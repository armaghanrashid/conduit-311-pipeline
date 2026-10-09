"""Silver: typed, standardised, de-duplicated requests built from every bronze partition.

Silver is a pure function of bronze, so it is recomputed in full each run. That keeps
"latest version wins" correct no matter what order batches arrived in, and makes re-runs idempotent.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from conduit import sqlfiles

SILVER_REL = Path("silver") / "silver_311" / "silver_311.parquet"
QUARANTINE_REL = Path("quarantine") / "quarantine_311" / "quarantine_311.parquet"


class NoBronzeData(RuntimeError):
    """There is nothing in bronze to build silver from."""


def build(data_dir: Path) -> pa.Table:
    glob = data_dir / "bronze" / "ingest_date=*" / "*.parquet"
    if not list((data_dir / "bronze").glob("ingest_date=*/*.parquet")):
        raise NoBronzeData(f"no bronze files under {data_dir / 'bronze'}; run an extract first")
    con = duckdb.connect()
    con.execute(
        "CREATE VIEW bronze AS SELECT * FROM "
        f"read_parquet('{sqlfiles.quote(glob)}', hive_partitioning = true)"
    )
    return con.execute(sqlfiles.read("silver_311")).to_arrow_table()


def _write_atomic(table: pa.Table, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, target)


def write_quarantine(quarantine: pa.Table, data_dir: Path) -> Path:
    target = data_dir / QUARANTINE_REL
    _write_atomic(quarantine, target)
    return target


def publish(good: pa.Table, quarantine: pa.Table, data_dir: Path) -> Path:
    """Write the rows that passed the gate to silver and the rest to quarantine."""
    write_quarantine(quarantine, data_dir)
    target = data_dir / SILVER_REL
    _write_atomic(good, target)
    return target
