<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Stage 2a — OpenSky data ingestion

This document covers the Stage-2a data layer: a dual-mode OpenSky
Network adapter plus an overnight collection script that together
produce the real-world calibration dataset needed for Stage-2b
conformal prediction.

**Scope of Stage 2a.** Live + offline adapter, cache-writing,
rate-limit-aware collection script, unit tests. The conformal
prediction layer itself is Stage 2b — built once Stage 2a has
produced enough data.

**Not scope.** Classifier training, ICAO metadata lookup,
conformal calibration, assurance-layer integration. All of that is
Stage 2b / 2c.

---

## 1. Setup — authenticate against OpenSky

OpenSky requires OAuth2 client credentials as of 2024. Anonymous
access still works but caps the daily quota at 400 credits (vs 4000
for authenticated). For calibration-grade data collection, register:

1. Log in at https://opensky-network.org/my-opensky/
2. Visit the **Account** page → **API Clients**
3. Create a new client. You receive a `client_id` and `client_secret`.
4. Export them as environment variables before running the collection
   script. **Never commit credentials.**

### Windows PowerShell

```powershell
$env:OPENSKY_CLIENT_ID = "your-client-id"
$env:OPENSKY_CLIENT_SECRET = "your-client-secret"
```

### Linux / macOS

```bash
export OPENSKY_CLIENT_ID=your-client-id
export OPENSKY_CLIENT_SECRET=your-client-secret
```

The `TokenManager` class reads these automatically. No hard-coded
credentials anywhere in the codebase.

---

## 2. Smoke test — 3-minute dry run

Before starting an overnight run, verify the adapter reaches OpenSky
and caches correctly:

```powershell
python scripts/collect_opensky.py `
    --cache-dir data/opensky_cache `
    --interval-seconds 30 `
    --duration-hours 0.05
```

That runs for ~3 minutes, fetches ~6 snapshots, saves them to
`data/opensky_cache/YYYY-MM-DD/HHMMSS.json`, and prints:

```
[INFO] Collection start 2026-04-21T23:00:00+00:00 · bbox=baltic · ...
[OK] t=2026-04-21T23:00:02+00:00 raw=42 in_bbox=38 credits_remaining=3998 cache=...
[OK] t=2026-04-21T23:00:32+00:00 raw=41 in_bbox=37 credits_remaining=3996 cache=...
...
[INFO] END 2026-04-21T23:03:00+00:00 · ok=6 err=0 runtime=180s
```

**Exit gate for the smoke test:** ≥ 1 snapshot cached, each with
`in_bbox > 0` (sanity check — the Baltic bbox is airspace-dense so
zero tracks would indicate a query problem, not a no-traffic moment).

---

## 3. Overnight collection

Once the smoke test passes, run for 12 hours:

```powershell
python scripts/collect_opensky.py `
    --cache-dir data/opensky_cache `
    --interval-seconds 300 `
    --duration-hours 12
```

Expected resource usage:

| Item | Per snapshot | Over 12 h @ 5-min |
|------|-------------:|------------------:|
| OpenSky credits | 2 | ~288 (7% of daily quota) |
| Disk space | ~50–200 KB | ~15–60 MB |
| Bandwidth | ~50–200 KB | ~15–60 MB |

The script is CTRL+C-safe: it finishes any in-flight fetch before
exiting. All cached files are complete JSON — partial writes do not
occur.

### Choosing a bounding box

- `--bbox baltic` — lat 54–60.5, lon 10–24 (default). Covers Swedish,
  Danish, Finnish, Estonian, Latvian airspace plus relevant ocean.
  2 credits per request.
- `--bbox gotland` — lat 56.5–58.5, lon 17–20. Narrower box for
  higher-resolution Gotland studies. 1 credit per request.

### Resumability

Every run appends new date-partitioned files. You can stop, resume,
or run multiple nights to a single cache directory. The replayer
reads them chronologically.

---

## 4. Using the cached data

In Python:

```python
from nimbus_c2 import OpenSkyAdapter

adapter = OpenSkyAdapter(mode="offline")
for snap in adapter.replay("data/opensky_cache"):
    print(
        snap.fetch_time_utc,
        "tracks:", snap.in_bbox_count,
        "authenticated:", snap.authenticated,
    )
    for sv in snap.states:
        # sv is a StateVector — see src/nimbus_c2/opensky_adapter.py
        # for the full schema. Key fields for calibration:
        #   sv.icao24            (ground-truth class lookup key)
        #   sv.latitude, sv.longitude
        #   sv.baro_altitude, sv.velocity, sv.true_track
        ...
```

This is the interface Stage 2b's conformal-prediction module will
consume. Same adapter, same dataclasses, no translation layer.

---

## 5. Scientific grounding

**OpenSky Network** — Schäfer, M., Strohmeier, M., Lenders, V.,
Martinovic, I., & Wilhelm, M. (2014). *Bringing Up OpenSky: A
Large-scale ADS-B Sensor Network for Research.* IPSN '14.

**OpenSky REST API spec** — https://openskynetwork.github.io/opensky-api/rest.html
(verified against the version current as of April 2026).

**Baltic/Gotland airspace context** — EUROCONTROL Performance Review
Reports; consistent with SESAR research practice for Nordic airspace
studies.

See `docs/REFERENCES.md` for the full bibliographic record.

---

## 6. What Stage 2b will add

- **ICAO metadata lookup** against the OpenSky aircraft database
  (https://opensky-network.org/datasets/metadata), to produce
  `icao24 → aircraft-type` ground-truth labels.
- **Synthetic classifier** producing softmax scores over a fixed
  threat-type taxonomy, calibrated to match OpenSky metadata labels
  with controlled noise (simulates realistic sensor-fusion output).
- **Split conformal prediction wrapper** (Angelopoulos & Bates 2023)
  yielding prediction sets with guaranteed marginal coverage
  $P(y \in C_\alpha(x)) \ge 1 - \alpha$ under exchangeability.
- **Assurance-layer integration** — a new DEFER trigger when
  prediction-set size exceeds a threshold, evidencing epistemic
  uncertainty.
- **Empirical coverage validation** — 500 seeded scenarios showing
  realised coverage within $\pm 2$ percentage points of
  $1 - \alpha$ for $\alpha \in \{0.05, 0.10\}$.

All contingent on having real calibration data from this Stage 2a
adapter first. No data, no conformal bounds.
