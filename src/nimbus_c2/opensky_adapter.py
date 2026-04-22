# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
OpenSky Network adapter — dual-mode ingestion of ADS-B state vectors.

This module is the Stage-2 data-ingestion layer. It provides a single
interface for fetching state vectors from the OpenSky Network in two
modes:

    mode="live"     — hits https://opensky-network.org/api/states/all
                      via OAuth2 client credentials and returns the
                      most recent state vectors for a bounding box.

    mode="offline"  — reads the same format from local cache files,
                      produced previously by either live runs (saved
                      automatically) or independent batch downloads.

The dual-mode design is deliberate: it preserves reproducibility
(critical for any downstream statistical claim like conformal coverage)
while still supporting live operational ingestion. The two modes yield
byte-identical ``StateVector`` dataclass outputs given the same raw
JSON, so any analysis written against this module is source-neutral.

---

**Schema reference.** The state-vector tuple layout follows the
authoritative OpenSky REST API specification. Each state vector is a
17-element array with fixed positional semantics:

    0  icao24         unique 24-bit ICAO transponder address (hex str)
    1  callsign       8-char callsign; may be null
    2  origin_country country inferred from icao24 prefix
    3  time_position  unix ts of last position update; may be null
    4  last_contact   unix ts of most recent transponder contact
    5  longitude      WGS-84 decimal degrees; may be null
    6  latitude       WGS-84 decimal degrees; may be null
    7  baro_altitude  barometric altitude in metres; may be null
    8  on_ground      bool — surface-position report
    9  velocity       ground speed in m/s; may be null
    10 true_track     heading in decimal degrees (north=0°)
    11 vertical_rate  m/s, positive climbing
    12 sensors        list of receiver IDs; usually null
    13 geo_altitude   geometric altitude in metres
    14 squawk         transponder code; may be null
    15 spi            special purpose indicator
    16 position_source 0=ADS-B, 1=ASTERIX, 2=MLAT, 3=FLARM

An optional 18th field (``category``) is returned when the request
includes ``extended=1``; this adapter does not request it by default
(reduces credit cost and keeps the schema stable). Stage 2b may opt in.

---

**Authentication.** As of 2024 OpenSky exclusively supports OAuth2
client credentials. Basic auth is no longer accepted. Credentials are
read from environment variables ``OPENSKY_CLIENT_ID`` and
``OPENSKY_CLIENT_SECRET`` (never from code, never committed to repo).
Anonymous access is still possible but comes with a ×10 reduction in
daily credit quota (400 vs 4000). For calibration-grade data
collection — the motivation for this adapter — authenticated access
is the default.

**Rate limit awareness.** The adapter tracks remaining credits via the
``X-Rate-Limit-Remaining`` response header and refuses to issue new
requests when the balance drops below a configurable floor. This is
the courtesy-citizen pattern expected by OpenSky and documented as
the right approach in their research guidelines.

**Scientific provenance.** OpenSky is described in Schäfer et al.
(2014), IPSN. The adapter's default bounding box for Baltic / Gotland
(lat 54–60.5, lon 10–24) is consistent with EUROCONTROL and SESAR
research practice for Nordic airspace studies. See docs/REFERENCES.md.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

# --------------------------------------------------------------------------- #
# Canonical bounding boxes                                                    #
# --------------------------------------------------------------------------- #

#: Baltic Sea + Gotland airspace, covering Swedish-relevant operations.
#: Values chosen to include Stockholm (59.33, 18.07), Gotland (57.53, 18.36),
#: and the approaches to Copenhagen, Helsinki, Tallinn, Riga.
BBOX_BALTIC: tuple[float, float, float, float] = (54.0, 10.0, 60.5, 24.0)

#: Narrower Gotland-focused box for higher temporal-resolution studies.
BBOX_GOTLAND_NARROW: tuple[float, float, float, float] = (56.5, 17.0, 58.5, 20.0)

#: OpenSky endpoints.
API_BASE = "https://opensky-network.org/api"
STATES_ALL_ENDPOINT = f"{API_BASE}/states/all"
TOKEN_ENDPOINT = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)


# --------------------------------------------------------------------------- #
# Typed state-vector record                                                   #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StateVector:
    """One OpenSky ADS-B state vector, schema-faithful.

    The field names match the OpenSky REST API property names exactly
    (not snake-cased differently); this guarantees 1:1 correspondence
    between an archived JSON cache and this dataclass without any
    post-hoc translation.
    """
    icao24: str
    callsign: str | None
    origin_country: str | None
    time_position: int | None
    last_contact: int | None
    longitude: float | None
    latitude: float | None
    baro_altitude: float | None
    on_ground: bool
    velocity: float | None
    true_track: float | None
    vertical_rate: float | None
    sensors: list[int] | None
    geo_altitude: float | None
    squawk: str | None
    spi: bool
    position_source: int | None

    @classmethod
    def from_array(cls, row: Sequence[Any]) -> StateVector:
        """Construct from a raw OpenSky state-vector tuple.

        OpenSky returns state vectors as fixed-length arrays; this
        method maps by index position per the official schema. Callers
        should never index into the raw array directly.
        """
        if len(row) < 17:
            raise ValueError(
                f"State vector must have ≥17 fields (got {len(row)}); "
                f"schema may have changed — re-check OpenSky API docs."
            )
        return cls(
            icao24=str(row[0]).lower().strip() if row[0] else "",
            callsign=_clean_callsign(row[1]),
            origin_country=str(row[2]) if row[2] else None,
            time_position=int(row[3]) if row[3] is not None else None,
            last_contact=int(row[4]) if row[4] is not None else None,
            longitude=float(row[5]) if row[5] is not None else None,
            latitude=float(row[6]) if row[6] is not None else None,
            baro_altitude=float(row[7]) if row[7] is not None else None,
            on_ground=bool(row[8]),
            velocity=float(row[9]) if row[9] is not None else None,
            true_track=float(row[10]) if row[10] is not None else None,
            vertical_rate=float(row[11]) if row[11] is not None else None,
            sensors=list(row[12]) if row[12] else None,
            geo_altitude=float(row[13]) if row[13] is not None else None,
            squawk=str(row[14]) if row[14] else None,
            spi=bool(row[15]),
            position_source=int(row[16]) if row[16] is not None else None,
        )

    def has_position(self) -> bool:
        """True iff longitude and latitude are both known."""
        return self.longitude is not None and self.latitude is not None

    def is_in_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> bool:
        """True iff the track's position lies inside (lamin, lomin, lamax, lomax)."""
        if not self.has_position():
            return False
        assert self.latitude is not None
        assert self.longitude is not None
        lamin, lomin, lamax, lomax = bbox
        return (
            lamin <= self.latitude <= lamax
            and lomin <= self.longitude <= lomax
        )


def _clean_callsign(v: Any) -> str | None:
    """OpenSky pads callsigns to 8 chars with trailing spaces. Strip them."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# --------------------------------------------------------------------------- #
# Snapshot container                                                          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StateSnapshot:
    """One fetch worth of OpenSky data, with provenance metadata."""
    fetch_time_utc: str                  # ISO-8601 UTC
    source_time_unix: int                # OpenSky's `time` field
    bbox: tuple[float, float, float, float]
    authenticated: bool
    states: list[StateVector]
    raw_count: int                       # tracks returned by API
    in_bbox_count: int                   # after local bbox enforcement
    source: Literal["opensky_live", "offline_cache"]
    cache_path: str | None = None     # if written to / read from disk
    rate_limit_remaining: int | None = None

    def as_jsonable(self) -> dict[str, Any]:
        """Serialise to dict suitable for json.dump."""
        return {
            "fetch_time_utc": self.fetch_time_utc,
            "source_time_unix": self.source_time_unix,
            "bbox": list(self.bbox),
            "authenticated": self.authenticated,
            "raw_count": self.raw_count,
            "in_bbox_count": self.in_bbox_count,
            "source": self.source,
            "cache_path": self.cache_path,
            "rate_limit_remaining": self.rate_limit_remaining,
            "states": [asdict(s) for s in self.states],
        }

    @classmethod
    def from_jsonable(cls, payload: dict[str, Any]) -> StateSnapshot:
        """Reconstruct from a dict previously produced by as_jsonable()."""
        states = [
            StateVector(**s) for s in payload["states"]
        ]
        return cls(
            fetch_time_utc=payload["fetch_time_utc"],
            source_time_unix=int(payload["source_time_unix"]),
            bbox=tuple(payload["bbox"]),
            authenticated=bool(payload["authenticated"]),
            states=states,
            raw_count=int(payload["raw_count"]),
            in_bbox_count=int(payload["in_bbox_count"]),
            source=payload["source"],
            cache_path=payload.get("cache_path"),
            rate_limit_remaining=payload.get("rate_limit_remaining"),
        )


# --------------------------------------------------------------------------- #
# OAuth2 token manager                                                        #
# --------------------------------------------------------------------------- #

class TokenManager:
    """Minimal OAuth2 client-credentials token cache for OpenSky.

    Mirrors the pattern documented in OpenSky's official Python example,
    with a proactive refresh margin so a token that expires mid-request
    never surfaces as a 401. Thread-safety is not required here because
    Stage 2 data collection is single-process.
    """

    REFRESH_MARGIN_SEC = 30

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        http_get: Any = None,
        http_post: Any = None,
    ) -> None:
        self.client_id = client_id or os.environ.get("OPENSKY_CLIENT_ID")
        self.client_secret = (
            client_secret or os.environ.get("OPENSKY_CLIENT_SECRET")
        )
        self._token: str | None = None
        self._expires_at: datetime | None = None
        # Injectable for tests; default to requests when running live.
        self._http_post = http_post

    def have_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing if needed."""
        if not self.have_credentials():
            raise RuntimeError(
                "OpenSky OAuth2 credentials not configured. Set "
                "OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET "
                "environment variables, or pass them to TokenManager()."
            )
        now = datetime.now(timezone.utc)
        if self._token and self._expires_at and now < self._expires_at:
            return self._token
        return self._refresh()

    def _refresh(self) -> str:
        """Fetch a fresh access token from the OpenSky auth server."""
        if self._http_post is None:
            import requests  # local import — adapter must import-cleanly w/o requests
            self._http_post = requests.post
        resp = self._http_post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 1800))
        self._expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in - self.REFRESH_MARGIN_SEC
        )
        return self._token

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}"}


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #

class OpenSkyAdapter:
    """Dual-mode OpenSky ingestion.

    Construct once, reuse across fetches. Rate-limit state is kept on
    the instance so repeated calls self-throttle correctly.

    Examples
    --------
    Live, authenticated, Baltic bbox::

        adapter = OpenSkyAdapter(mode="live", bbox=BBOX_BALTIC)
        snap = adapter.fetch(cache_dir="data/opensky_cache")

    Offline replay::

        adapter = OpenSkyAdapter(mode="offline")
        for snap in adapter.replay("data/opensky_cache"):
            print(snap.fetch_time_utc, snap.in_bbox_count)
    """

    def __init__(
        self,
        *,
        mode: Literal["live", "offline"] = "live",
        bbox: tuple[float, float, float, float] = BBOX_BALTIC,
        min_credits_floor: int = 200,
        token_manager: TokenManager | None = None,
        http_get: Any = None,
    ) -> None:
        if mode not in ("live", "offline"):
            raise ValueError(f"mode must be 'live' or 'offline', got {mode!r}")
        self.mode = mode
        self.bbox = bbox
        self.min_credits_floor = int(min_credits_floor)
        self._http_get = http_get
        self._tokens = token_manager
        self._last_rate_limit_remaining: int | None = None

    @property
    def last_rate_limit_remaining(self) -> int | None:
        return self._last_rate_limit_remaining

    # --------------------------------------------------------------------- #
    # Live fetch                                                            #
    # --------------------------------------------------------------------- #

    def fetch(
        self,
        *,
        cache_dir: str | Path | None = None,
    ) -> StateSnapshot:
        """Fetch one snapshot from the OpenSky REST API.

        Parameters
        ----------
        cache_dir :
            Directory to persist this snapshot as JSON. If None, no
            caching. The path structure is
            ``cache_dir/YYYY-MM-DD/HHMMSS.json`` so a night-long run
            produces a date-partitioned archive.

        Raises
        ------
        RuntimeError
            If the adapter is in offline mode, or if the remaining
            credit balance is below ``min_credits_floor``.
        """
        if self.mode != "live":
            raise RuntimeError(
                f"fetch() requires mode='live'; adapter is in {self.mode!r}"
            )

        if (
            self._last_rate_limit_remaining is not None
            and self._last_rate_limit_remaining < self.min_credits_floor
        ):
            raise RuntimeError(
                f"OpenSky rate-limit floor hit: "
                f"{self._last_rate_limit_remaining} remaining "
                f"< floor {self.min_credits_floor}. Pause collection."
            )

        headers: dict[str, str] = {}
        authenticated = False
        if self._tokens is None:
            self._tokens = TokenManager()
        if self._tokens.have_credentials():
            headers.update(self._tokens.auth_headers())
            authenticated = True

        lamin, lomin, lamax, lomax = self.bbox
        params = {
            "lamin": lamin, "lomin": lomin,
            "lamax": lamax, "lomax": lomax,
        }
        url = f"{STATES_ALL_ENDPOINT}?{urlencode(params)}"

        resp = self._do_get(url, headers)
        resp_status = getattr(resp, "status_code", 200)
        if resp_status == 401:
            raise RuntimeError(
                "OpenSky 401 Unauthorized — token likely expired or "
                "credentials invalid. TokenManager will refresh on next call."
            )
        if resp_status == 429:
            raise RuntimeError(
                "OpenSky 429 Too Many Requests — credit quota exhausted. "
                "Retry after the interval indicated by "
                "X-Rate-Limit-Retry-After-Seconds."
            )
        if resp_status >= 400:
            raise RuntimeError(
                f"OpenSky HTTP {resp_status}: {getattr(resp, 'text', '')[:300]}"
            )

        # Track remaining credits courteously.
        resp_headers = getattr(resp, "headers", {}) or {}
        remaining = resp_headers.get("X-Rate-Limit-Remaining")
        if remaining is not None:
            try:
                self._last_rate_limit_remaining = int(remaining)
            except (TypeError, ValueError):
                pass

        data = resp.json()
        raw_states = data.get("states") or []
        states = [StateVector.from_array(row) for row in raw_states]
        # Enforce bbox locally too; OpenSky mostly does this but
        # null-position records sometimes leak through.
        in_bbox = [s for s in states if s.is_in_bbox(self.bbox)]

        snap = StateSnapshot(
            fetch_time_utc=datetime.now(timezone.utc).isoformat(),
            source_time_unix=int(data.get("time") or 0),
            bbox=self.bbox,
            authenticated=authenticated,
            states=in_bbox,
            raw_count=len(states),
            in_bbox_count=len(in_bbox),
            source="opensky_live",
            rate_limit_remaining=self._last_rate_limit_remaining,
        )

        if cache_dir is not None:
            cache_path = self._write_cache(snap, cache_dir)
            # StateSnapshot is frozen; rebuild with the cache_path filled.
            snap = StateSnapshot(
                fetch_time_utc=snap.fetch_time_utc,
                source_time_unix=snap.source_time_unix,
                bbox=snap.bbox,
                authenticated=snap.authenticated,
                states=snap.states,
                raw_count=snap.raw_count,
                in_bbox_count=snap.in_bbox_count,
                source=snap.source,
                cache_path=str(cache_path),
                rate_limit_remaining=snap.rate_limit_remaining,
            )

        return snap

    def _do_get(self, url: str, headers: dict[str, str]) -> Any:
        """HTTP GET, injectable for tests."""
        if self._http_get is not None:
            return self._http_get(url, headers=headers, timeout=30)
        import requests
        return requests.get(url, headers=headers, timeout=30)

    # --------------------------------------------------------------------- #
    # Cache write / read                                                    #
    # --------------------------------------------------------------------- #

    @staticmethod
    def _write_cache(snap: StateSnapshot, cache_dir: str | Path) -> Path:
        """Persist a snapshot to cache_dir/YYYY-MM-DD/HHMMSS.json."""
        base = Path(cache_dir)
        # Parse fetch_time_utc for date partitioning.
        ft = datetime.fromisoformat(snap.fetch_time_utc.replace("Z", "+00:00"))
        day_dir = base / ft.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        file_path = day_dir / (ft.strftime("%H%M%S") + ".json")
        with file_path.open("w", encoding="utf-8") as fh:
            json.dump(snap.as_jsonable(), fh, indent=2, sort_keys=True)
        return file_path

    # --------------------------------------------------------------------- #
    # Offline replay                                                        #
    # --------------------------------------------------------------------- #

    def replay(
        self, cache_dir: str | Path
    ) -> Iterable[StateSnapshot]:
        """Yield cached snapshots in chronological order.

        The directory layout is the one written by ``fetch(cache_dir=…)``:
        ``cache_dir/YYYY-MM-DD/HHMMSS.json``. Files outside this layout
        are ignored (but not treated as an error).
        """
        base = Path(cache_dir)
        if not base.exists():
            return
        json_files = sorted(base.glob("*/*.json"))
        for fp in json_files:
            try:
                with fp.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                snap = StateSnapshot.from_jsonable(payload)
                # Overwrite source label when reading from disk — the
                # data is no longer "live" regardless of how it was
                # captured originally.
                yield StateSnapshot(
                    fetch_time_utc=snap.fetch_time_utc,
                    source_time_unix=snap.source_time_unix,
                    bbox=snap.bbox,
                    authenticated=snap.authenticated,
                    states=snap.states,
                    raw_count=snap.raw_count,
                    in_bbox_count=snap.in_bbox_count,
                    source="offline_cache",
                    cache_path=str(fp),
                    rate_limit_remaining=snap.rate_limit_remaining,
                )
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                # Skip corrupt cache files silently; the collection
                # script logs them. Silent skip here keeps offline
                # analysis robust.
                continue


__all__ = [
    "BBOX_BALTIC",
    "BBOX_GOTLAND_NARROW",
    "OpenSkyAdapter",
    "StateSnapshot",
    "StateVector",
    "TokenManager",
]
