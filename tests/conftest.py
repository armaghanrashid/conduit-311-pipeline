from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conduit import extract

EPOCH = datetime(2024, 1, 1)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def fixture_rows() -> list[dict]:
    return list(extract.fetch_fixture(EPOCH, 50_000))


def make_row(key, *, created="2024-03-01T10:00:00.000", closed=None, updated=None, **overrides):
    """A raw (all-string) bronze-shaped record, like the API returns."""
    row = {
        "unique_key": None if key is None else str(key),
        "created_date": created,
        "agency": "NYPD",
        "complaint_type": "Illegal Parking",
        "descriptor": "Blocked Hydrant",
        "status": "Closed" if closed else "Open",
        "incident_zip": "10001",
        "borough": "MANHATTAN",
        "latitude": "40.75",
        "longitude": "-73.99",
        "resolution_action_updated_date": updated or closed or created,
    }
    if closed:
        row["closed_date"] = closed
    row.update(overrides)
    return {k: v for k, v in row.items() if v is not None}
