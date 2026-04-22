# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""ExperimentResult — the serialisable output of a single experiment run.

Contains the original RunConfig plus all numerical outputs and provenance
metadata. Written to disk as JSON. Can be loaded back for post-hoc analysis,
cross-run comparison, or evidence in a peer review package.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import RunConfig


@dataclass(frozen=True)
class CoverageResult:
    """Coverage statistics at a single alpha level."""

    alpha: float
    target_coverage: float  # 1 - alpha
    mean_coverage: float
    min_coverage: float
    max_coverage: float
    mean_set_size: float
    q_hat_median: float
    passes_guarantee: bool  # mean_coverage >= target - tolerance


@dataclass(frozen=True)
class ExperimentResult:
    """Full artefact of one experiment run.

    Attributes
    ----------
    config : RunConfig
        Exact parameters used.
    git_sha : str
        Commit SHA at run time, or 'unknown' if git unavailable.
    git_branch : str
        Branch name at run time.
    git_is_dirty : bool
        True iff working tree had uncommitted edits.
    python_version : str
        Python version used, e.g. 'Python 3.12.10'.
    timestamp_utc : str
        ISO 8601 UTC timestamp of run completion.
    runtime_seconds : float
        Wall-clock time from experiment start to end.
    coverage_per_alpha : list[CoverageResult]
        Coverage stats for each alpha level in config.alpha_levels.
    coverage_tolerance : float
        Tolerance used for passes_guarantee assertion.
    warnings : list[str]
        Any warnings emitted during the run.
    """

    config: RunConfig
    git_sha: str
    git_branch: str
    git_is_dirty: bool
    python_version: str
    timestamp_utc: str
    runtime_seconds: float
    coverage_per_alpha: list[CoverageResult]
    coverage_tolerance: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Flatten to a JSON-serialisable dict."""
        d: dict[str, Any] = {
            "config": self.config.to_dict(),
            "git_sha": self.git_sha,
            "git_branch": self.git_branch,
            "git_is_dirty": self.git_is_dirty,
            "python_version": self.python_version,
            "timestamp_utc": self.timestamp_utc,
            "runtime_seconds": self.runtime_seconds,
            "coverage_per_alpha": [asdict(cr) for cr in self.coverage_per_alpha],
            "coverage_tolerance": self.coverage_tolerance,
            "warnings": list(self.warnings),
        }
        return d

    def to_json(self) -> str:
        """Serialise to a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def save(self, output_dir: str | Path) -> Path:
        """Write this result to disk.

        Filename pattern: ``{experiment_name}_{timestamp}_{short_sha}.json``
        where timestamp is YYYYMMDDTHHMMSSZ (UTC, no colons, safe for Windows
        filenames).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Convert ISO timestamp to filename-safe form
        ts = (
            self.timestamp_utc.replace(":", "").replace("-", "").split(".")[0]
            + "Z"
        )
        short_sha = self.git_sha[:7] if self.git_sha != "unknown" else "nosha"
        fname = f"{self.config.experiment_name}_{ts}_{short_sha}.json"

        path = output_dir / fname
        path.write_text(self.to_json(), encoding="utf-8")
        return path
