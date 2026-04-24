# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Geographically-grounded scenario packs for Nimbus-C2.

The ``scenarios`` subpackage contains adapters that load external
tactical canvases (e.g. the Boreal Passage hackathon pack) into the
engine's existing ``Base`` / ``Threat`` / ``CommandersIntent``
dataclasses.

**Design contract:** scenario packs are pure adapters. They do not
modify the solver, assurance layer, COA generator, or SITREP. The
engine is unchanged; only the *input* varies. Pipeline determinism is
therefore preserved: the same pack produces the same
``EvaluationResult`` byte-for-byte.
"""
from __future__ import annotations

from .boreal_passage import (
    BOREAL_SCENARIOS,
    BorealGeography,
    build_boreal_scenario,
    load_boreal_geography,
)

__all__ = [
    "BOREAL_SCENARIOS",
    "BorealGeography",
    "build_boreal_scenario",
    "load_boreal_geography",
]
