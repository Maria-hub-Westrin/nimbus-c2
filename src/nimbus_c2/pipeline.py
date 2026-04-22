# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
End-to-end Nimbus-C2 evaluation pipeline.

Orchestrates the current-stage modules in the canonical order:

    1. assurance layer        — SA health, autonomy mode
    2. wave forecaster        — per-sector follow-on forecast
    3. COA generator          — three alternatives via MILP
    4. SITREP                 — deterministic human-facing summary

Stages 2–3 layers (conformal, OOD, epistemic, shield) sit between
assurance and COAs when implemented; feature flags will toggle them
on without changing this orchestration.

**Determinism contract:** ``evaluate(state)`` with identical
arguments yields a byte-identical ``EvaluationResult`` across runs,
processes, and Python versions. No hidden state, no global RNG.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Sequence, Tuple

from .assurance import AssuranceReport, build_assurance_report
from .coa_generator import COA, generate_coas
from .models import (
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
)
from .sitrep import SITREP, build_offline_sitrep
from .wave_forecaster import WaveForecast, forecast_waves


@dataclass(frozen=True)
class EvaluationResult:
    """Complete Nimbus-C2 evaluation output."""
    assurance: AssuranceReport
    forecast: WaveForecast
    coas: List[COA]
    sitrep: SITREP
    n_threats: int
    total_threat_value: float

    def as_dict(self) -> dict:
        return {
            "assurance": self.assurance.as_dict(),
            "forecast": self.forecast.as_dict(),
            "coas": [c.as_dict() for c in self.coas],
            "sitrep": self.sitrep.as_dict(),
            "summary": {
                "n_threats": self.n_threats,
                "total_threat_value": round(self.total_threat_value, 1),
            },
        }


def evaluate(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    blind_spots: Sequence[Tuple[float, float]] = (),
    weights: ScoringWeights | None = None,
) -> EvaluationResult:
    """One-shot end-to-end evaluation.

    Parameters
    ----------
    bases, effectors, threats, intent :
        Tactical state; see ``models.py``.
    blind_spots :
        Known sensor-coverage gaps, as (x, y) in km.
    weights :
        Scoring coefficients; ``None`` selects canonical defaults.

    Returns
    -------
    EvaluationResult
        Assurance + forecast + three COAs + SITREP. Deterministic.
    """
    # Step 1: assurance layer decides autonomy mode.
    protected_positions: List[Tuple[float, float]] = [
        (b.x, b.y) for b in bases if b.is_capital
    ]
    if not protected_positions:
        protected_positions = [(b.x, b.y) for b in bases]

    assurance = build_assurance_report(
        threats=threats,
        protected_positions=protected_positions,
        intent=intent,
        blind_spots=blind_spots,
    )

    # Step 2: wave forecast for the primary protected asset.
    primary_asset = protected_positions[0]
    forecast = forecast_waves(threats, primary_asset)

    # Step 3: three COAs via the MILP solver (deterministic).
    coas = generate_coas(bases, effectors, threats, intent, forecast, weights)

    # Step 4: deterministic SITREP from the above.
    total_value = sum(t.threat_value for t in threats)
    sitrep = build_offline_sitrep(
        assurance=assurance,
        forecast=forecast,
        coas=coas,
        n_threats=len(threats),
        total_threat_value=total_value,
    )

    return EvaluationResult(
        assurance=assurance,
        forecast=forecast,
        coas=coas,
        sitrep=sitrep,
        n_threats=len(threats),
        total_threat_value=total_value,
    )


__all__ = ["EvaluationResult", "evaluate"]
