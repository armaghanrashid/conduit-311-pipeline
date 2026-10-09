from __future__ import annotations

import json
from datetime import datetime

from conduit import state


def test_missing_file_gives_empty_state(tmp_path):
    s = state.load(tmp_path / "state.json")
    assert s.watermark is None and s.last_run == {}


def test_round_trip(tmp_path):
    path = tmp_path / "state.json"
    s = state.State(watermark=datetime(2024, 5, 1, 12, 0, 1), last_run={"fetched": 3})
    state.save(path, s)
    again = state.load(path)
    assert again == s
    assert json.loads(path.read_text())["watermark"] == "2024-05-01T12:00:01"


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    state.save(tmp_path / "state.json", state.State(datetime(2024, 1, 1), {}))
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_advance_is_monotonic():
    s = state.State(datetime(2024, 5, 1), {})
    assert s.advance(datetime(2024, 4, 1)).watermark == datetime(2024, 5, 1)
    assert s.advance(datetime(2024, 6, 1)).watermark == datetime(2024, 6, 1)
    assert s.advance(None).watermark == datetime(2024, 5, 1)


def test_effective_since():
    since = datetime(2024, 1, 1)
    assert state.effective_since(state.State(), since, lookback_days=0) == since
    wm = state.State(datetime(2024, 3, 10), {})
    assert state.effective_since(wm, since, lookback_days=0) == datetime(2024, 3, 10)
    assert state.effective_since(wm, since, lookback_days=7) == datetime(2024, 3, 3)
    # the explicit --since can still move the start later than the watermark
    assert state.effective_since(wm, datetime(2024, 4, 1), lookback_days=7) == datetime(2024, 4, 1)
