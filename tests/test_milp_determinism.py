# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Stage-1 determinism contract tests.

Verifies STRATEGY.md §4.5 exit gate:

    "1000 repeated runs on identical input yield bit-identical result
     ordering (modulo ties; assignment set identical)."

Determinism is the single property that differentiates a defense-grade
decision engine from a research prototype. This test is what Saab
engineers will look at first.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.hungarian_tewa import solve_hungarian  # noqa: E402
from nimbus_c2.milp_tewa import solve_milp  # noqa: E402
from nimbus_c2.models import (  # noqa: E402
    Assignment,
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
)

_EFFECTORS = {
    "fighter": Effector(
        name="fighter", speed_kmh=2000.0, cost_weight=50.0,
        pk_matrix={"drone": 0.7, "bomber": 0.9, "fast-mover": 0.8},
        range_km=1200.0, min_engage_km=0.0, response_time_sec=60.0,
    ),
    "sam": Effector(
        name="sam", speed_kmh=3000.0, cost_weight=80.0,
        pk_matrix={"drone": 0.9, "bomber": 0.95, "fast-mover": 0.7},
        range_km=400.0, min_engage_km=0.0, response_time_sec=10.0,
    ),
    "drone": Effector(
        name="drone", speed_kmh=400.0, cost_weight=10.0,
        pk_matrix={"drone": 0.8, "bomber": 0.4, "fast-mover": 0.1},
        range_km=300.0, min_engage_km=0.0, response_time_sec=30.0,
    ),
}


def _canonical_scenario() -> tuple[list[Base], list[Threat]]:
    """A single fixed scenario. Not randomised — determinism is tested
    across runs of the *same* input."""
    bases = [
        Base(
            name="Alpha", x=0, y=0,
            inventory={"fighter": 4, "sam": 8, "drone": 6},
            is_capital=True,
        ),
        Base(
            name="Bravo", x=150, y=100,
            inventory={"fighter": 3, "sam": 4, "drone": 10},
        ),
        Base(
            name="Charlie", x=-100, y=200,
            inventory={"fighter": 2, "sam": 6, "drone": 4},
        ),
    ]
    threats = [
        Threat(id="T01", x=120, y=80, speed_kmh=800, heading_deg=200,
               estimated_type="bomber", threat_value=95.0),
        Threat(id="T02", x=-50, y=150, speed_kmh=1200, heading_deg=170,
               estimated_type="fast-mover", threat_value=70.0),
        Threat(id="T03", x=50, y=-30, speed_kmh=300, heading_deg=0,
               estimated_type="drone", threat_value=20.0),
        Threat(id="T04", x=200, y=50, speed_kmh=900, heading_deg=245,
               estimated_type="bomber", threat_value=85.0),
    ]
    return bases, threats


def _assignment_key(a: Assignment) -> tuple:
    return (a.base_name, a.effector, a.threat_id)


def _assignment_set(assignments) -> frozenset:
    return frozenset(_assignment_key(a) for a in assignments)


N_REPEATS = 1000


def test_hungarian_determinism() -> None:
    """1000 Hungarian runs on identical input yield identical assignment set."""
    bases, threats = _canonical_scenario()
    intent = CommandersIntent(min_pk_for_engage=0.0,
                               min_safety_margin_sec=-1e9,
                               max_effectors_per_threat=1)
    w = ScoringWeights()

    first = solve_hungarian(bases, _EFFECTORS, threats, intent, w)
    first_set = _assignment_set(first.assignments)
    first_util = first.total_utility

    for i in range(N_REPEATS):
        r = solve_hungarian(bases, _EFFECTORS, threats, intent, w)
        assert _assignment_set(r.assignments) == first_set, f"drift at {i}"
        assert abs(r.total_utility - first_util) < 1e-9


def test_milp_determinism() -> None:
    """1000 MILP runs on identical input yield identical assignment set."""
    bases, threats = _canonical_scenario()
    intent = CommandersIntent(min_pk_for_engage=0.0,
                               min_safety_margin_sec=-1e9,
                               max_effectors_per_threat=1)
    w = ScoringWeights()

    first = solve_milp(bases, _EFFECTORS, threats, intent, w)
    first_set = _assignment_set(first.assignments)
    first_util = first.total_utility

    for i in range(N_REPEATS):
        r = solve_milp(bases, _EFFECTORS, threats, intent, w)
        assert _assignment_set(r.assignments) == first_set, f"drift at {i}"
        assert abs(r.total_utility - first_util) < 1e-9


def test_output_is_sorted_canonically() -> None:
    """Output assignments are in sorted (base, effector, threat_id) order.

    This matters for human diffing, for SITREP rendering, for test
    stability, and for downstream serialisation hash-equality.
    """
    bases, threats = _canonical_scenario()
    intent = CommandersIntent(min_pk_for_engage=0.0,
                               min_safety_margin_sec=-1e9,
                               max_effectors_per_threat=1)
    w = ScoringWeights()

    for solver_fn in (solve_hungarian, solve_milp):
        r = solver_fn(bases, _EFFECTORS, threats, intent, w)
        keys = [_assignment_key(a) for a in r.assignments]
        assert keys == sorted(keys), f"{solver_fn.__name__} unsorted: {keys}"
