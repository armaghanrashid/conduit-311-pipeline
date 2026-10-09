from __future__ import annotations

from datetime import date

from conduit import bronze, silver
from tests.conftest import make_row

D1, D2 = date(2024, 3, 5), date(2024, 3, 6)


def _build(data_dir, *batches):
    for rows, day in batches:
        bronze.ingest(rows, data_dir, ingest_date=day, source="fixture")
    return silver.build(data_dir).to_pylist()


def test_dedup_keeps_the_latest_version(data_dir):
    old = make_row(1, updated="2024-03-01T10:00:00.000")
    new = make_row(1, closed="2024-03-02T10:00:00.000")
    rows = _build(data_dir, ([old], D1), ([new], D2))
    assert len(rows) == 1
    assert rows[0]["status"] == "Closed"
    assert rows[0]["response_hours"] == 24.0


def test_dedup_does_not_depend_on_arrival_order(data_dir):
    old = make_row(1, updated="2024-03-01T10:00:00.000")
    new = make_row(1, closed="2024-03-02T10:00:00.000")
    # the stale version arrives *after* the fresh one
    rows = _build(data_dir, ([new], D1), ([old], D2))
    assert len(rows) == 1 and rows[0]["status"] == "Closed"


def test_tie_on_source_timestamp_falls_back_to_latest_ingest(data_dir):
    a = make_row(1, status="Assigned")
    b = make_row(1, status="Started")
    rows = _build(data_dir, ([a], D1), ([b], D2))
    assert [r["status"] for r in rows] == ["Started"]


def test_types_and_standardisation(data_dir):
    messy = make_row(
        5,
        borough=" Staten Is ",
        incident_zip="11201-1234",
        latitude="40.6",
        longitude="-74.1",
        closed="2024-03-01T12:30:00.000",
    )
    row = _build(data_dir, ([messy], D1))[0]
    assert row["unique_key"] == 5
    assert row["borough"] == "STATEN ISLAND"
    assert row["incident_zip"] == "11201"
    assert row["latitude"] == 40.6
    assert row["response_hours"] == 2.5
    assert str(row["created_at"]) == "2024-03-01 10:00:00"


def test_borough_variants(data_dir):
    rows = _build(
        data_dir,
        (
            [
                make_row(1, borough="brooklyn"),
                make_row(2, borough="Unspecified"),
                make_row(3, borough=""),
            ],
            D1,
        ),
    )
    by_key = {r["unique_key"]: r["borough"] for r in rows}
    assert by_key == {1: "BROOKLYN", 2: "UNSPECIFIED", 3: None}


def test_open_tickets_have_no_response_time(data_dir):
    row = _build(data_dir, ([make_row(1)], D1))[0]
    assert row["closed_at"] is None and row["response_hours"] is None


def test_rows_without_a_key_survive_for_quarantine(data_dir):
    rows = _build(data_dir, ([make_row(None), make_row(None, complaint_type="Other")], D1))
    assert len(rows) == 2 and all(r["unique_key"] is None for r in rows)


def test_unparseable_key_becomes_null(data_dir):
    rows = _build(data_dir, ([make_row("abc")], D1))
    assert rows[0]["unique_key"] is None


def test_build_without_bronze_data_is_an_error(data_dir):
    import pytest

    with pytest.raises(silver.NoBronzeData):
        silver.build(data_dir)
