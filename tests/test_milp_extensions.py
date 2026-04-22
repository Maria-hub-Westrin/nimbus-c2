# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Stage-1 MILP extension tests.

These verify that the MILP enforces the constraints the Hungarian LAP
cannot: coordinated fire (K_t ≥ 2), hard capacity, hard reserve floor,
and hard min-Pk. Pass conditions are declarative — they describe what
the *output* must satisfy regardless of internal solver choices.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.models import (  # noqa: E402
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
)
from nimbus_c2.milp_tewa import solve_milp  # noqa: E402
from nimbus_c2.hungarian_tewa import solve_hungarian  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_EFFECTORS = {
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


def _threat(
    tid: str,
    x: float = 50.0,
    y: float = 50.0,
    type_: str = "bomber",
    value: float = 100.0,
    speed: float = 800.0,
) -> Threat:
    return Threat(
        id=tid,
        x=x,
        y=y,
        speed_kmh=speed,
        heading_deg=180.0,
        estimated_type=type_,
        threat_value=value,
        class_confidence=0.95,
        kinematic_consistency=0.95,
        sensor_agreement=1.0,
        age_sec=5.0,
    )


def _base(
    name: str = "B0",
    x: float = 0.0,
    y: float = 0.0,
    inv_sam: int = 10,
    inv_drone: int = 10,
    reserve_sam: int = 0,
    launchers_sam: int = 1,
    launchers_drone: int = 1,
) -> Base:
    return Base(
        name=name,
        x=x,
        y=y,
        inventory={"sam": inv_sam, "drone": inv_drone},
        is_capital=True,
        reserve_floor={"sam": reserve_sam},
        launchers_per_cycle={"sam": launchers_sam, "drone": launchers_drone},
    )


# --------------------------------------------------------------------------- #
# C1: coordinated fire (K_t >= 2)                                             #
# --------------------------------------------------------------------------- #

def test_coordinated_fire_allows_two_effectors_per_threat() -> None:
    """With K_t=2 and 2 shooters against 1 high-value threat, MILP uses both."""
    bases = [_base(name="B0", launchers_sam=1, launchers_drone=1)]
    threats = [_threat("T0", type_="bomber", value=200.0)]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=2,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    # Both effectors should engage the single threat.
    effectors_used = {a.effector for a in r.assignments}
    threats_engaged = {a.threat_id for a in r.assignments}
    assert threats_engaged == {"T0"}
    assert effectors_used == {"sam", "drone"}
    assert len(r.assignments) == 2


def test_coordinated_fire_respects_K_t_limit() -> None:
    """With K_t=1, MILP never assigns two effectors to one threat."""
    bases = [_base(name="B0", launchers_sam=1, launchers_drone=1)]
    threats = [_threat("T0", type_="bomber", value=200.0)]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    # Only one of the two effectors engages, not both.
    assert len(r.assignments) == 1


# --------------------------------------------------------------------------- #
# C2: capacity and reserve floor as HARD constraints                          #
# --------------------------------------------------------------------------- #

def test_launcher_capacity_hard_constraint() -> None:
    """Base with 1 SAM launcher cannot fire 2 SAMs in one cycle, regardless
    of inventory."""
    bases = [_base(name="B0", inv_sam=100, launchers_sam=1)]
    threats = [_threat("T0"), _threat("T1", x=30, y=30)]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )
    r = solve_milp(bases, _EFFECTORS, threats, intent)

    # At most one SAM engagement from B0 in this cycle.
    sam_assignments_b0 = [
        a for a in r.assignments
        if a.base_name == "B0" and a.effector == "sam"
    ]
    assert len(sam_assignments_b0) <= 1


def test_reserve_floor_hard_constraint() -> None:
    """Reserve floor withholds rounds from the MILP's usable capacity."""
    # Inventory 2, reserve 2 → capacity 0. No SAMs should be fired.
    bases = [_base(name="B0", inv_sam=2, reserve_sam=2, launchers_sam=1)]
    threats = [_threat("T0")]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    sam_assignments = [a for a in r.assignments if a.effector == "sam"]
    assert len(sam_assignments) == 0, (
        f"Reserve floor violated: {sam_assignments}"
    )


def test_milp_closes_reserve_gap_where_hungarian_is_silent() -> None:
    """Documenting the closed gap: MILP enforces reserve as a hard capacity
    constraint via Base.capacity(); Hungarian's LAP structure alone doesn't.

    In this scenario inventory = 2, reserve = 2, so capacity() = 0.
    MILP refuses to assign (test_reserve_floor_hard_constraint). This
    test asserts the same is true of Hungarian — which requires the
    enumerate_candidates pruning to check capacity, not just inventory.
    """
    bases = [_base(name="B0", inv_sam=2, reserve_sam=2, launchers_sam=1)]
    threats = [_threat("T0")]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )
    r_h = solve_hungarian(bases, _EFFECTORS, threats, intent)
    r_m = solve_milp(bases, _EFFECTORS, threats, intent)

    # Contract: both solvers respect reserve floor, via different mechanisms.
    # Hungarian: candidate enumeration prunes (b, e) with capacity == 0.
    # MILP: capacity constraint C2 with RHS = capacity(b, e).
    assert len([a for a in r_h.assignments if a.effector == "sam"]) == 0
    assert len([a for a in r_m.assignments if a.effector == "sam"]) == 0


# --------------------------------------------------------------------------- #
# C3: min-Pk floor as HARD feasibility                                        #
# --------------------------------------------------------------------------- #

def test_min_pk_floor_prunes_low_quality_shots() -> None:
    """Raising min_pk_for_engage above achievable Pk yields no engagements."""
    # Drone effector has Pk=0.1 against fast-mover; floor at 0.5 prunes it.
    bases = [_base(name="B0", inv_sam=0, inv_drone=3, launchers_drone=1)]
    bases[0] = Base(
        name="B0", x=0.0, y=0.0,
        inventory={"drone": 3, "sam": 0},
        is_capital=True,
        reserve_floor={},
        launchers_per_cycle={"drone": 1, "sam": 1},
    )
    threats = [_threat("T0", type_="fast-mover")]
    intent = CommandersIntent(
        min_pk_for_engage=0.5,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    assert len(r.assignments) == 0, (
        f"Below-floor engagement slipped through: {r.assignments}"
    )


def test_min_pk_floor_permits_qualified_shots() -> None:
    """With an effector that meets the Pk floor, engagement proceeds."""
    # SAM has Pk=0.95 against bomber; floor at 0.5 is easily satisfied.
    bases = [_base(name="B0", inv_sam=3, launchers_sam=1)]
    threats = [_threat("T0", type_="bomber")]
    intent = CommandersIntent(
        min_pk_for_engage=0.5,
        min_safety_margin_sec=-1e9,
        max_effectors_per_threat=1,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    assert len(r.assignments) == 1
    assert r.assignments[0].effector == "sam"
    assert r.assignments[0].pk_effective >= 0.5


# --------------------------------------------------------------------------- #
# Timing feasibility                                                          #
# --------------------------------------------------------------------------- #

def test_insufficient_margin_prunes_engagement() -> None:
    """Threat arriving faster than any shooter can intercept → no assignment."""
    # Threat 200km away moving at 3000 kmh: TTA ≈ 240s.
    # SAM has response_time 10s + travel 200/3000*3600 = 240s; TTI ≈ 250s.
    # Margin ≈ -10s — infeasible under min_safety_margin_sec = 5.
    bases = [_base(name="B0", x=0, y=0)]
    threats = [_threat("T0", x=200, y=0, speed=3000.0, type_="bomber")]
    intent = CommandersIntent(
        min_pk_for_engage=0.0,
        min_safety_margin_sec=5.0,
        max_effectors_per_threat=1,
    )

    r = solve_milp(bases, _EFFECTORS, threats, intent)

    assert len(r.assignments) == 0
