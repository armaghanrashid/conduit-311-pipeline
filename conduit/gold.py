"""Gold: analytics tables aggregated from silver by the SQL files in `sql/gold_*.sql`."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from conduit import sqlfiles
from conduit.silver import SILVER_REL

GOLD_TABLES = ("response_time_by_borough_month", "top_complaints_by_zip", "sla_breach_rate")
DEFAULT_SLA_HOURS = 72


def gold_path(data_dir: Path, name: str) -> Path:
    return data_dir / "gold" / name / f"{name}.parquet"


def build(data_dir: Path, *, sla_hours: int = DEFAULT_SLA_HOURS) -> dict[str, int]:
    """Rebuild every gold table from silver. Returns {table: row_count}."""
    silver = data_dir / SILVER_REL
    if not silver.exists():
        raise FileNotFoundError(f"{silver} does not exist; run the pipeline first")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW silver AS SELECT * FROM read_parquet('{sqlfiles.quote(silver)}')")
    con.execute(f"SET VARIABLE sla_hours = {int(sla_hours)}")
    counts: dict[str, int] = {}
    for name in GOLD_TABLES:
        target = gold_path(data_dir, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.tmp")
        con.execute(
            f"COPY ({sqlfiles.read('gold_' + name)}) TO '{sqlfiles.quote(staging)}' "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
        os.replace(staging, target)
        counts[name] = con.execute(
            f"SELECT count(*) FROM read_parquet('{sqlfiles.quote(target)}')"
        ).fetchone()[0]
    return counts
