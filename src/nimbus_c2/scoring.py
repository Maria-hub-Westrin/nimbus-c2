# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Shared feasibility and scoring for TEWA solvers.

Both the Hungarian and MILP solvers call into this module to compute
per-tuple utility and feasibility. Having a single source of truth for
the scoring function is what makes the Hungarian/MILP parity contract
(STRATEGY.md §4.3) testable: any discrepancy in solver output must come
from the optimisation, never from disagreeing cost matrices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .models import (
    Assignment,
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
    distance_km,
    sigmoid,
)


# --------------------------------------------------------------------------- #
# Per-tuple scoring                                                           #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Candidate:
    """An enumerated (base, effector, threat) tuple with pre-computed
    feasibility, timing, Pk, and utility.

    Candidate enumeration is deterministic: iteration order is
    ``(sorted bases, sorted effector names, sorted threats)``. This
    pins solver output order across runs.
    """
    base_idx: int
    base_name: str
    effector_name: str
    threat_idx: int
    threat_id: str
    distance_km: float
    pk_effective: float
    tti_sec: float        # time-to-intercept
    tta_sec: float        # time-to-asset (= time before threat reaches a protected asset)
    margin_sec: float     # tta - tti
    utility: float
    feasible: bool
    infeasibility_reason: str = ""


def effective_pk(
    effector: Effector,
    threat: Threat,
) -> float:
    """Effective Pk combining base Pk matrix with track quality.

    Implements the formula in ``docs/ARCHITECTURE.md``:

        Pk_eff = pk_matrix[e][type(t)] * (0.5 + 0.5 * track_quality)

    where ``track_quality`` is the composite of class confidence,
    kinematic consistency, and sensor agreement, age-penalised.
    """
    base_pk = effector.pk_matrix.get(threat.estimated_type, 0.0)

    # Track quality composite, matches docs/ARCHITECTURE.md.
    age_penalty = max(0.0, 1.0 - (threat.age_sec / 30.0) ** 2)
    tq_raw = (
        0.4 * threat.class_confidence
        + 0.3 * threat.kinematic_consistency
        + 0.3 * threat.sensor_agreement
    )
    tq = max(0.0, min(1.0, tq_raw * age_penalty))

    return max(0.0, min(1.0, base_pk * (0.5 + 0.5 * tq)))


def time_to_intercept_sec(
    base: Base,
    effector: Effector,
    threat: Threat,
) -> float:
    """Seconds from commit to weapon reaching threat.

    = response_time + distance / closing_speed.
    Closing speed is approximated as the effector's top speed (the
    threat's course is assumed non-helpful in the worst case). This is
    a deliberately conservative approximation.
    """
    d_km = distance_km(base.x, base.y, threat.x, threat.y)
    if effector.speed_kmh <= 0:
        return float("inf")
    travel_sec = d_km / effector.speed_kmh * 3600.0
    return effector.response_time_sec + travel_sec


def time_to_asset_sec(
    threat: Threat,
    protected_positions: Sequence[Tuple[float, float]],
) -> float:
    """Seconds until threat reaches its nearest protected asset."""
    if not protected_positions:
        return float("inf")
    if threat.speed_kmh <= 0:
        return float("inf")
    min_d = min(
        distance_km(threat.x, threat.y, ax, ay)
        for (ax, ay) in protected_positions
    )
    return min_d / threat.speed_kmh * 3600.0


def per_tuple_utility(
    pk: float,
    threat_value: float,
    margin_sec: float,
    effector: Effector,
    weights: ScoringWeights,
) -> float:
    """Linear utility, matching STRATEGY.md §4.2 exactly.

        u = w_value * Pk * threat_value
          + w_margin * margin_amplitude * sigmoid(margin_sec / margin_scale_sec)
          - cost_coef * cost_weight
    """
    return (
        weights.w_value * pk * threat_value
        + weights.w_margin
          * weights.margin_amplitude
          * sigmoid(margin_sec / weights.margin_scale_sec)
        - weights.cost_coef * effector.cost_weight
    )


# --------------------------------------------------------------------------- #
# Candidate enumeration                                                       #
# --------------------------------------------------------------------------- #

def enumerate_candidates(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights,
    protected_positions: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[Candidate]:
    """Enumerate all (base, effector, threat) tuples with feasibility.

    Iteration order is deterministic: bases sorted by ``name``,
    effectors sorted by ``name``, threats sorted by ``id``. This is
    what guarantees solver-independent output order in
    ``tests/test_milp_determinism.py``.
    """
    sorted_bases = sorted(enumerate(bases), key=lambda p: p[1].name)
    sorted_effectors = sorted(effectors.items(), key=lambda p: p[0])
    sorted_threats = sorted(enumerate(threats), key=lambda p: p[1].id)

    if protected_positions is None:
        caps = [(b.x, b.y) for b in bases if b.is_capital]
        protected_positions = caps if caps else [(b.x, b.y) for b in bases]

    candidates: List[Candidate] = []
    for b_idx, base in sorted_bases:
        for e_name, eff in sorted_effectors:
            # Gate on per-cycle capacity, not raw inventory. This is what
            # makes both Hungarian and MILP honour reserve_floor and
            # launchers_per_cycle by construction (Hungarian via
            # candidate-pruning, MILP additionally via the C2 constraint).
            if base.capacity(e_name) <= 0:
                continue
            for t_idx, threat in sorted_threats:
                d_km = distance_km(base.x, base.y, threat.x, threat.y)
                pk = effective_pk(eff, threat)
                tti = time_to_intercept_sec(base, eff, threat)
                tta = time_to_asset_sec(threat, protected_positions)
                margin = tta - tti
                u = per_tuple_utility(pk, threat.threat_value, margin, eff, weights)

                feasible = True
                reason = ""
                if d_km > eff.range_km:
                    feasible, reason = False, "out_of_range"
                elif d_km < eff.min_engage_km:
                    feasible, reason = False, "below_min_engage"
                elif margin < intent.min_safety_margin_sec:
                    feasible, reason = False, "insufficient_margin"
                elif pk < intent.min_pk_for_engage:
                    feasible, reason = False, "below_min_pk"

                candidates.append(Candidate(
                    base_idx=b_idx,
                    base_name=base.name,
                    effector_name=e_name,
                    threat_idx=t_idx,
                    threat_id=threat.id,
                    distance_km=d_km,
                    pk_effective=pk,
                    tti_sec=tti,
                    tta_sec=tta,
                    margin_sec=margin,
                    utility=u,
                    feasible=feasible,
                    infeasibility_reason=reason,
                ))
    return candidates


# --------------------------------------------------------------------------- #
# Assignment construction (used by both solvers)                              #
# --------------------------------------------------------------------------- #

def candidate_to_assignment(c: Candidate) -> Assignment:
    """Convert a chosen Candidate to the public Assignment type."""
    return Assignment(
        base_name=c.base_name,
        effector=c.effector_name,
        threat_id=c.threat_id,
        pk_effective=c.pk_effective,
        time_to_intercept_sec=c.tti_sec,
        time_to_asset_sec=c.tta_sec,
        margin_sec=c.margin_sec,
        utility=c.utility,
    )


__all__ = [
    "Candidate",
    "candidate_to_assignment",
    "effective_pk",
    "enumerate_candidates",
    "per_tuple_utility",
    "time_to_asset_sec",
    "time_to_intercept_sec",
]
