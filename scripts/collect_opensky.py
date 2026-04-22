# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Collect OpenSky state vectors over a period, into a date-partitioned cache.

Intended as an overnight run that builds a real calibration dataset for
Stage 2a (conformal prediction). Uses the OpenSkyAdapter under the hood.

Behaviour:
- Fetches one snapshot per ``--interval-seconds`` (default 300 = 5 min).
- Saves each snapshot to ``--cache-dir/YYYY-MM-DD/HHMMSS.json``.
- Logs a one-line summary per fetch to stdout plus to ``collection.log``
  inside the cache directory.
- Self-terminates if rate-limit credits drop below the floor.
- Responds to CTRL+C gracefully — no partial files left behind.
- Can be resumed: every run just appends new timestamped files.

Usage::

    $env:OPENSKY_CLIENT_ID="..."     # PowerShell
    $env:OPENSKY_CLIENT_SECRET="..."
    python scripts/collect_opensky.py `
        --cache-dir data/opensky_cache `
        --interval-seconds 300 `
        --duration-hours 12

For a quick smoke test run with ``--duration-hours 0.1 --interval-seconds 30``.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Adapter imports deferred into main() so --help does not require the package
# to be installed; this makes the script usable as a standalone documentation
# source even before `pip install -e .` runs.


_STOP = False


def _handle_sigint(signum, frame):
    global _STOP
    _STOP = True
    print("\n[INFO] Interrupt received — finishing current fetch and exiting.",
          flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect OpenSky state vectors for overnight calibration."
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/opensky_cache"),
        help="Where to write date-partitioned JSON snapshots.",
    )
    p.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Seconds between fetches. Default 300 (5 min). Minimum 30.",
    )
    p.add_argument(
        "--duration-hours",
        type=float,
        default=12.0,
        help="Total run length. Use small values (0.1) for smoke tests.",
    )
    p.add_argument(
        "--bbox",
        choices=["baltic", "gotland"],
        default="baltic",
        help="Which canonical bounding box to use.",
    )
    p.add_argument(
        "--min-credits-floor",
        type=int,
        default=200,
        help="Pause if remaining credits drop below this floor.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval_seconds < 30:
        print(
            "[ERROR] --interval-seconds must be ≥ 30 to respect OpenSky "
            "rate limits and 10-second time resolution.",
            file=sys.stderr,
        )
        return 2

    # Lazy imports so --help works without the package installed.
    from nimbus_c2.opensky_adapter import (
        BBOX_BALTIC,
        BBOX_GOTLAND_NARROW,
        OpenSkyAdapter,
    )

    bbox = BBOX_BALTIC if args.bbox == "baltic" else BBOX_GOTLAND_NARROW
    cache_dir: Path = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = cache_dir / "collection.log"

    adapter = OpenSkyAdapter(
        mode="live",
        bbox=bbox,
        min_credits_floor=args.min_credits_floor,
    )

    signal.signal(signal.SIGINT, _handle_sigint)

    start = datetime.now(timezone.utc)
    end = start.timestamp() + args.duration_hours * 3600.0
    n_ok = 0
    n_err = 0

    print(
        f"[INFO] Collection start {start.isoformat()} · "
        f"bbox={args.bbox} · interval={args.interval_seconds}s · "
        f"duration={args.duration_hours}h · cache={cache_dir}",
        flush=True,
    )
    _log(log_path, f"START bbox={args.bbox} interval={args.interval_seconds}s "
                    f"duration={args.duration_hours}h")

    while not _STOP and time.time() < end:
        tick = time.time()
        try:
            snap = adapter.fetch(cache_dir=cache_dir)
            n_ok += 1
            remain = adapter.last_rate_limit_remaining
            msg = (
                f"[OK] t={snap.fetch_time_utc} "
                f"raw={snap.raw_count} in_bbox={snap.in_bbox_count} "
                f"credits_remaining={remain if remain is not None else '?'} "
                f"cache={snap.cache_path}"
            )
            print(msg, flush=True)
            _log(log_path, msg)
        except Exception as exc:  # noqa: BLE001 — we genuinely want broad catch
            n_err += 1
            msg = f"[ERR] {type(exc).__name__}: {exc}"
            print(msg, flush=True)
            _log(log_path, msg)
            # If we hit the floor, stop; there's no point grinding on.
            if "rate-limit floor" in str(exc) or "quota exhausted" in str(exc):
                print("[INFO] Credit floor reached — stopping cleanly.",
                      flush=True)
                break

        # Sleep to next tick, but wake early if a stop is requested.
        next_tick = tick + args.interval_seconds
        while not _STOP and time.time() < next_tick and time.time() < end:
            time.sleep(min(2.0, next_tick - time.time()))

    end_time = datetime.now(timezone.utc)
    summary = (
        f"END {end_time.isoformat()} · ok={n_ok} err={n_err} "
        f"runtime={(end_time - start).total_seconds():.0f}s"
    )
    print(f"[INFO] {summary}", flush=True)
    _log(log_path, summary)

    return 0 if n_ok > 0 else 1


def _log(log_path: Path, msg: str) -> None:
    """Append a line to collection.log."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts}  {msg}\n")
    except OSError:
        pass  # do not let logging break the collection loop


if __name__ == "__main__":
    raise SystemExit(main())
