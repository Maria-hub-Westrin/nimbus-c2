# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""RunConfig — serialisable experiment specification.

A RunConfig captures every parameter that affects experiment output.
Together with code version (git_sha) it is sufficient to reproduce any
experiment bit-exactly on another machine.

Design principle: the config is the contract. If two runs have identical
configs and identical git_shas, they MUST produce identical results. Any
source of non-determinism not captured in the config is a bug.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class RunConfig:
    """Specification for a single experimental run.

    Attributes
    ----------
    experiment_name : str
        Short slug identifying the experiment type. Used in output filenames.
    seed : int
        Master random seed. All RNG is derived from this.
    alpha_levels : tuple[float, ...]
        Conformal miscoverage levels to test (e.g. (0.10, 0.05)).
    n_calibration : int
        Number of samples in each scenario's calibration set.
    n_test : int
        Number of samples in each scenario's test set.
    n_scenarios : int
        Number of independent seeded scenarios to run.
    class_names : tuple[str, ...]
        Ordered class labels for classification.
    data_source : str
        'synthetic' or path to a data file. Determines how features/labels
        are generated.
    classifier_confidence : float
        For synthetic data only: probability mass the classifier places on
        the true class. Controls how well-calibrated the classifier is.
    """

    experiment_name: str
    seed: int
    alpha_levels: tuple[float, ...]
    n_calibration: int
    n_test: int
    n_scenarios: int
    class_names: tuple[str, ...]
    data_source: str
    classifier_confidence: float = 0.70

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError(f"seed must be non-negative, got {self.seed}")
        if not self.alpha_levels:
            raise ValueError("alpha_levels must not be empty")
        for a in self.alpha_levels:
            if not 0.0 < a < 1.0:
                raise ValueError(f"alpha must be in (0, 1), got {a}")
        if self.n_calibration < 10:
            raise ValueError(
                f"n_calibration must be >= 10 for meaningful statistics, "
                f"got {self.n_calibration}"
            )
        if self.n_test < 10:
            raise ValueError(
                f"n_test must be >= 10 for meaningful statistics, "
                f"got {self.n_test}"
            )
        if self.n_scenarios < 1:
            raise ValueError(f"n_scenarios must be >= 1, got {self.n_scenarios}")
        if not self.class_names:
            raise ValueError("class_names must not be empty")
        if not 0.0 < self.classifier_confidence <= 1.0:
            raise ValueError(
                f"classifier_confidence must be in (0, 1], "
                f"got {self.classifier_confidence}"
            )

    @classmethod
    def from_yaml(cls, path: str | Path) -> RunConfig:
        """Load a RunConfig from a YAML file.

        YAML lists become tuples in the frozen dataclass.
        """
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        # Coerce lists to tuples (frozen dataclass requires hashable types)
        if "alpha_levels" in data and isinstance(data["alpha_levels"], list):
            data["alpha_levels"] = tuple(data["alpha_levels"])
        if "class_names" in data and isinstance(data["class_names"], list):
            data["class_names"] = tuple(data["class_names"])

        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict. Tuples become lists."""
        d = asdict(self)
        # JSON does not distinguish tuple from list; use list for round-trip
        d["alpha_levels"] = list(self.alpha_levels)
        d["class_names"] = list(self.class_names)
        return d
