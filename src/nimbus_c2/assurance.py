# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Assurance layer — situation-awareness health and autonomy-mode gating.

This module implements the rule-based autonomy decision that the
Nimbus-C2 architecture puts at the heart of the pitch:

    "You don't want an AI that's always confident. You want one that
     knows the edge of its envelope."

The layer computes three signals from the incoming tactical state —
track quality, situation complexity, and engagement stakes — combines
them into a composite SA-health score, and deterministically gates the
system into one of three autonomy modes (AUTONOMOUS, ADVISE, DEFER).

Every threshold here is a *policy* setting, not an empirical constant.
STRATEGY.md §Stage 2 calibrates these against held-out SAGAT-scored
simulation scenarios before any deployment. Until that calibration is
complete, these values are the engineering defaults derived from the
air-traffic-control situation-awareness literature (ATC cognitive-load
studies clustering around n≈15 concurrent tracks as the complexity
inflection point).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence, Tuple

from .models import CommandersIntent, Threat


# --------------------------------------------------------------------------- #
# Autonomy modes                                                              #
# --------------------------------------------------------------------------- #

class AutonomyMode(str, Enum):
    """Three deterministically-gated modes. Order = increasing human control."""
    AUTONOMOUS = "autonomous"   # system executes without operator confirmation
    ADVISE = "advise"           # system proposes; operator confirms
    DEFER = "defer"             # system refuses to act; full operator control


# --------------------------------------------------------------------------- #
# Thresholds (policy settings)                                                #
# --------------------------------------------------------------------------- #

AUTONOMY_THRESHOLDS: Dict[str, float] = {
    # Allow autonomous iff SA ≥ 75, complexity ≤ 0.60, stakes ≤ 0.80.
    "autonomous_sa_min": 75.0,          # SA health in [0, 100]
    "autonomous_complexity_max": 0.60,  # in [0, 1]
    "autonomous_stakes_max": 0.80,      # in [0, 1]
    # Hard DEFER guards.
    "defer_sa_max": 40.0,
    "defer_stakes_min": 0.90,
    "defer_stakes_sa_guard": 85.0,      # stakes ≥ 0.90 AND sa < 85 → DEFER
}


# --------------------------------------------------------------------------- #
# Inputs and outputs                                                          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class TrackQuality:
    """Composite track-quality record per threat."""
    track_id: str
    classification: float       # classifier confidence in [0, 1]
    kinematic: float            # kinematic-consistency score in [0, 1]
    sensor_agreement: float     # cross-sensor agreement in [0, 1]
    age_sec: float              # seconds since last update
    in_blind_spot: bool = False

    @property
    def composite(self) -> float:
        """Single scalar in [0, 1] combining all signals.

        Matches docs/ARCHITECTURE.md exactly:

            tq = (0.4 * class_conf + 0.3 * kinematic + 0.3 * sensor_agreement)
               * age_penalty
               * blind_spot_penalty

            age_penalty        = max(0, 1 - (age / 30)^2)
            blind_spot_penalty = 0.5 if in_blind_spot else 1.0
        """
        age_penalty = max(0.0, 1.0 - (self.age_sec / 30.0) ** 2)
        blind_penalty = 0.5 if self.in_blind_spot else 1.0
        raw = (
            0.4 * self.classification
            + 0.3 * self.kinematic
            + 0.3 * self.sensor_agreement
        )
        return max(0.0, min(1.0, raw * age_penalty * blind_penalty))


@dataclass(frozen=True)
class AssuranceReport:
    """Output of the assurance layer — consumed by every downstream stage."""
    sa_health: float                       # [0, 100]
    track_quality_index: float             # [0, 1]
    situation_complexity: float            # [0, 1]
    stakes: float                          # [0, 1]
    autonomy_mode: AutonomyMode
    reasons: List[str]                     # human-readable rationale
    alerts: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sa_health": round(self.sa_health, 1),
            "track_quality_index": round(self.track_quality_index, 3),
            "situation_complexity": round(self.situation_complexity, 3),
            "stakes": round(self.stakes, 3),
            "autonomy_mode": self.autonomy_mode.value,
            "reasons": list(self.reasons),
            "alerts": list(self.alerts),
        }


# --------------------------------------------------------------------------- #
# Geometric helpers                                                           #
# --------------------------------------------------------------------------- #

def _in_blind_spot(
    threat: Threat,
    blind_spots: Sequence[Tuple[float, float]],
    radius_km: float = 80.0,
) -> bool:
    """A threat falls in a blind spot if it is within ``radius_km`` of any
    listed blind-spot centre. Blind spots come from the coverage-gap
    analysis performed by the sensor-fusion layer upstream."""
    for (bx, by) in blind_spots:
        if math.hypot(threat.x - bx, threat.y - by) < radius_km:
            return True
    return False


def build_track_qualities(
    threats: Sequence[Threat],
    blind_spots: Sequence[Tuple[float, float]] = (),
) -> List[TrackQuality]:
    """Convert raw Threat records into per-track quality summaries."""
    return [
        TrackQuality(
            track_id=t.id,
            classification=t.class_confidence,
            kinematic=t.kinematic_consistency,
            sensor_agreement=t.sensor_agreement,
            age_sec=t.age_sec,
            in_blind_spot=_in_blind_spot(t, blind_spots),
        )
        for t in threats
    ]


# --------------------------------------------------------------------------- #
# Situation complexity                                                        #
# --------------------------------------------------------------------------- #

def compute_situation_complexity(
    threats: Sequence[Threat],
    track_qualities: Sequence[TrackQuality],
) -> float:
    """Complexity score in [0, 1].

    Three contributions, summed with fixed weights:

        count_factor = sigmoid((n - 15) / 4)      weight 0.45
        type_entropy = H(types) / log2(|types|)   weight 0.25
        low_q_frac   = fraction(tq.composite < 0.5)  weight 0.30

    The n=15 inflection point is drawn from the ATC cognitive-load
    literature; the weights encode "count dominates, ambiguity matters,
    degraded tracks matter most when many of them are present".
    """
    n = len(threats)
    if n == 0:
        return 0.0

    # Count saturation
    count_factor = 1.0 / (1.0 + math.exp(-(n - 15) / 4.0))

    # Shannon entropy over threat types
    type_counts: Dict[str, int] = {}
    for t in threats:
        type_counts[t.estimated_type] = type_counts.get(t.estimated_type, 0) + 1
    total = sum(type_counts.values())
    entropy = 0.0
    for c in type_counts.values():
        p = c / total
        if p > 0:
            entropy -= p * math.log2(p)
    max_entropy = math.log2(max(1, len(type_counts)))
    type_ambiguity = entropy / max_entropy if max_entropy > 0 else 0.0

    # Low-quality track fraction
    low_q = sum(1 for tq in track_qualities if tq.composite < 0.5)
    low_q_fraction = low_q / max(1, len(track_qualities))

    complexity = (
        0.45 * count_factor
        + 0.25 * type_ambiguity
        + 0.30 * low_q_fraction
    )
    return min(1.0, complexity)


# --------------------------------------------------------------------------- #
# Stakes                                                                      #
# --------------------------------------------------------------------------- #

def compute_stakes(
    threats: Sequence[Threat],
    protected_positions: Sequence[Tuple[float, float]],
) -> Tuple[float, List[str]]:
    """Stakes score in [0, 1] plus human-readable reasons.

    Two contributions:

        value_factor    = min(1, total_inbound_value / 500)         weight 0.6
        proximity_factor = max(0, 1 - min_dist_to_asset_km / 500)   weight 0.4
    """
    reasons: List[str] = []

    total_value = sum(t.threat_value for t in threats)
    value_factor = min(1.0, total_value / 500.0)
    if total_value > 300:
        reasons.append(f"high inbound value ({total_value:.0f})")

    if not protected_positions or not threats:
        return value_factor * 0.6, reasons

    min_dist = float("inf")
    for t in threats:
        for (ax, ay) in protected_positions:
            d = math.hypot(t.x - ax, t.y - ay)
            if d < min_dist:
                min_dist = d

    proximity_factor = 0.0
    if math.isfinite(min_dist):
        proximity_factor = max(0.0, 1.0 - min_dist / 500.0)
        if min_dist < 200:
            reasons.append(f"threat {min_dist:.0f}km from protected asset")

    stakes = 0.6 * value_factor + 0.4 * proximity_factor
    return min(1.0, stakes), reasons


# --------------------------------------------------------------------------- #
# Sensor-degradation alerts                                                   #
# --------------------------------------------------------------------------- #

def detect_alerts(track_qualities: Sequence[TrackQuality]) -> List[str]:
    """Surface-visible alerts for the commander's UI."""
    alerts: List[str] = []
    if not track_qualities:
        return alerts

    avg_agreement = sum(tq.sensor_agreement for tq in track_qualities) / len(track_qualities)
    if avg_agreement < 0.6:
        alerts.append("multi-sensor fusion: low agreement")

    blind_count = sum(1 for tq in track_qualities if tq.in_blind_spot)
    if blind_count > 0:
        alerts.append(f"{blind_count} track(s) in radar blind spot")

    stale = sum(1 for tq in track_qualities if tq.age_sec > 30)
    if stale > 0:
        alerts.append(f"{stale} stale track(s) (>30s since update)")

    return alerts


# --------------------------------------------------------------------------- #
# Autonomy gating                                                             #
# --------------------------------------------------------------------------- #

def decide_autonomy(
    sa_health: float,
    complexity: float,
    stakes: float,
    intent: CommandersIntent,
) -> Tuple[AutonomyMode, List[str]]:
    """Deterministic, rule-based autonomy gating.

    Order of precedence: DEFER guards evaluated first, then AUTONOMOUS
    permissions, otherwise ADVISE. Every branch appends to ``reasons``
    so the decision is fully explainable to the operator.
    """
    reasons: List[str] = []

    # DEFER: degraded SA.
    if sa_health < AUTONOMY_THRESHOLDS["defer_sa_max"]:
        reasons.append(f"SA health {sa_health:.0f}% below defer threshold")
        return AutonomyMode.DEFER, reasons

    # DEFER: high stakes with imperfect SA (subject to commander's intent).
    if stakes >= AUTONOMY_THRESHOLDS["defer_stakes_min"]:
        reasons.append(f"stakes {stakes:.2f} at defer threshold")
        if sa_health < AUTONOMY_THRESHOLDS["defer_stakes_sa_guard"]:
            return AutonomyMode.DEFER, reasons

    # AUTONOMOUS: fully inside the envelope.
    inside_envelope = (
        sa_health >= AUTONOMY_THRESHOLDS["autonomous_sa_min"]
        and complexity <= AUTONOMY_THRESHOLDS["autonomous_complexity_max"]
        and stakes <= AUTONOMY_THRESHOLDS["autonomous_stakes_max"]
    )
    if inside_envelope:
        reasons.append(
            f"SA {sa_health:.0f}%, complexity {complexity:.2f}, "
            f"stakes {stakes:.2f} — within envelope"
        )
        return AutonomyMode.AUTONOMOUS, reasons

    # Otherwise: ADVISE, with per-signal reasons.
    if sa_health < AUTONOMY_THRESHOLDS["autonomous_sa_min"]:
        reasons.append(f"SA {sa_health:.0f}% below autonomous threshold")
    if complexity > AUTONOMY_THRESHOLDS["autonomous_complexity_max"]:
        reasons.append(f"complexity {complexity:.2f} above autonomous threshold")
    if stakes > AUTONOMY_THRESHOLDS["autonomous_stakes_max"]:
        reasons.append(f"stakes {stakes:.2f} above autonomous threshold")
    return AutonomyMode.ADVISE, reasons


# --------------------------------------------------------------------------- #
# Top-level entry point                                                       #
# --------------------------------------------------------------------------- #

def build_assurance_report(
    threats: Sequence[Threat],
    protected_positions: Sequence[Tuple[float, float]],
    intent: CommandersIntent,
    blind_spots: Sequence[Tuple[float, float]] = (),
) -> AssuranceReport:
    """End-to-end assurance computation.

    Composition:

        track_qualities = build_track_qualities(threats, blind_spots)
        tqi             = mean(tq.composite)
        complexity      = compute_situation_complexity(...)
        stakes, reasons = compute_stakes(...)
        sa_health       = 100 * tqi * (1 - 0.35 * complexity)
        mode, mr        = decide_autonomy(sa_health, complexity, stakes, intent)

    All signals and reasons are returned in a single, deterministic
    ``AssuranceReport``. Same input always yields same report.
    """
    track_qualities = build_track_qualities(threats, blind_spots)

    if track_qualities:
        tqi = sum(tq.composite for tq in track_qualities) / len(track_qualities)
    else:
        tqi = 1.0

    complexity = compute_situation_complexity(threats, track_qualities)
    stakes, stakes_reasons = compute_stakes(threats, protected_positions)

    sa_health = 100.0 * tqi * (1.0 - 0.35 * complexity)
    sa_health = max(0.0, min(100.0, sa_health))

    alerts = detect_alerts(track_qualities)
    mode, mode_reasons = decide_autonomy(sa_health, complexity, stakes, intent)

    return AssuranceReport(
        sa_health=sa_health,
        track_quality_index=tqi,
        situation_complexity=complexity,
        stakes=stakes,
        autonomy_mode=mode,
        reasons=mode_reasons + stakes_reasons,
        alerts=alerts,
    )


__all__ = [
    "AUTONOMY_THRESHOLDS",
    "AssuranceReport",
    "AutonomyMode",
    "TrackQuality",
    "build_assurance_report",
    "build_track_qualities",
    "compute_situation_complexity",
    "compute_stakes",
    "decide_autonomy",
    "detect_alerts",
]
