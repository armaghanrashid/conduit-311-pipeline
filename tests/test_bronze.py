from __future__ import annotations

import json
from datetime import date

import duckdb

from conduit import bronze
from tests.conftest import make_row


def test_ingest_writes_landing_jsonl_and_partitioned_parquet(data_dir):
    rows = [make_row(1), make_row(2, closed="2024-03-01T12:00:00.000")]
    batch = bronze.ingest(rows, data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    assert batch.rows == 2
    landing = data_dir / "landing" / f"{batch.batch_id}.jsonl"
    assert [json.loads(line)["unique_key"] for line in landing.read_text().splitlines()] == [
        "1",
        "2",
    ]
    parquet = data_dir / "bronze" / "ingest_date=2024-03-05" / f"{batch.batch_id}.parquet"
    assert parquet.exists()


def test_bronze_keeps_raw_strings_and_adds_lineage_columns(data_dir):
    bronze.ingest([make_row(7)], data_dir, ingest_date=date(2024, 3, 5), source="api")
    con = duckdb.connect()
    desc = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{data_dir}/bronze/*/*.parquet', hive_partitioning=true)"
    ).fetchall()
    types = {name: typ for name, typ, *_ in desc}
    assert types["unique_key"] == "VARCHAR" and types["latitude"] == "VARCHAR"
    assert {"_batch_id", "_source", "_ingested_at", "ingest_date"} <= set(types)
    row = con.execute(
        f"SELECT unique_key, _source, closed_date FROM read_parquet('{data_dir}/bronze/*/*.parquet')"
    ).fetchone()
    assert row == ("7", "api", None)


def test_reingesting_the_same_batch_is_idempotent(data_dir):
    rows = [make_row(1), make_row(2)]
    first = bronze.ingest(rows, data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    second = bronze.ingest(rows, data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    assert first.batch_id == second.batch_id
    assert len(list((data_dir / "bronze").rglob("*.parquet"))) == 1
    assert len(list((data_dir / "landing").glob("*.jsonl"))) == 1


def test_different_content_gets_a_different_batch(data_dir):
    a = bronze.ingest([make_row(1)], data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    b = bronze.ingest([make_row(2)], data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    assert a.batch_id != b.batch_id
    assert len(list((data_dir / "bronze").rglob("*.parquet"))) == 2


def test_empty_input_writes_nothing(data_dir):
    batch = bronze.ingest([], data_dir, ingest_date=date(2024, 3, 5), source="fixture")
    assert batch.rows == 0 and batch.batch_id is None
    assert not (data_dir / "bronze").exists()
