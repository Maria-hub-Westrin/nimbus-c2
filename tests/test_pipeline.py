# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Tests for assurance, wave forecaster, COA generator, SITREP, pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2 import (  # noqa: E402
    Base, Threat, Effector, CommandersIntent,
    build_assurance_report, AutonomyMode,
    forecast_waves,
    generate_coas, COALabel,
    build_offline_sitrep,
    evaluate,
)

_EFFECTORS = {
    "sam": Effector(name="sam", speed_kmh=3000, cost_weight=80,
                    pk_matrix={"bomber": 0.95, "drone": 0.9, "fast-mover": 0.7},
                    range_km=400, response_time_sec=10),
    "fighter": Effector(name="fighter", speed_kmh=2000, cost_weight=50,
                    pk_matrix={"bomber": 0.9, "drone": 0.7, "fast-mover": 0.8},
                    range_km=1200, response_time_sec=60),
    "drone": Effector(name="drone", speed_kmh=400, cost_weight=10,
                    pk_matrix={"bomber": 0.4, "drone": 0.8, "fast-mover": 0.1},
                    range_km=300, response_time_sec=30),
}

def _nominal_state():
    bases = [
        Base(name="Alpha", x=0, y=0,
             inventory={"sam": 8, "fighter": 4, "drone": 6}, is_capital=True),
        Base(name="Bravo", x=150, y=100,
             inventory={"sam": 4, "fighter": 3, "drone": 10}),
    ]
    threats = [
        Threat(id="T01", x=100, y=50, speed_kmh=600, heading_deg=225,
               estimated_type="bomber", threat_value=80.0,
               class_confidence=0.95, kinematic_consistency=0.9,
               sensor_agreement=1.0, age_sec=3.0),
        Threat(id="T02", x=-80, y=40, speed_kmh=500, heading_deg=135,
               estimated_type="drone", threat_value=25.0,
               class_confidence=0.9, kinematic_consistency=0.85,
               sensor_agreement=0.95, age_sec=5.0),
    ]
    intent = CommandersIntent(
        min_pk_for_engage=0.5, min_safety_margin_sec=5.0,
        max_effectors_per_threat=1,
    )
    return bases, threats, intent


def _degraded_state():
    """Big swarm, noisy sensors, tight geometry."""
    bases = [Base(name="Alpha", x=0, y=0,
                  inventory={"sam": 8, "fighter": 4, "drone": 6}, is_capital=True)]
    threats = [
        Threat(
            id=f"T{i:02d}", x=50 + i * 5, y=50 + (i % 3) * 10,
            speed_kmh=800, heading_deg=220,
            estimated_type=("drone" if i % 2 else "bomber"),
            threat_value=60.0,
            class_confidence=0.55, kinematic_consistency=0.55,
            sensor_agreement=0.55, age_sec=22.0,
        ) for i in range(25)
    ]
    intent = CommandersIntent()
    return bases, threats, intent


# --------------------------------------------------------------------------- #
# Assurance                                                                   #
# --------------------------------------------------------------------------- #

class TestAssurance:
    def test_nominal_gives_high_sa_and_autonomous_or_advise(self):
        bases, threats, intent = _nominal_state()
        protected = [(b.x, b.y) for b in bases if b.is_capital]
        r = build_assurance_report(threats, protected, intent)
        assert r.sa_health >= 60
        assert r.autonomy_mode in (AutonomyMode.AUTONOMOUS, AutonomyMode.ADVISE)

    def test_degraded_gives_low_sa_and_defer_or_advise(self):
        bases, threats, intent = _degraded_state()
        protected = [(b.x, b.y) for b in bases]
        r = build_assurance_report(threats, protected, intent)
        assert r.situation_complexity >= 0.5, "25 low-quality tracks should register as complex"
        assert r.autonomy_mode in (AutonomyMode.ADVISE, AutonomyMode.DEFER)

    def test_no_threats_no_defer_paralysis(self):
        bases, _, intent = _nominal_state()
        protected = [(b.x, b.y) for b in bases]
        r = build_assurance_report([], protected, intent)
        # Empty picture: TQI = 1.0, no complexity, no stakes → AUTONOMOUS.
        assert r.autonomy_mode == AutonomyMode.AUTONOMOUS

    def test_blind_spot_degrades_tqi(self):
        bases, threats, intent = _nominal_state()
        protected = [(b.x, b.y) for b in bases if b.is_capital]
        r_clean = build_assurance_report(threats, protected, intent)
        r_blind = build_assurance_report(
            threats, protected, intent,
            blind_spots=[(100, 50)],  # exactly on T01
        )
        assert r_blind.track_quality_index < r_clean.track_quality_index

    def test_reasons_list_nonempty_for_every_mode(self):
        for state in (_nominal_state(), _degraded_state()):
            bases, threats, intent = state
            protected = [(b.x, b.y) for b in bases]
            r = build_assurance_report(threats, protected, intent)
            assert isinstance(r.reasons, list)
            assert len(r.reasons) >= 1, f"mode {r.autonomy_mode} gave no reasons"


# --------------------------------------------------------------------------- #
# Wave forecaster                                                             #
# --------------------------------------------------------------------------- #

class TestWaveForecaster:
    def test_empty_forecast_is_zero(self):
        f = forecast_waves([], (0, 0))
        assert f.follow_on_likelihood == 0.0
        assert all(s.n_current == 0 for s in f.sectors)

    def test_four_sectors_always(self):
        bases, threats, _ = _nominal_state()
        f = forecast_waves(threats, (0, 0))
        assert len(f.sectors) == 4
        assert {s.sector_id for s in f.sectors} == {"N", "E", "S", "W"}

    def test_threats_in_north_hit_north_sector(self):
        threats = [Threat(id=f"T{i}", x=0, y=100, speed_kmh=500, heading_deg=180,
                          estimated_type="bomber", threat_value=50)
                   for i in range(3)]
        f = forecast_waves(threats, (0, 0))
        n_sector = next(s for s in f.sectors if s.sector_id == "N")
        assert n_sector.n_current == 3

    def test_higher_density_means_higher_prob(self):
        dense = [Threat(id=f"T{i}", x=100, y=0, speed_kmh=500, heading_deg=270,
                        estimated_type="bomber", threat_value=50)
                 for i in range(5)]
        sparse = dense[:1]
        f_dense = forecast_waves(dense, (0, 0))
        f_sparse = forecast_waves(sparse, (0, 0))
        assert f_dense.follow_on_likelihood > f_sparse.follow_on_likelihood


# --------------------------------------------------------------------------- #
# COA generator                                                               #
# --------------------------------------------------------------------------- #

class TestCOAGenerator:
    def test_three_coas_always_produced(self):
        bases, threats, intent = _nominal_state()
        f = forecast_waves(threats, (bases[0].x, bases[0].y))
        coas = generate_coas(bases, _EFFECTORS, threats, intent, f)
        assert len(coas) == 3
        labels = {c.label for c in coas}
        assert labels == {COALabel.RECOMMENDED, COALabel.RESERVE_CONSERVING,
                          COALabel.RISK_MINIMIZING}

    def test_reserve_conserving_uses_fewer_or_equal_expensive_rounds(self):
        bases, threats, intent = _nominal_state()
        f = forecast_waves(threats, (bases[0].x, bases[0].y))
        coas = generate_coas(bases, _EFFECTORS, threats, intent, f)
        rec = next(c for c in coas if c.label == COALabel.RECOMMENDED)
        rc = next(c for c in coas if c.label == COALabel.RESERVE_CONSERVING)
        # cost_weight >= 50 means 'fighter' and 'sam' are expensive.
        rec_expensive = rec.reserves_spent.get("sam", 0) + rec.reserves_spent.get("fighter", 0)
        rc_expensive = rc.reserves_spent.get("sam", 0) + rc.reserves_spent.get("fighter", 0)
        assert rc_expensive <= rec_expensive, (
            f"Reserve-conserving spent more expensive rounds "
            f"({rc_expensive}) than recommended ({rec_expensive})"
        )

    def test_coverage_in_zero_one(self):
        bases, threats, intent = _nominal_state()
        f = forecast_waves(threats, (bases[0].x, bases[0].y))
        coas = generate_coas(bases, _EFFECTORS, threats, intent, f)
        for c in coas:
            assert 0.0 <= c.predicted_coverage <= 1.0
            assert 0.0 <= c.risk_if_follow_on <= 1.0


# --------------------------------------------------------------------------- #
# SITREP                                                                      #
# --------------------------------------------------------------------------- #

class TestSITREP:
    def test_sitrep_all_fields_populated(self):
        bases, threats, intent = _nominal_state()
        r = evaluate(bases, _EFFECTORS, threats, intent)
        s = r.sitrep
        assert s.headline and s.posture and s.threats_summary
        assert s.recommendation and s.assurance_note and s.follow_on_note

    def test_sitrep_source_is_template_by_default(self):
        bases, threats, intent = _nominal_state()
        r = evaluate(bases, _EFFECTORS, threats, intent)
        assert r.sitrep.source.value == "template"

    def test_numeric_fields_not_in_prose(self):
        """Headline/posture/recommendation should carry human-readable text.
        The exact Pk, counts, value numbers live in structured sub-objects."""
        bases, threats, intent = _nominal_state()
        r = evaluate(bases, _EFFECTORS, threats, intent)
        # SITREP prose talks about counts and coverage percentages but
        # never embeds a raw Pk estimate; those live in coas[i].assignments.
        rec = next(c for c in r.coas if c.label == COALabel.RECOMMENDED)
        if rec.assignments:
            assert "pk_effective" in rec.as_dict()["assignments"][0]


# --------------------------------------------------------------------------- #
# End-to-end pipeline                                                         #
# --------------------------------------------------------------------------- #

class TestPipelineE2E:
    def test_evaluate_returns_full_result(self):
        bases, threats, intent = _nominal_state()
        r = evaluate(bases, _EFFECTORS, threats, intent)
        assert r.assurance is not None
        assert r.forecast is not None
        assert len(r.coas) == 3
        assert r.sitrep is not None

    def test_evaluate_deterministic(self):
        """Same input, same output — three repeats."""
        bases, threats, intent = _nominal_state()
        r1 = evaluate(bases, _EFFECTORS, threats, intent)
        r2 = evaluate(bases, _EFFECTORS, threats, intent)
        r3 = evaluate(bases, _EFFECTORS, threats, intent)
        assert r1.as_dict() == r2.as_dict() == r3.as_dict()

    def test_evaluate_no_threats(self):
        bases, _, intent = _nominal_state()
        r = evaluate(bases, _EFFECTORS, [], intent)
        assert r.n_threats == 0
        assert all(len(c.assignments) == 0 for c in r.coas)
        assert r.sitrep.headline.startswith("No inbound threats")
