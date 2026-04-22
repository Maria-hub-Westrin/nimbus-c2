# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Reference data model for the Stage-1 TEWA core.

These dataclasses are the **authoritative interface** consumed by both the
Hungarian reference solver (`hungarian_tewa.py`) and the MILP solver
(`milp_tewa.py`). The goal of this module is to be:

  * minimal — no optional cruft; every field has a role in scoring or
    feasibility;
  * typed — every field declares its type; mypy --strict clean;
  * deterministic — no runtime randomness, no sets of mutable
    dataclasses (iteration order would vary by hash seed).

The types here are a subset of the project-wide model in
``src/models.py``. When the two diverge, this file is the reference for
Stage-1 solvers. Later stages (conformal, OOD, ensemble) extend the
``Threat`` type with additional fields via composition, never mutation.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------------- #
# Effector registry                                                           #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Effector:
    """A class of weapon system available at one or more bases.

    Attributes
    ----------
    name : str
        Canonical identifier. Matches the key in ``Base.inventory``.
    speed_kmh : float
        Top speed. Used for time-to-intercept in conjunction with base-
        to-threat closing geometry.
    cost_weight : float
        Relative consumption cost. Appears in the utility as ``-0.05 *
        cost_weight``.
    pk_matrix : Mapping[str, float]
        Base probability-of-kill keyed by threat ``estimated_type``.
        Effective Pk layers sensor-agreement and track-quality on top.
    range_km : float
        Maximum engagement distance from base.
    min_engage_km : float
        Minimum engagement distance (weapon fuze / arming radius).
    response_time_sec : float
        Commit-to-launch time. Enters the time-to-intercept budget.
    """
    name: str
    speed_kmh: float
    cost_weight: float
    pk_matrix: Mapping[str, float]
    range_km: float = 400.0
    min_engage_km: float = 0.0
    response_time_sec: float = 15.0


# --------------------------------------------------------------------------- #
# Bases                                                                       #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Base:
    """A fixed defensive installation with an inventory of effectors.

    Attributes
    ----------
    name : str
        Identifier; must be unique across the ``GameState``.
    x, y : float
        Cartesian coordinates in kilometres from an arbitrary origin.
    inventory : Mapping[str, int]
        Count of available rounds by effector name. Solvers enforce
        this as a hard capacity in every decision cycle.
    is_capital : bool
        Whether this base is a high-value protected asset.
    reserve_floor : Mapping[str, int]
        Minimum inventory to preserve for future waves per effector
        name. The MILP solver enforces this as a **hard** constraint
        (capacity = max(0, inventory - reserve_floor)). The Hungarian
        solver only penalises it softly.
    """
    name: str
    x: float
    y: float
    inventory: Mapping[str, int]
    is_capital: bool = False
    reserve_floor: Mapping[str, int] = field(default_factory=dict)
    launchers_per_cycle: Mapping[str, int] = field(default_factory=dict)

    def capacity(self, effector_name: str) -> int:
        """Hard per-decision-cycle capacity after reserve-floor withholding.

        Combines three concepts that are separately meaningful:

        1. ``inventory[e]``           — total rounds of effector *e* stockpiled.
        2. ``reserve_floor[e]``       — rounds contractually held back for later.
        3. ``launchers_per_cycle[e]`` — how many rounds of *e* this base can
                                         physically salvo in a single decision
                                         cycle (launchers, fire-control
                                         channels, etc.).

        Per-cycle capacity is the minimum of (a) remaining stockpile after the
        reserve floor, and (b) physical parallel-launch capacity. The default
        ``launchers_per_cycle`` value (when not specified for an effector) is
        **1**, matching the one-shot-per-shooter assumption that the Hungarian
        LAP implicitly encodes. Stage-3 multi-wave extensions can raise this
        without touching Stage-1 parity behaviour.

        Always non-negative.
        """
        inv = self.inventory.get(effector_name, 0)
        res = self.reserve_floor.get(effector_name, 0)
        stockpile = max(0, inv - res)
        lpc = self.launchers_per_cycle.get(effector_name, 1)
        return min(stockpile, max(0, lpc))


# --------------------------------------------------------------------------- #
# Threats                                                                     #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Threat:
    """An inbound hostile track under consideration.

    Attributes
    ----------
    id : str
        Stable track identifier across fusion cycles.
    x, y : float
        Current position in km.
    speed_kmh : float
        Current speed; used for time-to-asset.
    heading_deg : float
        Course over ground in degrees (0 = north, CW positive).
    estimated_type : str
        Classifier label. Must be a key in every relevant effector's
        ``pk_matrix``.
    threat_value : float
        Scalar quantifying the damage potential if the threat reaches
        its target. Enters the utility as ``w_value * Pk * value``.
    class_confidence : float
        Classifier confidence in ``estimated_type``. Multiplies Pk via
        track-quality composition.
    kinematic_consistency : float
        Agreement between observed track kinematics and the claimed
        type's expected envelope.
    sensor_agreement : float
        Cross-sensor agreement (1.0 = all sensors concur).
    age_sec : float
        Seconds since the most recent update to this track.
    """
    id: str
    x: float
    y: float
    speed_kmh: float
    heading_deg: float
    estimated_type: str
    threat_value: float
    class_confidence: float = 0.85
    kinematic_consistency: float = 0.9
    sensor_agreement: float = 1.0
    age_sec: float = 10.0


# --------------------------------------------------------------------------- #
# Commander's intent & ROE                                                    #
# --------------------------------------------------------------------------- #

class ROETier(str, Enum):
    STRICT = "strict"
    STANDARD = "standard"
    PERMISSIVE = "permissive"


@dataclass(frozen=True)
class CommandersIntent:
    """Operational constraints the solver must respect.

    Attributes
    ----------
    roe_tier : ROETier
        Engagement tier. Stage-1 solvers do not branch on this, but
        downstream layers (shield) do.
    min_pk_for_engage : float
        Hard floor on effective Pk. Any assignment with Pk below this
        threshold is infeasible (MILP; Hungarian penalises heavily).
    min_safety_margin_sec : float
        Minimum TTA - TTI. Infeasibility floor.
    max_effectors_per_threat : int
        ``K_t`` in the MILP constraints. Defaults to 1 for parity with
        Hungarian; values >= 2 enable coordinated fire.
    """
    roe_tier: ROETier = ROETier.STANDARD
    min_pk_for_engage: float = 0.55
    min_safety_margin_sec: float = 5.0
    max_effectors_per_threat: int = 1


# --------------------------------------------------------------------------- #
# Scoring weights                                                             #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ScoringWeights:
    """Linear scoring coefficients used by both solvers.

    The defaults here are chosen such that the ``w_value`` term is the
    dominant driver of the utility, with the margin term providing
    small but non-zero tie-breaking in favour of earlier, more
    confident engagements. The cost term is an order of magnitude
    smaller still, consistent with "ammunition cost matters but never
    trumps survival".

    All weights are non-negative. The overall utility formula is
    identical in both solvers:

        u(b,e,t) = w_value * Pk_eff * threat_value
                 + w_margin * 15 * sigmoid(margin_sec / 60)
                 - 0.05 * cost_weight(e)

    Softer terms (doctrine preferences, reserve shortage penalties)
    from the original Hungarian implementation are **deliberately
    omitted** in the Stage-1 reference because the MILP promotes
    reserve floor to a hard constraint. See STRATEGY.md §4.2.
    """
    w_value: float = 1.0
    w_margin: float = 0.2
    cost_coef: float = 0.05
    margin_scale_sec: float = 60.0
    margin_amplitude: float = 15.0


# --------------------------------------------------------------------------- #
# Solver outputs                                                              #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Assignment:
    """A single (base, effector, threat) engagement decision."""
    base_name: str
    effector: str
    threat_id: str
    pk_effective: float
    time_to_intercept_sec: float
    time_to_asset_sec: float
    margin_sec: float
    utility: float


@dataclass(frozen=True)
class TEWAResult:
    """Full solver output.

    Attributes
    ----------
    assignments : List[Assignment]
        The chosen engagements, in deterministic order (sorted by
        ``(base_name, effector, threat_id)``).
    total_utility : float
        Sum of ``assignment.utility`` over chosen assignments.
    solver : str
        Identifier of the solver that produced the result
        (``"hungarian"``, ``"milp_highs"``, or ``"milp_gurobi"``).
    wall_clock_ms : float
        Wall-clock time spent in the solver's ``solve`` method, in
        milliseconds, excluding problem construction.
    feasible_pairs : int
        Number of (base, effector, threat) tuples that survived
        feasibility pruning. Useful for diagnostics.
    """
    assignments: list[Assignment]
    total_utility: float
    solver: str
    wall_clock_ms: float
    feasible_pairs: int


# --------------------------------------------------------------------------- #
# Geometry helpers (deterministic, pure functions)                            #
# --------------------------------------------------------------------------- #

def distance_km(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance in km. Pure, deterministic."""
    dx = ax - bx
    dy = ay - by
    return (dx * dx + dy * dy) ** 0.5


def sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid."""
    if x >= 0:
        z = 2.718281828459045 ** (-x)
        return 1.0 / (1.0 + z)
    z = 2.718281828459045 ** x
    return z / (1.0 + z)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

__all__ = [
    "Assignment",
    "Base",
    "CommandersIntent",
    "Effector",
    "ROETier",
    "ScoringWeights",
    "TEWAResult",
    "Threat",
    "distance_km",
    "sigmoid",
]
