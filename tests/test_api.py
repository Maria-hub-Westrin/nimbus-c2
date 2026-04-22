# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""End-to-end API tests via FastAPI TestClient (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nimbus_c2.api.app import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_scenarios():
    r = client.get("/demo/scenarios")
    assert r.status_code == 200
    scenarios = r.json()["scenarios"]
    assert len(scenarios) == 3
    assert {s["id"] for s in scenarios} == {"clean", "swarm", "jammed"}


def test_get_scenario_roundtrip():
    r = client.get("/demo/scenarios/clean")
    assert r.status_code == 200
    body = r.json()
    assert "bases" in body and "threats" in body and "effectors" in body


def test_clean_scenario_is_autonomous():
    r = client.post("/demo/clean/evaluate")
    assert r.status_code == 200
    j = r.json()
    assert j["assurance"]["autonomy_mode"] == "autonomous"
    assert len(j["coas"]) == 3


def test_swarm_scenario_is_advise():
    r = client.post("/demo/swarm/evaluate")
    assert r.status_code == 200
    assert r.json()["assurance"]["autonomy_mode"] == "advise"


def test_jammed_scenario_is_defer():
    r = client.post("/demo/jammed/evaluate")
    assert r.status_code == 200
    j = r.json()
    assert j["assurance"]["autonomy_mode"] == "defer"
    assert len(j["assurance"]["alerts"]) >= 1


def test_unknown_scenario_404():
    r = client.post("/demo/nonexistent/evaluate")
    assert r.status_code == 404


def test_evaluate_rejects_malformed_input():
    r = client.post("/evaluate", json={"not_a_valid_field": 42})
    assert r.status_code == 422  # pydantic validation error


def test_determinism_across_api_calls():
    """Same demo scenario, three POSTs, byte-identical JSON output."""
    r1 = client.post("/demo/swarm/evaluate").json()
    r2 = client.post("/demo/swarm/evaluate").json()
    r3 = client.post("/demo/swarm/evaluate").json()
    assert r1 == r2 == r3
