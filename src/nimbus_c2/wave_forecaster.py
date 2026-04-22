# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Wave forecaster — per-sector follow-on wave prediction.

Given the current inbound picture, partition the airspace around the
protected asset into azimuth sectors and forecast the likelihood and
expected value of follow-on arrivals over a short horizon. The output
informs the COA generator's reserve-conserving logic: do not burn all
SAMs now if the north sector is expected to stay hot for another 60 s.

This is a deliberately simple Poisson arrival model. Stage 3 can
replace it with a Bayesian filter over adversary doctrine, but the
simple version is explainable, deterministic, and sufficient for the
Stage-1/2 pitch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .models import Threat


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# Azimuth partition: four 90° sectors centred on N/E/S/W.
# Sector id maps to (lower_deg, upper_deg) half-open, with N wrapping.
SECTORS: Dict[str, Tuple[float, float]] = {
    "N": (315.0, 45.0),   # 315..360 ∪ 0..45
    "E": (45.0, 135.0),
    "S": (135.0, 225.0),
    "W": (225.0, 315.0),
}

# Amplification factor encoding "the enemy typically commits in waves":
# observed rate is multiplied by this to predict incoming-wave rate.
# 1.3 is the STRATEGY.md §Stage-2 default; calibrate before deployment.
WAVE_AMPLIFIER: float = 1.3

# Observation window for rate estimation.
RATE_WINDOW_SEC: float = 30.0

# Reserve-SAM heuristic: rounds recommended per unit of expected value.
RESERVE_SAM_PER_VALUE: float = 60.0


# --------------------------------------------------------------------------- #
# Dataclasses                                                                 #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SectorForecast:
    """Forecast for one azimuth sector."""
    sector_id: str
    n_current: int
    arrival_prob_60s: float                    # P(≥1 follow-on arrival in 60 s)
    expected_value: float                      # value likely to arrive
    recommended_reserve: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WaveForecast:
    """Top-level forecast bundling every sector."""
    horizon_sec: float
    total_expected_value: float
    follow_on_likelihood: float                # max over sectors
    sectors: List[SectorForecast] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "horizon_sec": self.horizon_sec,
            "total_expected_value": round(self.total_expected_value, 1),
            "follow_on_likelihood": round(self.follow_on_likelihood, 3),
            "sectors": [
                {
                    "sector_id": s.sector_id,
                    "n_current": s.n_current,
                    "arrival_prob_60s": round(s.arrival_prob_60s, 3),
                    "expected_value": round(s.expected_value, 1),
                    "recommended_reserve": dict(s.recommended_reserve),
                }
                for s in self.sectors
            ],
        }


# --------------------------------------------------------------------------- #
# Geometry                                                                    #
# --------------------------------------------------------------------------- #

def _azimuth_deg(x: float, y: float, ax: float, ay: float) -> float:
    """Azimuth from (ax, ay) to (x, y) in degrees, 0 = north, CW positive."""
    dx = x - ax
    dy = y - ay
    # atan2 returns math convention (0 = east, CCW); convert to compass.
    theta_math = math.degrees(math.atan2(dy, dx))   # [-180, 180]
    compass = (90.0 - theta_math) % 360.0           # 0 = north, CW positive
    return compass


def _sector_for_azimuth(az_deg: float) -> str:
    """Classify an azimuth into one of the four cardinal sectors."""
    az = az_deg % 360.0
    # Handle N wrap-around (315..360 ∪ 0..45).
    if az >= 315.0 or az < 45.0:
        return "N"
    if az < 135.0:
        return "E"
    if az < 225.0:
        return "S"
    return "W"


# --------------------------------------------------------------------------- #
# Forecast                                                                    #
# --------------------------------------------------------------------------- #

def forecast_waves(
    threats: Sequence[Threat],
    protected_position: Tuple[float, float],
    horizon_sec: float = 120.0,
    rate_window_sec: float = RATE_WINDOW_SEC,
) -> WaveForecast:
    """Produce a per-sector wave forecast relative to ``protected_position``.

    Model
    -----

    Treat current inbound threats as an observed Poisson sample over
    ``rate_window_sec``. Per sector:

        observed_rate   = n_threats_in_sector / rate_window_sec
        predicted_rate  = observed_rate * WAVE_AMPLIFIER
        p(>=1 in 60 s)  = 1 - exp(-predicted_rate * 60)
        expected_value  = avg_value_in_sector
                          * predicted_rate * horizon_sec
        reserve_sam     = ceil(expected_value / RESERVE_SAM_PER_VALUE)

    Returns a fully-populated WaveForecast. Deterministic: same input,
    same forecast, every call.
    """
    ax, ay = protected_position

    by_sector: Dict[str, List[Threat]] = {k: [] for k in SECTORS}
    for t in threats:
        az = _azimuth_deg(t.x, t.y, ax, ay)
        sid = _sector_for_azimuth(az)
        by_sector[sid].append(t)

    forecasts: List[SectorForecast] = []
    follow_on_likelihood = 0.0
    total_expected_value = 0.0

    # Deterministic order: N, E, S, W.
    for sid in ("N", "E", "S", "W"):
        bucket = by_sector[sid]
        n = len(bucket)
        if n == 0:
            forecasts.append(SectorForecast(
                sector_id=sid,
                n_current=0,
                arrival_prob_60s=0.0,
                expected_value=0.0,
                recommended_reserve={},
            ))
            continue

        observed_rate = n / rate_window_sec               # arrivals / sec
        predicted_rate = observed_rate * WAVE_AMPLIFIER
        arrival_prob_60s = 1.0 - math.exp(-predicted_rate * 60.0)
        avg_val = sum(t.threat_value for t in bucket) / n
        expected_value = avg_val * predicted_rate * horizon_sec
        total_expected_value += expected_value
        follow_on_likelihood = max(follow_on_likelihood, arrival_prob_60s)

        reserve_sam = int(math.ceil(expected_value / RESERVE_SAM_PER_VALUE))
        forecasts.append(SectorForecast(
            sector_id=sid,
            n_current=n,
            arrival_prob_60s=min(1.0, arrival_prob_60s),
            expected_value=expected_value,
            recommended_reserve={"sam": reserve_sam} if reserve_sam > 0 else {},
        ))

    return WaveForecast(
        horizon_sec=horizon_sec,
        total_expected_value=total_expected_value,
        follow_on_likelihood=follow_on_likelihood,
        sectors=forecasts,
    )


__all__ = [
    "RATE_WINDOW_SEC",
    "RESERVE_SAM_PER_VALUE",
    "SECTORS",
    "SectorForecast",
    "WAVE_AMPLIFIER",
    "WaveForecast",
    "forecast_waves",
]
