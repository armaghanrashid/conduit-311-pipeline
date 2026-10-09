from __future__ import annotations

from datetime import datetime

import duckdb
import pytest

from conduit import extract, pipeline, state
from tests.conftest import make_row

EPOCH = datetime(2024, 1, 1)


def _silver(data_dir):
    path = data_dir / "silver" / "silver_311" / "silver_311.parquet"
    return duckdb.sql(f"SELECT * FROM read_parquet('{path}')")


def _run(data_dir, **kw):
    return pipeline.run(source="fixture", since=EPOCH, limit=50_000, data_dir=data_dir, **kw)


def test_fixture_run_counts(data_dir):
    result = _run(data_dir)
    assert result.fetched == 500
    assert result.silver_rows == 474  # 500 minus 26 superseded versions
    assert result.quarantined == 8
    assert result.good_rows == 466
    assert result.fail_rate == pytest.approx(8 / 474)
    assert result.rule_failures == {
        "non_null_keys": 2,
        "valid_borough": 2,
        "closed_not_before_created": 2,
        "latlon_in_nyc_bbox": 2,
    }
    assert _silver(data_dir).aggregate("count(*)").fetchone()[0] == 466
    assert set(result.gold_rows) == {
        "response_time_by_borough_month",
        "top_complaints_by_zip",
        "sla_breach_rate",
    }


def test_superseded_versions_are_resolved_to_the_closed_one(data_dir):
    _run(data_dir)
    open_after = _silver(data_dir).filter("status = 'Open'").aggregate("count(*)").fetchone()[0]
    assert open_after == 40 - 26  # the first 26 open requests were closed by later versions


def test_incremental_rerun_adds_zero_rows(data_dir):
    first = _run(data_dir)
    keys_before = _silver(data_dir).aggregate("count(*), count(DISTINCT unique_key)").fetchone()
    second = _run(data_dir)
    keys_after = _silver(data_dir).aggregate("count(*), count(DISTINCT unique_key)").fetchone()
    assert second.fetched == 0
    assert keys_after == keys_before == (466, 466)
    assert second.gold_rows == first.gold_rows
    assert len(list((data_dir / "bronze").rglob("*.parquet"))) == 1


def test_rerun_with_lookback_refetches_but_adds_no_duplicates(data_dir):
    _run(data_dir)
    again = _run(data_dir, lookback_days=400)
    assert again.fetched == 500
    count, distinct = _silver(data_dir).aggregate("count(*), count(DISTINCT unique_key)").fetchone()
    assert count == distinct == 466
    assert len(list((data_dir / "bronze").rglob("*.parquet"))) == 1  # same content, same batch file


def test_watermark_is_persisted(data_dir):
    _run(data_dir)
    s = state.load(data_dir / "state.json")
    newest = max(datetime.fromisoformat(r["created_date"]) for r in extract.fetch_fixture(EPOCH, 50_000))
    assert s.watermark == newest
    assert s.last_run["fetched"] == 500


def test_late_update_is_picked_up_by_lookback(data_dir):
    base = [make_row(1, created="2024-03-01T10:00:00.000")]
    pipeline.run(source="custom", since=EPOCH, limit=100, data_dir=data_dir, fetcher=lambda *a: iter(base))
    update = [make_row(1, created="2024-03-01T10:00:00.000", closed="2024-03-03T10:00:00.000")]
    result = pipeline.run(
        source="custom",
        since=EPOCH,
        limit=100,
        data_dir=data_dir,
        lookback_days=30,
        fetcher=lambda since, until, limit: iter(update) if since < datetime(2024, 3, 1, 10) else iter(()),
    )
    assert result.fetched == 1
    rows = _silver(data_dir).fetchall()
    assert len(rows) == 1
    assert _silver(data_dir).filter("status = 'Closed'").aggregate("count(*)").fetchone()[0] == 1


def test_gate_failure_blocks_publish_and_keeps_watermark(data_dir):
    rows = [make_row(i) for i in range(1, 91)] + [make_row(100 + i, borough="N/A") for i in range(10)]
    with pytest.raises(pipeline.QualityGateError) as err:
        pipeline.run(
            source="custom",
            since=EPOCH,
            limit=1000,
            data_dir=data_dir,
            fetcher=lambda *a: iter(rows),
        )
    assert err.value.report.fail_rate == pytest.approx(0.10)
    assert not (data_dir / "silver").exists()
    assert not (data_dir / "gold").exists()
    assert (data_dir / "quarantine" / "quarantine_311" / "quarantine_311.parquet").exists()
    assert state.load(data_dir / "state.json").watermark is None


def test_failed_run_can_be_retried_after_the_data_is_fixed(data_dir):
    bad = [make_row(i) for i in range(1, 91)] + [make_row(100 + i, borough="N/A") for i in range(10)]
    with pytest.raises(pipeline.QualityGateError):
        pipeline.run(
            source="custom",
            since=EPOCH,
            limit=1000,
            data_dir=data_dir,
            fetcher=lambda *a: iter(bad),
        )
    # the upstream corrects the 10 rows; same keys, newer version
    fixed = [make_row(100 + i, updated="2024-03-05T00:00:00.000") for i in range(10)]
    result = pipeline.run(
        source="custom", since=EPOCH, limit=1000, data_dir=data_dir, fetcher=lambda *a: iter(fixed)
    )
    assert result.quarantined == 0 and result.good_rows == 100
