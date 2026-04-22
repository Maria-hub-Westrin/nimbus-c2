# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Course-of-Action generator — three tradeoff-explicit recommendations.

Given a tactical state, produce three alternative assignments with
different philosophies. This is the heart of the pitch: "the commander
always sees alternatives, not just an answer."

    1. RECOMMENDED        — balanced utility, the MILP's primary solution
    2. RESERVE_CONSERVING — stricter reserve floor, saves effectors for
                            the next wave at the cost of higher current-wave leak
    3. RISK_MINIMIZING    — higher Pk floor AND more effectors per threat
                            if intent allows, at the cost of more ammo spent

Each COA is solved by the same deterministic MILP with different
intent parameters. The three outputs are ranked, annotated with a
plain-language philosophy, and presented together.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Sequence

from .milp_tewa import solve_milp
from .models import (
    Assignment,
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    TEWAResult,
    Threat,
)
from .wave_forecaster import WaveForecast


# --------------------------------------------------------------------------- #
# COA descriptors                                                             #
# --------------------------------------------------------------------------- #

class COALabel(str, Enum):
    RECOMMENDED = "recommended"
    RESERVE_CONSERVING = "reserve_conserving"
    RISK_MINIMIZING = "risk_minimizing"


@dataclass(frozen=True)
class COA:
    """A single Course of Action, fully annotated for operator display."""
    label: COALabel
    philosophy: str                          # one-sentence plain-language summary
    assignments: List[Assignment]
    total_utility: float
    predicted_coverage: float                # fraction of total value engaged
    reserves_spent: Dict[str, int]           # effector → rounds used
    risk_if_follow_on: float                 # proxy for "how exposed we are next wave"
    # Monte Carlo uncertainty placeholders — populated by the uncertainty layer in Stage 2.
    survival_estimate: float = 0.0
    survival_stddev: float = 0.0

    def as_dict(self) -> dict:
        return {
            "label": self.label.value,
            "philosophy": self.philosophy,
            "assignments": [
                {
                    "base_name": a.base_name,
                    "effector": a.effector,
                    "threat_id": a.threat_id,
                    "pk_effective": round(a.pk_effective, 3),
                    "time_to_intercept_sec": round(a.time_to_intercept_sec, 1),
                    "time_to_asset_sec": round(a.time_to_asset_sec, 1),
                    "margin_sec": round(a.margin_sec, 1),
                    "utility": round(a.utility, 2),
                }
                for a in self.assignments
            ],
            "total_utility": round(self.total_utility, 2),
            "predicted_coverage": round(self.predicted_coverage, 3),
            "reserves_spent": dict(self.reserves_spent),
            "risk_if_follow_on": round(self.risk_if_follow_on, 3),
            "survival_estimate": round(self.survival_estimate, 1),
            "survival_stddev": round(self.survival_stddev, 1),
        }


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _reserves_spent(result: TEWAResult) -> Dict[str, int]:
    """Count rounds consumed per effector type."""
    counts: Dict[str, int] = {}
    for a in result.assignments:
        counts[a.effector] = counts.get(a.effector, 0) + 1
    return counts


def _predicted_coverage(
    result: TEWAResult,
    threats: Sequence[Threat],
) -> float:
    """Fraction of total inbound threat value engaged.

    Proxy for "how much of the threat we addressed". 1.0 = every
    threat has at least one engagement; 0.0 = none engaged.
    """
    total_value = sum(t.threat_value for t in threats) or 1.0
    engaged_ids = {a.threat_id for a in result.assignments}
    engaged_value = sum(t.threat_value for t in threats if t.id in engaged_ids)
    return min(1.0, engaged_value / total_value)


def _risk_if_follow_on(
    reserves_spent: Mapping[str, int],
    bases: Sequence[Base],
    forecast: WaveForecast,
) -> float:
    """Risk proxy: how exposed are we if the forecast is right.

    Computed as the ratio of forecast-recommended-reserve to
    remaining-inventory-after-this-COA. 1.0 = we just spent the
    inventory the forecast says we'll need; 0.0 = no follow-on
    exposure predicted.
    """
    recommended_reserve: Dict[str, int] = {}
    for sec in forecast.sectors:
        for eff, rsv in sec.recommended_reserve.items():
            recommended_reserve[eff] = recommended_reserve.get(eff, 0) + rsv

    if not recommended_reserve:
        return 0.0

    # Total remaining inventory per effector across all bases after this COA.
    remaining: Dict[str, int] = {}
    for b in bases:
        for eff, inv in b.inventory.items():
            spent = reserves_spent.get(eff, 0)
            remaining[eff] = remaining.get(eff, 0) + max(0, inv - spent)

    worst = 0.0
    for eff, need in recommended_reserve.items():
        have = remaining.get(eff, 0)
        if need <= 0:
            continue
        shortage = max(0.0, (need - have) / need)
        worst = max(worst, shortage)
    return min(1.0, worst)


# --------------------------------------------------------------------------- #
# Variant constructors                                                        #
# --------------------------------------------------------------------------- #

def _run_recommended(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights,
    forecast: WaveForecast,
) -> COA:
    r = solve_milp(bases, effectors, threats, intent, weights)
    spent = _reserves_spent(r)
    return COA(
        label=COALabel.RECOMMENDED,
        philosophy="Balanced utility. Maximises expected damage averted "
                   "per unit ammunition at the commander's current ROE.",
        assignments=list(r.assignments),
        total_utility=r.total_utility,
        predicted_coverage=_predicted_coverage(r, threats),
        reserves_spent=spent,
        risk_if_follow_on=_risk_if_follow_on(spent, bases, forecast),
    )


def _run_reserve_conserving(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights,
    forecast: WaveForecast,
) -> COA:
    """Temporarily add a reserve floor that withholds half of each
    high-value effector's inventory."""
    stricter_bases: List[Base] = []
    for b in bases:
        new_reserve: Dict[str, int] = dict(b.reserve_floor)
        for eff_name, inv in b.inventory.items():
            # Protect expensive effectors (fighter, sam); let cheap ones
            # (drone) be fully usable.
            eff = effectors.get(eff_name)
            if eff is None:
                continue
            if eff.cost_weight >= 50.0:
                held = max(new_reserve.get(eff_name, 0), inv // 2)
                new_reserve[eff_name] = held
        stricter_bases.append(Base(
            name=b.name, x=b.x, y=b.y,
            inventory=b.inventory,
            is_capital=b.is_capital,
            reserve_floor=new_reserve,
            launchers_per_cycle=b.launchers_per_cycle,
        ))

    r = solve_milp(stricter_bases, effectors, threats, intent, weights)
    spent = _reserves_spent(r)
    return COA(
        label=COALabel.RESERVE_CONSERVING,
        philosophy="Preserves 50 % of each expensive effector's inventory for "
                   "follow-on waves. Accepts higher current-wave leak "
                   "in exchange for multi-wave survivability.",
        assignments=list(r.assignments),
        total_utility=r.total_utility,
        predicted_coverage=_predicted_coverage(r, threats),
        reserves_spent=spent,
        risk_if_follow_on=_risk_if_follow_on(spent, bases, forecast),
    )


def _run_risk_minimizing(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights,
    forecast: WaveForecast,
) -> COA:
    """Raise Pk floor to demand higher-confidence shots; allow up to
    two effectors per threat for coordinated fire."""
    stricter_intent = CommandersIntent(
        roe_tier=intent.roe_tier,
        min_pk_for_engage=max(intent.min_pk_for_engage, 0.70),
        min_safety_margin_sec=max(intent.min_safety_margin_sec, 8.0),
        max_effectors_per_threat=max(intent.max_effectors_per_threat, 2),
    )
    r = solve_milp(bases, effectors, threats, stricter_intent, weights)
    spent = _reserves_spent(r)
    return COA(
        label=COALabel.RISK_MINIMIZING,
        philosophy="Higher Pk floor (0.70) and coordinated fire where available. "
                   "Accepts more ammunition spent in exchange for lower "
                   "per-engagement miss probability.",
        assignments=list(r.assignments),
        total_utility=r.total_utility,
        predicted_coverage=_predicted_coverage(r, threats),
        reserves_spent=spent,
        risk_if_follow_on=_risk_if_follow_on(spent, bases, forecast),
    )


# --------------------------------------------------------------------------- #
# Top-level                                                                   #
# --------------------------------------------------------------------------- #

def generate_coas(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    forecast: WaveForecast,
    weights: ScoringWeights | None = None,
) -> List[COA]:
    """Produce the three COAs, in deterministic label order."""
    w = weights if weights is not None else ScoringWeights()
    return [
        _run_recommended(bases, effectors, threats, intent, w, forecast),
        _run_reserve_conserving(bases, effectors, threats, intent, w, forecast),
        _run_risk_minimizing(bases, effectors, threats, intent, w, forecast),
    ]


__all__ = [
    "COA",
    "COALabel",
    "generate_coas",
]
