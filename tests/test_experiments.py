# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Tests for the experiment reproducibility framework.

The key invariants under test:
- RunConfig round-trip (YAML -> dataclass -> dict -> dataclass) preserves values
- Config validation rejects malformed specs
- Running the same config twice produces identical numerical outputs
- ExperimentResult serialises to JSON and parses back cleanly
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.experiments import RunConfig, run_conformal_validation  # noqa: E402
from nimbus_c2.experiments.result import ExperimentResult  # noqa: E402


def _minimal_config(**overrides: object) -> RunConfig:
    """Build a small valid config for fast tests."""
    defaults: dict[str, object] = dict(
        experiment_name="test_experiment",
        seed=42,
        alpha_levels=(0.10,),
        n_calibration=100,
        n_test=100,
        n_scenarios=3,
        class_names=("civilian", "military", "unknown"),
        data_source="synthetic",
        classifier_confidence=0.70,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)  # type: ignore[arg-type]


def test_runconfig_validates_seed():
    with pytest.raises(ValueError, match="seed"):
        _minimal_config(seed=-1)


def test_runconfig_validates_alpha():
    with pytest.raises(ValueError, match="alpha"):
        _minimal_config(alpha_levels=(0.5, 1.2))
    with pytest.raises(ValueError, match="empty"):
        _minimal_config(alpha_levels=())


def test_runconfig_validates_sizes():
    with pytest.raises(ValueError, match="n_calibration"):
        _minimal_config(n_calibration=5)
    with pytest.raises(ValueError, match="n_test"):
        _minimal_config(n_test=5)
    with pytest.raises(ValueError, match="n_scenarios"):
        _minimal_config(n_scenarios=0)


def test_runconfig_validates_class_names():
    with pytest.raises(ValueError, match="class_names"):
        _minimal_config(class_names=())


def test_runconfig_validates_confidence():
    with pytest.raises(ValueError, match="classifier_confidence"):
        _minimal_config(classifier_confidence=0.0)
    with pytest.raises(ValueError, match="classifier_confidence"):
        _minimal_config(classifier_confidence=1.5)


def test_runconfig_yaml_roundtrip(tmp_path: Path):
    """YAML file -> RunConfig -> dict -> YAML file -> RunConfig == original."""
    import yaml  # type: ignore[import-untyped]

    original = _minimal_config()
    yaml_path = tmp_path / "cfg.yaml"
    yaml_path.write_text(yaml.safe_dump(original.to_dict()), encoding="utf-8")

    reloaded = RunConfig.from_yaml(yaml_path)
    assert reloaded == original


def test_runconfig_to_dict_is_json_safe():
    """to_dict output must be JSON-serialisable (no tuples, no custom classes)."""
    cfg = _minimal_config()
    d = cfg.to_dict()
    # Round-trip through json must not raise
    s = json.dumps(d)
    d2 = json.loads(s)
    assert d2["alpha_levels"] == [0.10]  # list, not tuple
    assert d2["class_names"] == ["civilian", "military", "unknown"]


def test_run_conformal_validation_produces_result():
    cfg = _minimal_config()
    result = run_conformal_validation(cfg)

    assert isinstance(result, ExperimentResult)
    assert result.config == cfg
    assert len(result.coverage_per_alpha) == 1
    assert result.coverage_per_alpha[0].alpha == 0.10
    assert 0.0 <= result.coverage_per_alpha[0].mean_coverage <= 1.0
    assert result.runtime_seconds > 0.0
    # git_sha should be either 7+ chars of hex or 'unknown'
    assert result.git_sha == "unknown" or len(result.git_sha) >= 7


def test_determinism_of_experiment():
    """Same config, run twice, must produce identical numerical outputs.

    This is the core reproducibility invariant. If this breaks, the framework
    is fundamentally broken.
    """
    cfg = _minimal_config()

    result1 = run_conformal_validation(cfg)
    result2 = run_conformal_validation(cfg)

    # Compare numerical fields (ignoring timestamps and runtimes)
    assert len(result1.coverage_per_alpha) == len(result2.coverage_per_alpha)
    for cr1, cr2 in zip(
        result1.coverage_per_alpha, result2.coverage_per_alpha, strict=True
    ):
        assert cr1.alpha == cr2.alpha
        assert cr1.mean_coverage == cr2.mean_coverage
        assert cr1.min_coverage == cr2.min_coverage
        assert cr1.max_coverage == cr2.max_coverage
        assert cr1.mean_set_size == cr2.mean_set_size
        assert cr1.q_hat_median == cr2.q_hat_median


def test_different_seed_produces_different_results():
    """Changing seed must change output. Otherwise seed is not being used."""
    cfg1 = _minimal_config(seed=42)
    cfg2 = _minimal_config(seed=99)

    result1 = run_conformal_validation(cfg1)
    result2 = run_conformal_validation(cfg2)

    # At least one of the coverage numbers should differ
    cr1 = result1.coverage_per_alpha[0]
    cr2 = result2.coverage_per_alpha[0]
    differs = (
        cr1.mean_coverage != cr2.mean_coverage
        or cr1.q_hat_median != cr2.q_hat_median
    )
    assert differs, "Different seeds produced identical results — seeding broken"


def test_unsupported_data_source_raises():
    cfg = _minimal_config(data_source="s3://some/bucket/data.parquet")
    with pytest.raises(NotImplementedError, match="synthetic"):
        run_conformal_validation(cfg)


def test_result_to_json_valid():
    cfg = _minimal_config()
    result = run_conformal_validation(cfg)
    s = result.to_json()
    parsed = json.loads(s)
    assert parsed["config"]["experiment_name"] == "test_experiment"
    assert parsed["config"]["seed"] == 42
    assert "coverage_per_alpha" in parsed
    assert "git_sha" in parsed
    assert "timestamp_utc" in parsed


def test_result_save_produces_file(tmp_path: Path):
    cfg = _minimal_config()
    result = run_conformal_validation(cfg)
    path = result.save(tmp_path)

    assert path.exists()
    assert path.suffix == ".json"
    assert cfg.experiment_name in path.name

    # File must be valid JSON
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["config"]["experiment_name"] == cfg.experiment_name


def test_coverage_guarantee_holds():
    """With sensible defaults, mean coverage should meet target - tolerance."""
    cfg = _minimal_config(
        n_calibration=500,
        n_test=500,
        n_scenarios=20,
        alpha_levels=(0.10, 0.05),
    )
    result = run_conformal_validation(cfg)

    for cr in result.coverage_per_alpha:
        assert cr.passes_guarantee, (
            f"alpha={cr.alpha}: empirical coverage {cr.mean_coverage:.4f} "
            f"below target {cr.target_coverage:.4f} - tolerance"
        )


def test_seed_override_via_replace():
    """Seed override pattern (used by CLI) works correctly."""
    cfg_original = _minimal_config(seed=42)
    cfg_overridden = replace(cfg_original, seed=7)

    assert cfg_overridden.seed == 7
    assert cfg_original.seed == 42  # original unchanged
    # All other fields preserved
    assert cfg_overridden.alpha_levels == cfg_original.alpha_levels
    assert cfg_overridden.class_names == cfg_original.class_names
