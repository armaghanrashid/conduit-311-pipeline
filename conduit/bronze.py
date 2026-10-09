"""Bronze: immutable raw landing (JSON lines) plus a Parquet copy partitioned by ingest_date.

Everything stays a string here. The batch id is a hash of the batch contents, so ingesting
the same rows twice overwrites the same files instead of piling up copies.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from conduit.extract import COLUMNS


@dataclass(frozen=True)
class BronzeBatch:
    batch_id: str | None
    rows: int
    path: Path | None


def _quote(path: Path) -> str:
    return str(path).replace("'", "''")


def ingest(rows: Iterable[dict], data_dir: Path, *, ingest_date: date, source: str) -> BronzeBatch:
    landing_dir = data_dir / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    tmp = landing_dir / f".incoming-{os.getpid()}.jsonl"
    digest, count = hashlib.sha256(), 0
    with tmp.open("w") as fh:
        for row in rows:
            line = json.dumps({k: row[k] for k in COLUMNS if k in row}, sort_keys=True)
            fh.write(line + "\n")
            digest.update(line.encode())
            count += 1
    if count == 0:
        tmp.unlink()
        return BronzeBatch(None, 0, None)

    batch_id = digest.hexdigest()[:16]
    landing = landing_dir / f"{batch_id}.jsonl"
    os.replace(tmp, landing)

    partition = data_dir / "bronze" / f"ingest_date={ingest_date.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    target = partition / f"{batch_id}.parquet"
    staging = partition / f".{batch_id}.parquet.tmp"
    columns = ", ".join(f"'{c}': 'VARCHAR'" for c in COLUMNS)
    ingested_at = datetime.now(UTC).replace(tzinfo=None)
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT *, ? AS _batch_id, ? AS _source, ?::TIMESTAMP AS _ingested_at
            FROM read_json('{_quote(landing)}', format = 'newline_delimited', columns = {{{columns}}})
        ) TO '{_quote(staging)}' (FORMAT parquet, COMPRESSION zstd)
        """,
        [batch_id, source, ingested_at],
    )
    con.close()
    os.replace(staging, target)
    return BronzeBatch(batch_id, count, target)
