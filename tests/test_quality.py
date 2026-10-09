from __future__ import annotations

from datetime import date

import pyarrow as pa
import pytest

from conduit import bronze, quality, silver
from tests.conftest import make_row


def _table(data_dir, rows) -> pa.Table:
    bronze.ingest(rows, data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    return silver.build(data_dir)


def _good(n, start=1000):
    return [make_row(start + i) for i in range(n)]


def test_clean_data_passes(data_dir):
    report = quality.run(_table(data_dir, _good(20)))
    assert report.passed and report.failed == 0 and report.total == 20
    assert report.good.num_rows == 20 and report.quarantine.num_rows == 0


@pytest.mark.parametrize(
    ("bad_row", "rule"),
    [
        (make_row(None), "non_null_keys"),
        (make_row(1, created=None), "non_null_keys"),
        (make_row(1, borough="Unspecified"), "valid_borough"),
        (make_row(1, borough=""), "valid_borough"),
        (make_row(1, closed="2024-02-01T10:00:00.000"), "closed_not_before_created"),
        (make_row(1, latitude="0", longitude="0"), "latlon_in_nyc_bbox"),
        (make_row(1, latitude="41.9", longitude="-73.9"), "latlon_in_nyc_bbox"),
        (make_row(1, latitude="40.7", longitude="-80.0"), "latlon_in_nyc_bbox"),
    ],
)
def test_each_rule_quarantines_its_row(data_dir, bad_row, rule):
    table = _table(data_dir, [bad_row, *_good(99)])
    report = quality.run(table)
    assert report.quarantine.num_rows == 1
    assert report.good.num_rows == 99
    assert rule in report.quarantine.column("failed_rules").to_pylist()[0].split(",")
    assert report.rule_failures[rule] == 1
    assert "failed_rules" not in report.good.column_names


def test_missing_coordinates_are_allowed(data_dir):
    rows = [make_row(1, latitude=None, longitude=None), *_good(9)]
    report = quality.run(_table(data_dir, rows))
    assert report.failed == 0


def test_one_row_can_break_several_rules(data_dir):
    rows = [make_row(1, borough="Unspecified", latitude="0", longitude="0"), *_good(9)]
    report = quality.run(_table(data_dir, rows))
    assert report.failed == 1
    rules = set(report.quarantine.column("failed_rules").to_pylist()[0].split(","))
    assert rules == {"valid_borough", "latlon_in_nyc_bbox"}


def test_threshold_is_strictly_more_than_five_percent(data_dir):
    at_limit = quality.run(_table(data_dir, [*_good(95), *[make_row(None)] * 5]))
    assert at_limit.fail_rate == pytest.approx(0.05)
    assert at_limit.passed


def test_above_threshold_fails_the_run(tmp_path):
    rows = [*_good(94, 5000), *[make_row(9000 + i, borough="Unspecified") for i in range(6)]]
    report = quality.run(_table(tmp_path / "d", rows))
    assert report.fail_rate == pytest.approx(0.06)
    assert not report.passed


def test_threshold_is_configurable(data_dir):
    report = quality.run(_table(data_dir, [make_row(1, borough="Unspecified"), *_good(9)]), threshold=0.2)
    assert report.passed
    assert not quality.run(
        _table(data_dir, [make_row(1, borough="Unspecified"), *_good(9)]), threshold=0.05
    ).passed


def test_empty_table_passes():
    empty = silver_schema_empty()
    report = quality.run(empty)
    assert report.total == 0 and report.passed


def silver_schema_empty() -> pa.Table:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        bronze.ingest([make_row(1)], data, ingest_date=date(2024, 3, 5), source="fixture")
        return silver.build(data).slice(0, 0)
