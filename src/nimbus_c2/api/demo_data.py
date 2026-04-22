# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Canned demo scenarios for the Nimbus-C2 UI.

Three scenarios that exercise the three autonomy modes:

    clean    : high-SA, low-complexity, moderate-stakes → AUTONOMOUS
    swarm    : medium-SA, high-complexity, high-stakes → ADVISE
    jammed   : low-SA, blind-spots, high-stakes → DEFER

These are what the Saab pitch demo clicks through to show the system's
competence-awareness behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class DemoScenario:
    id: str
    name: str
    description: str
    request: Dict[str, Any]  # ready-to-POST EvaluateRequest payload

    def to_request(self) -> Dict[str, Any]:
        return self.request


# --------------------------------------------------------------------------- #
# Common pieces                                                               #
# --------------------------------------------------------------------------- #

_EFFECTORS = {
    "sam": {
        "name": "sam",
        "speed_kmh": 3000,
        "cost_weight": 80,
        "pk_matrix": {"bomber": 0.95, "drone": 0.9, "fast-mover": 0.7,
                      "hypersonic": 0.5, "ghost": 0.8},
        "range_km": 400,
        "min_engage_km": 5,
        "response_time_sec": 10,
    },
    "fighter": {
        "name": "fighter",
        "speed_kmh": 2000,
        "cost_weight": 50,
        "pk_matrix": {"bomber": 0.9, "drone": 0.7, "fast-mover": 0.8,
                      "hypersonic": 0.3, "ghost": 0.6},
        "range_km": 1200,
        "min_engage_km": 20,
        "response_time_sec": 60,
    },
    "drone": {
        "name": "drone",
        "speed_kmh": 400,
        "cost_weight": 10,
        "pk_matrix": {"bomber": 0.4, "drone": 0.8, "fast-mover": 0.1,
                      "hypersonic": 0.05, "ghost": 0.3},
        "range_km": 300,
        "min_engage_km": 0,
        "response_time_sec": 30,
    },
}

_BASES_DEFAULT = [
    {"name": "Arktholm", "x": 0, "y": 0,
     "inventory": {"sam": 12, "fighter": 4, "drone": 8},
     "is_capital": True,
     "reserve_floor": {"sam": 4},
     "launchers_per_cycle": {"sam": 2, "fighter": 1, "drone": 1}},
    {"name": "Boden", "x": 150, "y": 100,
     "inventory": {"sam": 6, "fighter": 3, "drone": 10},
     "launchers_per_cycle": {"sam": 1, "fighter": 1, "drone": 2}},
    {"name": "Gotland", "x": -120, "y": 80,
     "inventory": {"sam": 4, "fighter": 2, "drone": 6},
     "launchers_per_cycle": {"sam": 1, "fighter": 1, "drone": 1}},
]

_INTENT_DEFAULT = {
    "roe_tier": "standard",
    "min_pk_for_engage": 0.55,
    "min_safety_margin_sec": 5.0,
    "max_effectors_per_threat": 1,
}


# --------------------------------------------------------------------------- #
# Scenario 1: CLEAN — three bombers, high-quality tracks                      #
# --------------------------------------------------------------------------- #

_CLEAN_THREATS = [
    {"id": "T01", "x": 120, "y": 70, "speed_kmh": 700, "heading_deg": 210,
     "estimated_type": "bomber", "threat_value": 85.0,
     "class_confidence": 0.95, "kinematic_consistency": 0.92,
     "sensor_agreement": 1.0, "age_sec": 3.0},
    {"id": "T02", "x": -80, "y": 60, "speed_kmh": 650, "heading_deg": 140,
     "estimated_type": "bomber", "threat_value": 80.0,
     "class_confidence": 0.93, "kinematic_consistency": 0.90,
     "sensor_agreement": 0.98, "age_sec": 4.5},
    {"id": "T03", "x": 60, "y": 180, "speed_kmh": 600, "heading_deg": 195,
     "estimated_type": "bomber", "threat_value": 82.0,
     "class_confidence": 0.94, "kinematic_consistency": 0.91,
     "sensor_agreement": 1.0, "age_sec": 3.2},
]

SCENARIO_CLEAN = DemoScenario(
    id="clean",
    name="Clean picture — three bombers",
    description=(
        "High track quality, no sensor contention, moderate threat value. "
        "Demonstrates the AUTONOMOUS mode and the system's default MILP "
        "assignment logic."
    ),
    request={
        "bases": _BASES_DEFAULT,
        "effectors": _EFFECTORS,
        "threats": _CLEAN_THREATS,
        "intent": _INTENT_DEFAULT,
        "blind_spots": [],
    },
)


# --------------------------------------------------------------------------- #
# Scenario 2: SWARM — mixed types, many tracks, noisier sensors               #
# --------------------------------------------------------------------------- #

def _swarm_threats() -> List[Dict[str, Any]]:
    threats: List[Dict[str, Any]] = []
    # 12 drones fanning in from N-W
    for i in range(12):
        threats.append({
            "id": f"D{i:02d}",
            "x": -60 + (i % 4) * 20,
            "y": 80 + (i // 4) * 20,
            "speed_kmh": 400,
            "heading_deg": 150,
            "estimated_type": "drone",
            "threat_value": 15.0,
            "class_confidence": 0.75,
            "kinematic_consistency": 0.8,
            "sensor_agreement": 0.9,
            "age_sec": 8.0,
        })
    # 2 fast-movers from east
    threats.extend([
        {"id": "F01", "x": 200, "y": 40, "speed_kmh": 1500, "heading_deg": 260,
         "estimated_type": "fast-mover", "threat_value": 95.0,
         "class_confidence": 0.88, "kinematic_consistency": 0.9,
         "sensor_agreement": 0.95, "age_sec": 4.0},
        {"id": "F02", "x": 210, "y": 80, "speed_kmh": 1400, "heading_deg": 258,
         "estimated_type": "fast-mover", "threat_value": 92.0,
         "class_confidence": 0.85, "kinematic_consistency": 0.88,
         "sensor_agreement": 0.93, "age_sec": 5.0},
    ])
    # 1 ghost — ambiguous classification
    threats.append({
        "id": "G01", "x": 30, "y": 220, "speed_kmh": 900, "heading_deg": 200,
        "estimated_type": "ghost", "threat_value": 70.0,
        "class_confidence": 0.55, "kinematic_consistency": 0.6,
        "sensor_agreement": 0.7, "age_sec": 15.0,
    })
    return threats


SCENARIO_SWARM = DemoScenario(
    id="swarm",
    name="Swarm with fast-mover breakthrough",
    description=(
        "15 tracks: 12 drones, 2 fast-movers, 1 ghost with ambiguous "
        "classification. Exercises the ADVISE mode via elevated "
        "complexity and mixed track quality."
    ),
    request={
        "bases": _BASES_DEFAULT,
        "effectors": _EFFECTORS,
        "threats": _swarm_threats(),
        "intent": _INTENT_DEFAULT,
        "blind_spots": [],
    },
)


# --------------------------------------------------------------------------- #
# Scenario 3: JAMMED — high stakes, blind spots, low sensor agreement         #
# --------------------------------------------------------------------------- #

_JAMMED_THREATS = [
    {"id": "H01", "x": 80, "y": 50, "speed_kmh": 4000, "heading_deg": 225,
     "estimated_type": "hypersonic", "threat_value": 200.0,
     "class_confidence": 0.45, "kinematic_consistency": 0.5,
     "sensor_agreement": 0.45, "age_sec": 18.0},
    {"id": "G02", "x": -40, "y": 90, "speed_kmh": 700, "heading_deg": 135,
     "estimated_type": "ghost", "threat_value": 95.0,
     "class_confidence": 0.4, "kinematic_consistency": 0.55,
     "sensor_agreement": 0.4, "age_sec": 25.0},
    {"id": "G03", "x": 100, "y": 120, "speed_kmh": 800, "heading_deg": 210,
     "estimated_type": "ghost", "threat_value": 90.0,
     "class_confidence": 0.45, "kinematic_consistency": 0.5,
     "sensor_agreement": 0.45, "age_sec": 22.0},
    {"id": "F03", "x": 150, "y": 30, "speed_kmh": 1600, "heading_deg": 245,
     "estimated_type": "fast-mover", "threat_value": 100.0,
     "class_confidence": 0.6, "kinematic_consistency": 0.7,
     "sensor_agreement": 0.55, "age_sec": 12.0},
]


SCENARIO_JAMMED = DemoScenario(
    id="jammed",
    name="Jammed sensors + high-value threats",
    description=(
        "Inbound hypersonic and multiple ghosts, low sensor agreement, "
        "blind spot over the primary track. Demonstrates DEFER mode: "
        "system withdraws rather than act on degraded picture."
    ),
    request={
        "bases": _BASES_DEFAULT,
        "effectors": _EFFECTORS,
        "threats": _JAMMED_THREATS,
        "intent": _INTENT_DEFAULT,
        "blind_spots": [[80, 50]],
    },
)


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #

DEMO_SCENARIOS: Dict[str, DemoScenario] = {
    s.id: s for s in (SCENARIO_CLEAN, SCENARIO_SWARM, SCENARIO_JAMMED)
}


__all__ = [
    "DEMO_SCENARIOS",
    "DemoScenario",
    "SCENARIO_CLEAN",
    "SCENARIO_SWARM",
    "SCENARIO_JAMMED",
]
