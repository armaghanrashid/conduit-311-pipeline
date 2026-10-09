from __future__ import annotations

from datetime import date

import duckdb
import pytest

from conduit import bronze, gold, quality, silver
from tests.conftest import make_row


def _make_silver(data_dir, rows):
    bronze.ingest(rows, data_dir, ingest_date=date(2024, 4, 1), source="fixture")
    report = quality.run(silver.build(data_dir))
    silver.publish(report.good, report.quarantine, data_dir)


def _read(data_dir, name):
    path = data_dir / "gold" / name / f"{name}.parquet"
    return duckdb.sql(f"SELECT * FROM read_parquet('{path}')").fetchall()


def _closed(key, hours, **kw):
    from datetime import datetime, timedelta

    created = datetime(2024, 3, 1, 0, 0)
    closed = created + timedelta(hours=hours)
    return make_row(
        key,
        created=created.isoformat(timespec="milliseconds"),
        closed=closed.isoformat(timespec="milliseconds"),
        **kw,
    )


def test_response_time_by_borough_month(data_dir):
    rows = [
        _closed(1, 2, borough="BRONX"),
        _closed(2, 4, borough="BRONX"),
        _closed(3, 6, borough="BRONX"),
        _closed(4, 10, borough="QUEENS"),
        make_row(5, borough="QUEENS"),  # still open: excluded
        make_row(6, created="2024-04-02T00:00:00.000", closed="2024-04-02T01:00:00.000"),
    ]
    _make_silver(data_dir, rows)
    counts = gold.build(data_dir)
    assert counts["response_time_by_borough_month"] == 3
    got = {(str(m), b): (n, med) for m, b, n, med, *_ in _read(data_dir, "response_time_by_borough_month")}
    assert got[("2024-03-01", "BRONX")] == (3, 4.0)
    assert got[("2024-03-01", "QUEENS")] == (1, 10.0)
    assert got[("2024-04-01", "MANHATTAN")] == (1, 1.0)


def test_top_complaints_by_zip_ranks_and_shares(data_dir):
    rows = (
        [make_row(i, complaint_type="Noise") for i in range(1, 5)]
        + [make_row(i, complaint_type="Parking") for i in range(5, 7)]
        + [make_row(7, complaint_type="Trees")]
        + [make_row(8, incident_zip="10002", complaint_type="Trees")]
    )
    _make_silver(data_dir, rows)
    gold.build(data_dir)
    got = _read(data_dir, "top_complaints_by_zip")
    by_zip = {z: [(r, c, n, s) for zz, r, c, n, s in got if zz == z] for z in {"10001", "10002"}}
    assert by_zip["10001"] == [
        (1, "Noise", 4, 0.5714),
        (2, "Parking", 2, 0.2857),
        (3, "Trees", 1, 0.1429),
    ]
    assert by_zip["10002"] == [(1, "Trees", 1, 1.0)]


def test_top_complaints_keeps_only_five_per_zip(data_dir):
    rows = [make_row(i, complaint_type=f"C{i}") for i in range(1, 9)]
    _make_silver(data_dir, rows)
    gold.build(data_dir)
    assert len(_read(data_dir, "top_complaints_by_zip")) == 5


def test_sla_breach_rate(data_dir):
    rows = [
        _closed(1, 10, agency="NYPD"),  # within 72h
        _closed(2, 100, agency="NYPD"),  # breached
        _closed(3, 100, agency="HPD"),  # breached
        make_row(4, agency="HPD", created="2024-03-01T00:00:00.000"),  # open > 72h at as-of: breached
        make_row(5, agency="HPD", created="2024-03-20T00:00:00.000", closed="2024-03-20T01:00:00.000"),
    ]
    _make_silver(data_dir, rows)
    gold.build(data_dir, sla_hours=72)
    got = {(a, str(m)): (t, b, r, h) for a, m, t, b, r, h in _read(data_dir, "sla_breach_rate")}
    assert got[("NYPD", "2024-03-01")] == (2, 1, 0.5, 72)
    assert got[("HPD", "2024-03-01")] == (3, 2, 0.6667, 72)


def test_sla_threshold_is_a_parameter(data_dir):
    _make_silver(data_dir, [_closed(1, 10), _closed(2, 30)])
    gold.build(data_dir, sla_hours=24)
    (_, _, tickets, breached, rate, hours) = _read(data_dir, "sla_breach_rate")[0]
    assert (tickets, breached, rate, hours) == (2, 1, 0.5, 24)


def test_gold_is_idempotent(data_dir):
    _make_silver(data_dir, [_closed(1, 10), _closed(2, 30)])
    first = gold.build(data_dir)
    snapshot = {n: _read(data_dir, n) for n in first}
    assert gold.build(data_dir) == first
    assert {n: _read(data_dir, n) for n in first} == snapshot


def test_gold_requires_silver(data_dir):
    with pytest.raises(FileNotFoundError):
        gold.build(data_dir)
