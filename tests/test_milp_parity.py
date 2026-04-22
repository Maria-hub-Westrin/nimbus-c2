# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Stage-1 parity contract tests.

Verifies the contract in STRATEGY.md §4.3:

    When the MILP is configured with K_t = 1, capacity large, no
    reserve floor, and min_pk = 0 (or not binding), it solves the same
    LAP as Hungarian and returns the same **objective value** within
    1e-6.

Note: assignment *identity* can differ between solvers when ties exist
in the utility. Parity is asserted on objective, not on specific pairs.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

# Make "core" importable when tests are run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.hungarian_tewa import solve_hungarian  # noqa: E402
from nimbus_c2.milp_tewa import solve_milp  # noqa: E402
from nimbus_c2.models import (  # noqa: E402
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
)

# --------------------------------------------------------------------------- #
# Scenario generator                                                          #
# --------------------------------------------------------------------------- #

# Keep thresholds permissive so most pairings are feasible — parity is
# about the optimiser behaviour, not the feasibility pruning.
_PARITY_INTENT = CommandersIntent(
    min_pk_for_engage=0.0,
    min_safety_margin_sec=-1e9,      # essentially disabled
    max_effectors_per_threat=1,
)

_EFFECTORS = {
    "fighter": Effector(
        name="fighter",
        speed_kmh=2000.0,
        cost_weight=50.0,
        pk_matrix={"drone": 0.7, "bomber": 0.9, "fast-mover": 0.8},
        range_km=1200.0,
        min_engage_km=0.0,
        response_time_sec=60.0,
    ),
    "sam": Effector(
        name="sam",
        speed_kmh=3000.0,
        cost_weight=80.0,
        pk_matrix={"drone": 0.9, "bomber": 0.95, "fast-mover": 0.7},
        range_km=400.0,
        min_engage_km=0.0,
        response_time_sec=10.0,
    ),
    "drone": Effector(
        name="drone",
        speed_kmh=400.0,
        cost_weight=10.0,
        pk_matrix={"drone": 0.8, "bomber": 0.4, "fast-mover": 0.1},
        range_km=300.0,
        min_engage_km=0.0,
        response_time_sec=30.0,
    ),
}


def _make_scenario(
    seed: int,
    n_bases: int = 3,
    n_threats: int = 5,
) -> tuple[list[Base], list[Threat]]:
    """Deterministic random scenario for parity testing."""
    rng = random.Random(seed)
    bases = []
    for i in range(n_bases):
        bases.append(Base(
            name=f"B{i}",
            x=rng.uniform(-200, 200),
            y=rng.uniform(-200, 200),
            # Large inventory so capacity is not binding.
            inventory={"fighter": 50, "sam": 50, "drone": 50},
            is_capital=(i == 0),
            reserve_floor={},
        ))

    threat_types = ["drone", "bomber", "fast-mover"]
    threats = []
    for j in range(n_threats):
        threats.append(Threat(
            id=f"T{j}",
            x=rng.uniform(-250, 250),
            y=rng.uniform(-250, 250),
            speed_kmh=rng.uniform(200, 1500),
            heading_deg=rng.uniform(0, 359),
            estimated_type=rng.choice(threat_types),
            threat_value=rng.uniform(10, 100),
            class_confidence=rng.uniform(0.5, 1.0),
            kinematic_consistency=rng.uniform(0.5, 1.0),
            sensor_agreement=rng.uniform(0.5, 1.0),
            age_sec=rng.uniform(0, 25),
        ))
    return bases, threats


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("seed", range(50))
def test_parity_small_scenarios(seed: int) -> None:
    """50 seeded small scenarios: MILP objective == Hungarian objective."""
    bases, threats = _make_scenario(seed=seed, n_bases=3, n_threats=5)
    w = ScoringWeights()

    r_h = solve_hungarian(bases, _EFFECTORS, threats, _PARITY_INTENT, w)
    r_m = solve_milp(bases, _EFFECTORS, threats, _PARITY_INTENT, w)

    assert abs(r_h.total_utility - r_m.total_utility) < 1e-6, (
        f"Parity violation seed={seed}: "
        f"H={r_h.total_utility:.6f} vs MILP={r_m.total_utility:.6f}"
    )
    # Both solvers see the same feasible-pair count (same pruning).
    assert r_h.feasible_pairs == r_m.feasible_pairs


@pytest.mark.parametrize("seed", range(20))
def test_parity_medium_scenarios(seed: int) -> None:
    """20 medium scenarios (6 bases × 12 threats)."""
    bases, threats = _make_scenario(seed=seed + 1000, n_bases=6, n_threats=12)
    w = ScoringWeights()

    r_h = solve_hungarian(bases, _EFFECTORS, threats, _PARITY_INTENT, w)
    r_m = solve_milp(bases, _EFFECTORS, threats, _PARITY_INTENT, w)

    assert abs(r_h.total_utility - r_m.total_utility) < 1e-6, (
        f"Parity violation seed={seed}: "
        f"H={r_h.total_utility:.6f} vs MILP={r_m.total_utility:.6f}"
    )


def test_empty_inputs() -> None:
    """No threats → both solvers return empty assignment, zero utility."""
    bases, _ = _make_scenario(seed=0, n_bases=2, n_threats=0)
    w = ScoringWeights()

    r_h = solve_hungarian(bases, _EFFECTORS, [], _PARITY_INTENT, w)
    r_m = solve_milp(bases, _EFFECTORS, [], _PARITY_INTENT, w)

    assert r_h.assignments == []
    assert r_m.assignments == []
    assert r_h.total_utility == 0.0
    assert r_m.total_utility == 0.0


def test_solver_identity_strings() -> None:
    """Output labels the solver used — diagnostics and telemetry rely on this."""
    bases, threats = _make_scenario(seed=42)
    w = ScoringWeights()

    r_h = solve_hungarian(bases, _EFFECTORS, threats, _PARITY_INTENT, w)
    r_m = solve_milp(bases, _EFFECTORS, threats, _PARITY_INTENT, w)

    assert r_h.solver == "hungarian"
    assert r_m.solver.startswith("milp_")
