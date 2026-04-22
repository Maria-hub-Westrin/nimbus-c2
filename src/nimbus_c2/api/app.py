# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""FastAPI gateway for the Nimbus-C2 engine.

Three endpoints:

    GET  /health                    — liveness check
    GET  /demo/scenarios            — list canned demo scenarios
    POST /evaluate                  — run the full pipeline

The API layer transcodes JSON → dataclasses → JSON. It performs no
decision logic; that is entirely owned by ``nimbus_c2.pipeline.evaluate``.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .. import (
    Base,
    CommandersIntent,
    Effector,
    EvaluationResult,
    ROETier,
    Threat,
    evaluate,
)
from .demo_data import DEMO_SCENARIOS

# --------------------------------------------------------------------------- #
# Pydantic request/response schemas                                           #
# --------------------------------------------------------------------------- #

class EffectorIn(BaseModel):
    name: str
    speed_kmh: float = 1000.0
    cost_weight: float = 10.0
    pk_matrix: dict[str, float]
    range_km: float = 400.0
    min_engage_km: float = 0.0
    response_time_sec: float = 15.0


class BaseIn(BaseModel):
    name: str
    x: float
    y: float
    inventory: dict[str, int]
    is_capital: bool = False
    reserve_floor: dict[str, int] = Field(default_factory=dict)
    launchers_per_cycle: dict[str, int] = Field(default_factory=dict)


class ThreatIn(BaseModel):
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


class IntentIn(BaseModel):
    roe_tier: str = "standard"
    min_pk_for_engage: float = 0.55
    min_safety_margin_sec: float = 5.0
    max_effectors_per_threat: int = 1


class EvaluateRequest(BaseModel):
    bases: list[BaseIn]
    effectors: dict[str, EffectorIn]
    threats: list[ThreatIn]
    intent: IntentIn = Field(default_factory=IntentIn)
    blind_spots: list[tuple[float, float]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Converters                                                                  #
# --------------------------------------------------------------------------- #

def _to_effector(m: EffectorIn) -> Effector:
    return Effector(
        name=m.name, speed_kmh=m.speed_kmh, cost_weight=m.cost_weight,
        pk_matrix=m.pk_matrix, range_km=m.range_km,
        min_engage_km=m.min_engage_km, response_time_sec=m.response_time_sec,
    )


def _to_base(m: BaseIn) -> Base:
    return Base(
        name=m.name, x=m.x, y=m.y,
        inventory=m.inventory, is_capital=m.is_capital,
        reserve_floor=m.reserve_floor,
        launchers_per_cycle=m.launchers_per_cycle,
    )


def _to_threat(m: ThreatIn) -> Threat:
    return Threat(
        id=m.id, x=m.x, y=m.y, speed_kmh=m.speed_kmh,
        heading_deg=m.heading_deg, estimated_type=m.estimated_type,
        threat_value=m.threat_value,
        class_confidence=m.class_confidence,
        kinematic_consistency=m.kinematic_consistency,
        sensor_agreement=m.sensor_agreement,
        age_sec=m.age_sec,
    )


def _to_intent(m: IntentIn) -> CommandersIntent:
    try:
        tier = ROETier(m.roe_tier)
    except ValueError:
        tier = ROETier.STANDARD
    return CommandersIntent(
        roe_tier=tier,
        min_pk_for_engage=m.min_pk_for_engage,
        min_safety_margin_sec=m.min_safety_margin_sec,
        max_effectors_per_threat=m.max_effectors_per_threat,
    )


def _evaluate_from_request(req: EvaluateRequest) -> EvaluationResult:
    bases = [_to_base(b) for b in req.bases]
    effectors = {k: _to_effector(v) for k, v in req.effectors.items()}
    threats = [_to_threat(t) for t in req.threats]
    intent = _to_intent(req.intent)
    return evaluate(
        bases=bases, effectors=effectors, threats=threats,
        intent=intent, blind_spots=req.blind_spots,
    )


# --------------------------------------------------------------------------- #
# App                                                                         #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Nimbus-C2",
    description=(
        "Reliability-aware command-and-control decision engine. "
        "Deterministic MILP TEWA core + assurance layer + wave forecaster + "
        "COA generator + offline SITREP."
    ),
    version="1.0.0",
)

# Permissive CORS for the single-file demo UI. Tighten in production deployments.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe."""
    return {"status": "ok", "version": app.version}


@app.get("/demo/scenarios")
def list_scenarios() -> dict[str, Any]:
    """List canned demo scenarios."""
    return {
        "scenarios": [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in DEMO_SCENARIOS.values()
        ]
    }


@app.get("/demo/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> dict[str, Any]:
    """Retrieve a canned demo scenario's full tactical state."""
    s = DEMO_SCENARIOS.get(scenario_id)
    if s is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown scenario {scenario_id!r}; see /demo/scenarios",
        )
    return s.to_request()


@app.post("/evaluate")
def evaluate_endpoint(req: EvaluateRequest) -> dict[str, Any]:
    """Run the full Nimbus-C2 pipeline."""
    try:
        result = _evaluate_from_request(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result.as_dict()


@app.post("/demo/{scenario_id}/evaluate")
def evaluate_demo(scenario_id: str) -> dict[str, Any]:
    """Convenience endpoint: run the pipeline against a named demo scenario."""
    s = DEMO_SCENARIOS.get(scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail="unknown scenario")
    req = EvaluateRequest(**s.to_request())
    return _evaluate_from_request(req).as_dict()
