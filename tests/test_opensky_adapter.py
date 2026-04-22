# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Tests for the OpenSky adapter.

These tests mock the HTTP layer entirely so they run offline and
deterministically. They verify:

* StateVector schema-faithful parsing from raw OpenSky tuples
* Bounding-box filtering (both remote and local-enforcement)
* Round-tripping snapshots through JSON cache
* TokenManager caching / refresh logic
* Rate-limit floor enforcement
* Replay over a cache directory produces snapshots in order

No test makes a real HTTP call.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.opensky_adapter import (  # noqa: E402
    BBOX_BALTIC,
    BBOX_GOTLAND_NARROW,
    OpenSkyAdapter,
    StateSnapshot,
    StateVector,
    TokenManager,
)

# --------------------------------------------------------------------------- #
# Fixtures — raw state-vector tuples matching OpenSky schema                  #
# --------------------------------------------------------------------------- #

# A Stockholm-area airliner, well inside the Baltic bbox.
_SAS_OVER_STOCKHOLM = [
    "4ac9f1", "SAS821  ", "Sweden", 1713700800, 1713700802,
    18.0637, 59.3293, 10058.4, False, 245.8, 180.5, -2.5,
    None, 10363.2, "1234", False, 0,
]

# A Gotland-area flight, inside Gotland narrow box.
_SAS_OVER_GOTLAND = [
    "4ac9f2", "SAS501  ", "Sweden", 1713700800, 1713700802,
    18.3615, 57.5302, 9144.0, False, 239.0, 90.0, 0.0,
    None, 9500.0, None, False, 0,
]

# Somewhere over central Germany — outside Baltic bbox.
_LH_OVER_MUNICH = [
    "3c6444", "DLH4AB  ", "Germany", 1713700800, 1713700802,
    11.5819, 48.1351, 11582.4, False, 261.0, 45.0, 1.0,
    None, 11880.0, None, False, 0,
]

# Null-position record (airborne but position unknown). OpenSky emits these.
_NULL_POSITION = [
    "3c6445", None, "Germany", 1713700800, 1713700802,
    None, None, None, False, None, None, None,
    None, None, None, False, 0,
]


def _make_opensky_response(states: list[list[Any]]) -> dict[str, Any]:
    return {"time": 1713700810, "states": states}


# --------------------------------------------------------------------------- #
# Fake HTTP response object                                                   #
# --------------------------------------------------------------------------- #

class _FakeResponse:
    """Lookalike for requests.Response, without the dependency."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = text

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# --------------------------------------------------------------------------- #
# StateVector parsing                                                         #
# --------------------------------------------------------------------------- #

class TestStateVectorParsing:
    def test_from_array_fills_all_fields(self):
        s = StateVector.from_array(_SAS_OVER_STOCKHOLM)
        assert s.icao24 == "4ac9f1"
        assert s.callsign == "SAS821"  # trailing spaces stripped
        assert s.origin_country == "Sweden"
        assert s.latitude == pytest.approx(59.3293)
        assert s.longitude == pytest.approx(18.0637)
        assert s.velocity == pytest.approx(245.8)
        assert s.on_ground is False
        assert s.spi is False

    def test_from_array_handles_null_fields(self):
        s = StateVector.from_array(_NULL_POSITION)
        assert s.icao24 == "3c6445"
        assert s.callsign is None
        assert s.latitude is None
        assert s.longitude is None
        assert s.has_position() is False

    def test_from_array_rejects_short_tuples(self):
        with pytest.raises(ValueError, match="≥17 fields"):
            StateVector.from_array(["abc123", "ABC"])

    def test_is_in_bbox_baltic(self):
        stockholm = StateVector.from_array(_SAS_OVER_STOCKHOLM)
        gotland = StateVector.from_array(_SAS_OVER_GOTLAND)
        munich = StateVector.from_array(_LH_OVER_MUNICH)
        assert stockholm.is_in_bbox(BBOX_BALTIC)
        assert gotland.is_in_bbox(BBOX_BALTIC)
        assert not munich.is_in_bbox(BBOX_BALTIC)

    def test_is_in_bbox_gotland_narrow(self):
        stockholm = StateVector.from_array(_SAS_OVER_STOCKHOLM)
        gotland = StateVector.from_array(_SAS_OVER_GOTLAND)
        # Stockholm is outside the narrow Gotland box; Gotland is inside.
        assert not stockholm.is_in_bbox(BBOX_GOTLAND_NARROW)
        assert gotland.is_in_bbox(BBOX_GOTLAND_NARROW)

    def test_null_position_never_in_bbox(self):
        s = StateVector.from_array(_NULL_POSITION)
        assert not s.is_in_bbox(BBOX_BALTIC)


# --------------------------------------------------------------------------- #
# TokenManager                                                                #
# --------------------------------------------------------------------------- #

class TestTokenManager:
    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
        monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
        tm = TokenManager()
        assert not tm.have_credentials()
        with pytest.raises(RuntimeError, match="credentials not configured"):
            tm.get_token()

    def test_initial_fetch_caches_token(self):
        calls = []

        def fake_post(url, data, timeout):
            calls.append(url)
            return _FakeResponse(
                status_code=200,
                json_data={"access_token": "TOK1", "expires_in": 1800},
            )

        tm = TokenManager(
            client_id="cid", client_secret="sec", http_post=fake_post
        )
        assert tm.get_token() == "TOK1"
        assert tm.get_token() == "TOK1"  # second call: cached
        assert len(calls) == 1

    def test_refresh_near_expiry(self):
        calls: list[str] = []

        def fake_post(url, data, timeout):
            calls.append(url)
            return _FakeResponse(
                status_code=200,
                json_data={"access_token": f"TOK{len(calls)}", "expires_in": 20},
            )

        tm = TokenManager(
            client_id="cid", client_secret="sec", http_post=fake_post
        )
        t1 = tm.get_token()
        # Simulate clock advancing past the refresh margin.
        tm._expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        t2 = tm.get_token()
        assert t1 == "TOK1"
        assert t2 == "TOK2"
        assert len(calls) == 2


# --------------------------------------------------------------------------- #
# OpenSkyAdapter — live mode with mocked HTTP                                 #
# --------------------------------------------------------------------------- #

class TestLiveFetch:
    def _make_adapter_with_response(
        self, response: _FakeResponse, *, authenticated: bool = False
    ) -> OpenSkyAdapter:
        captured: dict[str, Any] = {}

        def fake_get(url, headers, timeout):
            captured["url"] = url
            captured["headers"] = headers
            return response

        # Build an adapter; provide a token-manager that has credentials only
        # if `authenticated` is True so the Authorization header is exercised.
        if authenticated:
            def fake_post(url, data, timeout):
                return _FakeResponse(
                    status_code=200,
                    json_data={"access_token": "BEARER_XYZ", "expires_in": 1800},
                )
            tm = TokenManager(
                client_id="c", client_secret="s", http_post=fake_post
            )
        else:
            tm = TokenManager(client_id=None, client_secret=None)

        adapter = OpenSkyAdapter(
            mode="live", bbox=BBOX_BALTIC, token_manager=tm, http_get=fake_get
        )
        adapter._captured = captured  # type: ignore[attr-defined]
        return adapter

    def test_fetch_parses_states_and_filters_bbox(self):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([
                _SAS_OVER_STOCKHOLM,
                _SAS_OVER_GOTLAND,
                _LH_OVER_MUNICH,   # outside Baltic — should be filtered
                _NULL_POSITION,    # null position — should be filtered
            ]),
            headers={"X-Rate-Limit-Remaining": "3950"},
        )
        adapter = self._make_adapter_with_response(response)
        snap = adapter.fetch()
        assert snap.raw_count == 4
        assert snap.in_bbox_count == 2
        icaos = {s.icao24 for s in snap.states}
        assert icaos == {"4ac9f1", "4ac9f2"}
        assert snap.rate_limit_remaining == 3950
        assert snap.source == "opensky_live"

    def test_fetch_sends_bounding_box_parameters(self):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([]),
        )
        adapter = self._make_adapter_with_response(response)
        adapter.fetch()
        url = adapter._captured["url"]  # type: ignore[attr-defined]
        assert "lamin=54.0" in url
        assert "lomin=10.0" in url
        assert "lamax=60.5" in url
        assert "lomax=24.0" in url

    def test_fetch_authenticated_sends_bearer(self):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([]),
        )
        adapter = self._make_adapter_with_response(response, authenticated=True)
        adapter.fetch()
        headers = adapter._captured["headers"]  # type: ignore[attr-defined]
        assert headers.get("Authorization") == "Bearer BEARER_XYZ"

    def test_fetch_unauthenticated_omits_bearer(self):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([]),
        )
        adapter = self._make_adapter_with_response(response, authenticated=False)
        adapter.fetch()
        headers = adapter._captured["headers"]  # type: ignore[attr-defined]
        assert "Authorization" not in headers

    def test_fetch_401_raises(self):
        response = _FakeResponse(status_code=401, text="Unauthorized")
        adapter = self._make_adapter_with_response(response)
        with pytest.raises(RuntimeError, match="401 Unauthorized"):
            adapter.fetch()

    def test_fetch_429_raises(self):
        response = _FakeResponse(status_code=429, text="Too Many Requests")
        adapter = self._make_adapter_with_response(response)
        with pytest.raises(RuntimeError, match="429 Too Many Requests"):
            adapter.fetch()

    def test_fetch_refuses_below_credit_floor(self):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([]),
            headers={"X-Rate-Limit-Remaining": "50"},
        )
        adapter = self._make_adapter_with_response(response)
        adapter.min_credits_floor = 200
        # First call succeeds but records "50 remaining".
        adapter.fetch()
        # Second call refuses.
        with pytest.raises(RuntimeError, match="rate-limit floor hit"):
            adapter.fetch()


# --------------------------------------------------------------------------- #
# OpenSkyAdapter — offline mode                                               #
# --------------------------------------------------------------------------- #

class TestOfflineReplay:
    def test_offline_mode_refuses_fetch(self):
        adapter = OpenSkyAdapter(mode="offline")
        with pytest.raises(RuntimeError, match="requires mode='live'"):
            adapter.fetch()

    def test_replay_yields_cached_snapshots_in_order(self, tmp_path: Path):
        # Write three snapshots by hand into the expected layout.
        day_dir = tmp_path / "2026-04-20"
        day_dir.mkdir()
        for hhmmss in ("120000", "120500", "121000"):
            snap = StateSnapshot(
                fetch_time_utc=f"2026-04-20T{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]}+00:00",
                source_time_unix=1713614400 + int(hhmmss),
                bbox=BBOX_BALTIC,
                authenticated=True,
                states=[StateVector.from_array(_SAS_OVER_STOCKHOLM)],
                raw_count=1, in_bbox_count=1,
                source="opensky_live",
            )
            (day_dir / f"{hhmmss}.json").write_text(
                json.dumps(snap.as_jsonable()), encoding="utf-8",
            )

        adapter = OpenSkyAdapter(mode="offline")
        snaps = list(adapter.replay(tmp_path))
        assert len(snaps) == 3
        # Sorted chronologically by filename.
        assert [s.fetch_time_utc for s in snaps] == [
            "2026-04-20T12:00:00+00:00",
            "2026-04-20T12:05:00+00:00",
            "2026-04-20T12:10:00+00:00",
        ]
        # source is rewritten for replayed snapshots.
        assert all(s.source == "offline_cache" for s in snaps)

    def test_replay_skips_corrupt_files(self, tmp_path: Path):
        day_dir = tmp_path / "2026-04-20"
        day_dir.mkdir()
        # Good file.
        good_snap = StateSnapshot(
            fetch_time_utc="2026-04-20T12:00:00+00:00",
            source_time_unix=1713614400,
            bbox=BBOX_BALTIC, authenticated=False,
            states=[], raw_count=0, in_bbox_count=0,
            source="opensky_live",
        )
        (day_dir / "120000.json").write_text(
            json.dumps(good_snap.as_jsonable()), encoding="utf-8",
        )
        # Corrupt file.
        (day_dir / "120500.json").write_text("{not valid json", encoding="utf-8")

        adapter = OpenSkyAdapter(mode="offline")
        snaps = list(adapter.replay(tmp_path))
        assert len(snaps) == 1  # corrupt file silently skipped

    def test_replay_missing_dir_returns_empty(self, tmp_path: Path):
        adapter = OpenSkyAdapter(mode="offline")
        snaps = list(adapter.replay(tmp_path / "nonexistent"))
        assert snaps == []


# --------------------------------------------------------------------------- #
# Roundtrip — live fetch, write to cache, replay, verify identity             #
# --------------------------------------------------------------------------- #

class TestLiveToCacheToReplay:
    def test_fetch_writes_cache_and_is_replayable(self, tmp_path: Path):
        response = _FakeResponse(
            status_code=200,
            json_data=_make_opensky_response([
                _SAS_OVER_STOCKHOLM,
                _SAS_OVER_GOTLAND,
            ]),
            headers={"X-Rate-Limit-Remaining": "3999"},
        )

        def fake_get(url, headers, timeout):
            return response

        adapter = OpenSkyAdapter(
            mode="live",
            bbox=BBOX_BALTIC,
            token_manager=TokenManager(client_id=None, client_secret=None),
            http_get=fake_get,
        )
        snap = adapter.fetch(cache_dir=tmp_path)
        assert snap.cache_path is not None
        assert Path(snap.cache_path).exists()
        assert snap.in_bbox_count == 2

        # Now replay from the same directory.
        replayer = OpenSkyAdapter(mode="offline")
        replayed = list(replayer.replay(tmp_path))
        assert len(replayed) == 1
        rsnap = replayed[0]
        assert rsnap.in_bbox_count == 2
        # States survive round-trip byte-for-byte.
        original_icaos = sorted(s.icao24 for s in snap.states)
        replayed_icaos = sorted(s.icao24 for s in rsnap.states)
        assert original_icaos == replayed_icaos
