"""Extract: pull 311 service requests from the NYC Open Data (Socrata SODA) API, or a local fixture.

The API needs no key. Requests are paged, throttled and retried with exponential backoff so a
run stays polite to a free public service. Rows come back exactly as the API sends them
(all values strings, absent fields omitted); typing is the silver layer's job.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import requests

from conduit import __version__

API_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
PAGE_SIZE = 10_000
MAX_ROWS = 50_000  # politeness cap for one run
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample.csv"

COLUMNS = (
    "unique_key",
    "created_date",
    "closed_date",
    "resolution_action_updated_date",
    "agency",
    "complaint_type",
    "descriptor",
    "status",
    "incident_zip",
    "borough",
    "latitude",
    "longitude",
)


class ExtractError(RuntimeError):
    """The API could not be read (after retries, or on a non-retryable error)."""


def _ts(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _where(since: datetime, until: datetime | None) -> str:
    clause = f"created_date > '{_ts(since)}'"
    if until is not None:
        clause += f" AND created_date <= '{_ts(until)}'"
    return clause


def _get_page(
    session: requests.Session,
    params: dict,
    *,
    max_attempts: int,
    backoff: float,
    sleep: Callable[[float], None],
) -> list[dict]:
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(API_URL, params=params, timeout=60)
            if response.status_code in RETRY_STATUS:
                raise requests.ConnectionError(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == max_attempts:
                raise ExtractError(f"giving up after {max_attempts} attempts: {exc}") from exc
            sleep(backoff * 2 ** (attempt - 1))
        except requests.RequestException as exc:
            raise ExtractError(f"request failed: {exc}") from exc
    raise AssertionError("unreachable")  # pragma: no cover


def fetch(
    since: datetime,
    limit: int,
    *,
    until: datetime | None = None,
    page_size: int = PAGE_SIZE,
    pause: float = 0.25,
    max_attempts: int = 5,
    backoff: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    session: requests.Session | None = None,
) -> Iterator[dict]:
    """Yield up to `limit` requests created after `since` (and up to `until`), oldest first."""
    if limit > MAX_ROWS:
        raise ValueError(f"limit {limit} exceeds the {MAX_ROWS} row politeness cap")
    session = session or requests.Session()
    session.headers["User-Agent"] = f"conduit-311-pipeline/{__version__}"
    remaining, offset = limit, 0
    while remaining > 0:
        want = min(page_size, remaining)
        params = {
            "$select": ",".join(COLUMNS),
            "$where": _where(since, until),
            "$order": "created_date ASC, unique_key ASC",
            "$limit": want,
            "$offset": offset,
        }
        page = _get_page(session, params, max_attempts=max_attempts, backoff=backoff, sleep=sleep)
        yield from page
        offset += len(page)
        remaining -= len(page)
        if len(page) < want:
            break
        if remaining > 0:
            sleep(pause)


def fetch_fixture(
    since: datetime,
    limit: int,
    *,
    until: datetime | None = None,
    path: Path = FIXTURE_PATH,
) -> Iterator[dict]:
    """Same contract as `fetch`, served from the synthetic CSV so the pipeline runs offline."""
    with path.open(newline="") as fh:
        rows = [{k: v for k, v in row.items() if v != ""} for row in csv.DictReader(fh)]
    rows = [
        r
        for r in rows
        if datetime.fromisoformat(r["created_date"]) > since
        and (until is None or datetime.fromisoformat(r["created_date"]) <= until)
    ]
    rows.sort(
        key=lambda r: (
            r["created_date"],
            r.get("unique_key", ""),
            r["resolution_action_updated_date"],
        )
    )
    yield from rows[:limit]
