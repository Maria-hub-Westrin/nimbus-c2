#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""CLI entry point for reproducible experiment runs.

Usage
-----
    python run_validation.py --config configs/stage2b_conformal_validation.yaml
    python run_validation.py --config configs/stage2b_conformal_validation.yaml --seed 7
    python run_validation.py --config <path> --output results/custom.json

Exit codes
----------
    0 — experiment passed all coverage guarantees
    1 — experiment failed one or more coverage guarantees
    2 — config loading or experiment setup failed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nimbus_c2.experiments import RunConfig, run_conformal_validation


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a reproducible Nimbus-C2 validation experiment. "
            "The config file specifies what to run; the git_sha of the "
            "current repository is automatically captured in the result."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML experiment configuration file.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Override the seed in the config (e.g. for sensitivity analysis). "
            "If not given, uses the seed from the config file."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results"),
        help="Directory for output JSON. Default: ./results",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable summary; print only the output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        config = RunConfig.from_yaml(args.config)
    except FileNotFoundError:
        print(f"ERROR: config file not found: {args.config}", file=sys.stderr)
        return 2
    except (ValueError, TypeError) as e:
        print(f"ERROR: invalid config: {e}", file=sys.stderr)
        return 2

    # Apply CLI overrides
    if args.seed is not None:
        from dataclasses import replace

        config = replace(config, seed=args.seed)

    if not args.quiet:
        print(f"Running experiment: {config.experiment_name}")
        print(f"  seed             = {config.seed}")
        print(f"  alpha levels     = {config.alpha_levels}")
        print(f"  n_calibration    = {config.n_calibration}")
        print(f"  n_test           = {config.n_test}")
        print(f"  n_scenarios      = {config.n_scenarios}")
        print(f"  data_source      = {config.data_source}")
        print("")

    result = run_conformal_validation(config)
    output_path = result.save(args.output_dir)

    if not args.quiet:
        print(f"Completed in {result.runtime_seconds:.2f}s")
        print(f"  git_sha          = {result.git_sha[:7]}")
        if result.git_is_dirty:
            print("  WARNING: working tree was dirty")
        print("")
        print("Coverage results:")
        for cr in result.coverage_per_alpha:
            marker = "PASS" if cr.passes_guarantee else "FAIL"
            print(
                f"  alpha={cr.alpha:.2f}  target={cr.target_coverage:.3f}  "
                f"empirical={cr.mean_coverage:.4f}  "
                f"mean_set_size={cr.mean_set_size:.2f}  [{marker}]"
            )
        print("")
        print(f"Result written to: {output_path}")
    else:
        print(output_path)

    # Exit code reflects coverage guarantee pass/fail
    all_passed = all(cr.passes_guarantee for cr in result.coverage_per_alpha)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
