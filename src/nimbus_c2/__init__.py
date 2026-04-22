# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Nimbus-C2 — reliability-aware command-and-control decision engine.

See STRATEGY.md for the stage-gated plan that governs this package.
"""
from .assurance import (
    AssuranceReport,
    AutonomyMode,
    build_assurance_report,
)
from .coa_generator import COA, COALabel, generate_coas
from .hungarian_tewa import solve_hungarian
from .milp_tewa import solve_milp
from .models import (
    Assignment,
    Base,
    CommandersIntent,
    Effector,
    ROETier,
    ScoringWeights,
    TEWAResult,
    Threat,
)
from .opensky_adapter import (
    BBOX_BALTIC,
    BBOX_GOTLAND_NARROW,
    OpenSkyAdapter,
    StateSnapshot,
    StateVector,
    TokenManager,
)
from .pipeline import EvaluationResult, evaluate
from .sitrep import SITREP, build_offline_sitrep
from .wave_forecaster import SectorForecast, WaveForecast, forecast_waves

__all__ = [
    "Assignment", "Base", "CommandersIntent", "Effector", "ROETier",
    "ScoringWeights", "TEWAResult", "Threat",
    "solve_hungarian", "solve_milp",
    "AssuranceReport", "AutonomyMode", "build_assurance_report",
    "SectorForecast", "WaveForecast", "forecast_waves",
    "COA", "COALabel", "generate_coas",
    "SITREP", "build_offline_sitrep",
    "EvaluationResult", "evaluate",
    # Stage 2a — OpenSky data ingestion.
    "BBOX_BALTIC", "BBOX_GOTLAND_NARROW",
    "OpenSkyAdapter", "StateSnapshot", "StateVector", "TokenManager",
]

__version__ = "1.0.0"
