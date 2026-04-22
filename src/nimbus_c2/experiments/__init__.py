# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Experiment runner for reproducible validation of Nimbus-C2 components.

This module provides a minimal but rigorous experiment framework:

- :class:`RunConfig` — YAML-loadable experiment specification with all
  parameters needed to reproduce a single run bit-exactly.
- :class:`ExperimentResult` — JSON-serialisable result artefact containing
  the full config plus numerical outputs and provenance metadata.
- :func:`run_conformal_validation` — the canonical Stage 2b coverage-guarantee
  validation, implemented as a pure function of a RunConfig.

The design deliberately avoids plugin systems, registry patterns, or other
extensibility machinery. Every experiment is a single function that takes
a config and returns a result. This keeps the provenance chain visible to
reviewers: config -> function -> result, nothing hidden.
"""
from __future__ import annotations

from .config import RunConfig
from .provenance import git_sha_with_status, python_version
from .result import ExperimentResult
from .runner import run_conformal_validation

__all__ = [
    "ExperimentResult",
    "RunConfig",
    "git_sha_with_status",
    "python_version",
    "run_conformal_validation",
]
