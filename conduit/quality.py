"""Data-quality gate between silver-staging and silver.

Each rule is a SQL predicate that is TRUE for a *violating* row. Violating rows go to
quarantine (tagged with every rule they broke) and never reach silver or gold. If more than
`THRESHOLD` of the rows fail, the whole run fails instead of publishing a degraded dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pyarrow as pa

THRESHOLD = 0.05
BOROUGHS = ("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND")
# Generous bounding box around the five boroughs: lat_min, lat_max, lon_min, lon_max.
NYC_BBOX = (40.45, 40.95, -74.30, -73.65)

_BOROUGH_LIST = ", ".join(f"'{b}'" for b in BOROUGHS)
RULES: dict[str, str] = {
    "non_null_keys": "unique_key IS NULL OR created_at IS NULL",
    "valid_borough": f"borough IS NULL OR borough NOT IN ({_BOROUGH_LIST})",
    "closed_not_before_created": "closed_at IS NOT NULL AND closed_at < created_at",
    # Missing coordinates are tolerated (many requests have none); present ones must be on the map.
    "latlon_in_nyc_bbox": (
        "(latitude IS NOT NULL OR longitude IS NOT NULL) AND NOT coalesce("
        f"latitude BETWEEN {NYC_BBOX[0]} AND {NYC_BBOX[1]} "
        f"AND longitude BETWEEN {NYC_BBOX[2]} AND {NYC_BBOX[3]}, false)"
    ),
}


@dataclass(frozen=True)
class Report:
    total: int
    failed: int
    threshold: float
    rule_failures: dict[str, int]
    good: pa.Table
    quarantine: pa.Table

    @property
    def fail_rate(self) -> float:
        return self.failed / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        return self.fail_rate <= self.threshold


def run(table: pa.Table, threshold: float = THRESHOLD) -> Report:
    con = duckdb.connect()
    con.register("staged", table)
    tags = ", ".join(f"CASE WHEN {pred} THEN '{name}' END" for name, pred in RULES.items())
    con.execute(
        f"CREATE TEMP VIEW flagged AS SELECT *, "
        f"list_filter([{tags}], x -> x IS NOT NULL) AS _failed FROM staged"
    )
    columns = ", ".join(f'"{c}"' for c in table.column_names)
    good = con.execute(f"SELECT {columns} FROM flagged WHERE len(_failed) = 0").to_arrow_table()
    quarantine = con.execute(
        f"SELECT {columns}, array_to_string(_failed, ',') AS failed_rules FROM flagged WHERE len(_failed) > 0"
    ).to_arrow_table()
    counts = {
        name: con.execute(f"SELECT count(*) FROM staged WHERE {pred}").fetchone()[0]
        for name, pred in RULES.items()
    }
    return Report(
        total=table.num_rows,
        failed=quarantine.num_rows,
        threshold=threshold,
        rule_failures=counts,
        good=good,
        quarantine=quarantine,
    )
