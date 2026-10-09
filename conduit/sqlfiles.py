"""Locate and read the DuckDB transform files in `sql/`."""

from __future__ import annotations

from pathlib import Path

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def read(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text().strip().rstrip(";")


def quote(path: Path) -> str:
    """Escape a filesystem path for use inside a single-quoted SQL string."""
    return str(path).replace("'", "''")
