# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Baseline aircraft classifier for Nimbus-C2 Stage 2b.

Classifies ADS-B tracks into {civilian, military, unknown} using a
multinomial logistic regression on kinematic features. The classifier is
deliberately simple — transparent, fast, and easy to explain to reviewers.
Conformal prediction (see :mod:`nimbus_c2.conformal`) wraps this classifier
to produce uncertainty-quantified prediction sets.

Design rationale
----------------
- **Logistic regression, not a neural net.** For a Saab-style certifiable
  system, every prediction must be explainable in terms of human-understandable
  features. Logistic regression gives us interpretable coefficients.
- **Feature set is deliberately sparse.** We use only features that are
  robust against ADS-B spoofing and missing data. Notably excluded: callsign
  prefixes and airline ICAO codes, which can be trivially forged.
- **No training on-device.** The classifier is fit once offline on labelled
  calibration data, then deployed frozen. Retraining requires human review.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

# Canonical class ordering. MUST match the order used everywhere.
CLASS_NAMES: tuple[str, ...] = ("civilian", "military", "unknown")

# Canonical feature ordering. MUST match the order used everywhere.
FEATURE_NAMES: tuple[str, ...] = (
    "velocity_ms",       # ground speed
    "baro_altitude_m",   # barometric altitude
    "geo_altitude_m",    # geometric (GNSS) altitude
    "vertical_rate_ms",  # climb rate
    "on_ground_flag",    # 0.0 or 1.0
    "squawk_military",   # 0.0 or 1.0 — squawk in reserved military range
)


@dataclass(frozen=True)
class TrackFeatures:
    """Feature vector for one ADS-B track.

    All fields are numeric to satisfy sklearn's fit/predict interface.
    None values in source data must be imputed before constructing this.
    """

    velocity_ms: float
    baro_altitude_m: float
    geo_altitude_m: float
    vertical_rate_ms: float
    on_ground_flag: float
    squawk_military: float

    def to_array(self) -> NDArray[np.float64]:
        return np.array(
            [
                self.velocity_ms,
                self.baro_altitude_m,
                self.geo_altitude_m,
                self.vertical_rate_ms,
                self.on_ground_flag,
                self.squawk_military,
            ],
            dtype=np.float64,
        )


def features_to_matrix(features: Sequence[TrackFeatures]) -> NDArray[np.float64]:
    """Stack TrackFeatures into an (n_samples, n_features) array."""
    if not features:
        return np.zeros((0, len(FEATURE_NAMES)), dtype=np.float64)
    return np.stack([f.to_array() for f in features], axis=0)


class BaselineClassifier:
    """Multinomial logistic regression over kinematic features.

    Wraps sklearn's LogisticRegression with a fixed random seed for
    reproducibility. Produces softmax probabilities suitable for conformal
    wrapping.

    The model is trained with `multi_class="multinomial"` and L2 regularisation
    to avoid overfitting on small calibration sets.
    """

    RANDOM_STATE = 42
    C = 1.0  # Inverse regularisation strength; smaller = stronger regularisation

    def __init__(self) -> None:
        self._model: LogisticRegression | None = None

    def fit(
        self,
        X: NDArray[np.float64],
        y: NDArray[np.int64],
    ) -> BaselineClassifier:
        """Train the classifier on labelled data.

        Parameters
        ----------
        X : (n_samples, n_features) array
        y : (n_samples,) array of class indices in [0, len(CLASS_NAMES))

        Returns
        -------
        self, for method chaining.
        """
        if X.shape[1] != len(FEATURE_NAMES):
            raise ValueError(
                f"X must have {len(FEATURE_NAMES)} columns (FEATURE_NAMES); "
                f"got {X.shape[1]}"
            )
        if X.shape[0] != y.shape[0]:
            raise ValueError(
                f"X and y row count mismatch: {X.shape[0]} vs {y.shape[0]}"
            )

        self._model = LogisticRegression(
            multi_class="multinomial",
            solver="lbfgs",
            max_iter=1000,
            C=self.C,
            random_state=self.RANDOM_STATE,
        )
        self._model.fit(X, y)
        return self

    def predict_proba(self, X: NDArray[np.float64]) -> NDArray[np.float64]:
        """Produce (n_samples, n_classes) softmax probability matrix.

        Output columns are ordered to match CLASS_NAMES. If the training set
        did not contain all classes, missing columns are zero-padded so that
        the output always has shape (n_samples, len(CLASS_NAMES)).
        """
        if self._model is None:
            raise RuntimeError("Classifier must be fit() before predict_proba()")

        raw_proba: NDArray[np.float64] = self._model.predict_proba(X)
        model_classes: NDArray[np.int64] = self._model.classes_

        # Align output columns to canonical CLASS_NAMES order
        n_samples = X.shape[0]
        n_canonical = len(CLASS_NAMES)
        output = np.zeros((n_samples, n_canonical), dtype=np.float64)
        for col_out, class_idx in enumerate(range(n_canonical)):
            # Find which column of raw_proba corresponds to this canonical class
            matches = np.where(model_classes == class_idx)[0]
            if len(matches) == 1:
                output[:, col_out] = raw_proba[:, matches[0]]
        return output
