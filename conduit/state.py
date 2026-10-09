"""Run state: a high-water mark on `created_date` so incremental runs only fetch new requests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class State:
    watermark: datetime | None = None
    last_run: dict = field(default_factory=dict)

    def advance(self, seen: datetime | None) -> State:
        """Return a state whose watermark is the max of the old one and `seen` (never moves back)."""
        candidates = [w for w in (self.watermark, seen) if w is not None]
        return replace(self, watermark=max(candidates) if candidates else None)


def load(path: Path) -> State:
    if not path.exists():
        return State()
    raw = json.loads(path.read_text())
    wm = raw.get("watermark")
    return State(datetime.fromisoformat(wm) if wm else None, raw.get("last_run", {}))


def save(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "watermark": state.watermark.isoformat() if state.watermark else None,
        "last_run": state.last_run,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def effective_since(state: State, since: datetime, *, lookback_days: int) -> datetime:
    """Where the next extract starts: the watermark minus a lookback, but never before `since`.

    The lookback re-pulls recent requests so later updates (e.g. a ticket closing) are seen;
    silver's latest-wins dedup absorbs the overlap.
    """
    if state.watermark is None:
        return since
    return max(since, state.watermark - timedelta(days=lookback_days))
