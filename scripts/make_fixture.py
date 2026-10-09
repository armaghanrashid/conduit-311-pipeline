"""Generate tests/fixtures/sample.csv: 500 synthetic 311-style rows, fully deterministic.

Composition (asserted by the test-suite):
  466 clean, unique requests
    6 of them have messy-but-fixable boroughs ("brooklyn", " Staten Is ") that silver standardises
   26 later versions of earlier open requests (same unique_key, now closed)
    8 genuinely bad rows (2 null keys, 2 bad boroughs, 2 closed-before-created, 2 off-map coordinates)
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from conduit.extract import COLUMNS

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample.csv"
FMT = "%Y-%m-%dT%H:%M:%S.000"

ZIPS = {
    "MANHATTAN": ["10001", "10002", "10003", "10016", "10025", "10027"],
    "BROOKLYN": ["11201", "11206", "11211", "11215", "11226"],
    "QUEENS": ["11101", "11354", "11368", "11373", "11432"],
    "BRONX": ["10451", "10453", "10457", "10460", "10467"],
    "STATEN ISLAND": ["10301", "10304", "10306", "10314"],
}
CENTRE = {
    "MANHATTAN": (40.78, -73.97),
    "BROOKLYN": (40.65, -73.95),
    "QUEENS": (40.72, -73.80),
    "BRONX": (40.85, -73.88),
    "STATEN ISLAND": (40.58, -74.15),
}
# (agency, complaint_type, descriptor, median hours to close)
COMPLAINTS = [
    ("NYPD", "Noise - Residential", "Loud Music/Party", 2.0),
    ("NYPD", "Illegal Parking", "Blocked Hydrant", 3.0),
    ("HPD", "HEAT/HOT WATER", "ENTIRE BUILDING", 70.0),
    ("HPD", "PLUMBING", "WATER LEAK", 90.0),
    ("DOT", "Street Condition", "Pothole", 120.0),
    ("DSNY", "Missed Collection", "Trash", 30.0),
    ("DEP", "Water System", "Hydrant Leaking", 20.0),
    ("DPR", "Damaged Tree", "Branch Cracked", 200.0),
    ("DOB", "General Construction", "Work Without Permit", 150.0),
]
BOROUGH_SPEED = {
    "MANHATTAN": 0.9,
    "BROOKLYN": 1.0,
    "QUEENS": 1.1,
    "BRONX": 1.3,
    "STATEN ISLAND": 1.2,
}

START = datetime(2024, 1, 1, 0, 5)
SPAN_SECONDS = 180 * 24 * 3600


def build() -> list[dict]:
    rng = random.Random(311)
    keys = rng.sample(range(59_000_000, 59_900_000), 480)
    rows: list[dict] = []

    def make(key, *, borough=None, open_=False):
        borough = borough or rng.choice(list(ZIPS))
        agency, complaint, descriptor, median = rng.choice(COMPLAINTS)
        created = START + timedelta(seconds=rng.randrange(SPAN_SECONDS))
        lat0, lon0 = CENTRE[borough]
        row = dict.fromkeys(COLUMNS, "")
        row.update(
            unique_key=str(key) if key is not None else "",
            created_date=created.strftime(FMT),
            agency=agency,
            complaint_type=complaint,
            descriptor=descriptor,
            status="Open" if open_ else "Closed",
            incident_zip=rng.choice(ZIPS[borough]),
            borough=borough,
        )
        if rng.random() > 0.03:
            row["latitude"] = f"{lat0 + rng.uniform(-0.04, 0.04):.6f}"
            row["longitude"] = f"{lon0 + rng.uniform(-0.04, 0.04):.6f}"
        hours = median * BOROUGH_SPEED[borough] * math.exp(rng.gauss(0, 0.8))
        closed = created + timedelta(seconds=int(hours * 3600))
        row["resolution_action_updated_date"] = created.strftime(FMT)
        if not open_:
            row["closed_date"] = closed.strftime(FMT)
            row["resolution_action_updated_date"] = closed.strftime(FMT)
        return row

    clean = []
    for i in range(466):
        clean.append(make(keys[i], open_=(i < 40)))
    rows.extend(clean)

    # Messy-but-fixable boroughs.
    messy = ["brooklyn", " Staten Is ", "QUEENS ", "bronx", "Manhattan", " staten island"]
    for row, text in zip(clean[100:106], messy, strict=True):
        row["borough"] = text

    # 26 later versions of earlier open requests: same key, now closed.
    for original in clean[:26]:
        updated = dict(original)
        created = datetime.strptime(original["created_date"], FMT)
        closed = created + timedelta(hours=rng.uniform(2, 400))
        updated.update(
            status="Closed",
            closed_date=closed.strftime(FMT),
            resolution_action_updated_date=closed.strftime(FMT),
        )
        rows.append(updated)

    # 8 bad rows.
    bad = [make(keys[466 + i]) for i in range(8)]
    bad[0]["unique_key"] = ""
    bad[1]["unique_key"] = ""
    bad[2]["borough"] = "Unspecified"
    bad[3]["borough"] = "N/A"
    for row in (bad[4], bad[5]):
        created = datetime.strptime(row["created_date"], FMT)
        row["closed_date"] = (created - timedelta(hours=5)).strftime(FMT)
        row["status"] = "Closed"
    bad[6]["latitude"], bad[6]["longitude"] = "0.000000", "0.000000"
    bad[7]["latitude"], bad[7]["longitude"] = "41.900000", "-73.900000"
    rows.extend(bad)
    assert len(rows) == 500
    return rows


def main() -> None:
    rows = build()
    with OUT.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT.name}")


if __name__ == "__main__":
    main()
