from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from conduit import extract


def _page(start, n):
    return [
        {"unique_key": str(i), "created_date": "2024-02-01T00:00:00.000"} for i in range(start, start + n)
    ]


@responses.activate
def test_fetch_pages_with_limit_offset_and_where():
    responses.add(responses.GET, extract.API_URL, json=_page(0, 2))
    responses.add(responses.GET, extract.API_URL, json=_page(2, 1))
    rows = list(extract.fetch(datetime(2024, 1, 1), 3, page_size=2, pause=0, sleep=lambda _: None))
    assert [r["unique_key"] for r in rows] == ["0", "1", "2"]
    q0, q1 = (parse_qs(urlparse(c.request.url).query) for c in responses.calls)
    assert q0["$limit"] == ["2"] and q0["$offset"] == ["0"]
    assert q1["$limit"] == ["1"] and q1["$offset"] == ["2"]
    assert q0["$where"] == ["created_date > '2024-01-01T00:00:00.000'"]
    assert q0["$order"] == ["created_date ASC, unique_key ASC"]
    assert "X-App-Token" not in responses.calls[0].request.headers


@responses.activate
def test_fetch_stops_on_short_page():
    responses.add(responses.GET, extract.API_URL, json=_page(0, 1))
    rows = list(extract.fetch(datetime(2024, 1, 1), 100, page_size=10, pause=0))
    assert len(rows) == 1
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_upper_bound_is_added_to_where():
    responses.add(responses.GET, extract.API_URL, json=[])
    list(extract.fetch(datetime(2024, 1, 1), 10, until=datetime(2024, 2, 1), pause=0))
    where = parse_qs(urlparse(responses.calls[0].request.url).query)["$where"][0]
    assert where.endswith("AND created_date <= '2024-02-01T00:00:00.000'")


@responses.activate
def test_fetch_retries_with_exponential_backoff():
    responses.add(responses.GET, extract.API_URL, status=503)
    responses.add(responses.GET, extract.API_URL, status=429)
    responses.add(responses.GET, extract.API_URL, json=_page(0, 1))
    waits: list[float] = []
    rows = list(extract.fetch(datetime(2024, 1, 1), 5, pause=0, backoff=1.0, sleep=waits.append))
    assert len(rows) == 1
    assert waits == [1.0, 2.0]


@responses.activate
def test_fetch_gives_up_after_max_attempts():
    for _ in range(3):
        responses.add(responses.GET, extract.API_URL, status=500)
    with pytest.raises(extract.ExtractError):
        list(extract.fetch(datetime(2024, 1, 1), 5, max_attempts=3, pause=0, sleep=lambda _: None))
    assert len(responses.calls) == 3


@responses.activate
def test_client_errors_are_not_retried():
    responses.add(responses.GET, extract.API_URL, status=400)
    with pytest.raises(extract.ExtractError):
        list(extract.fetch(datetime(2024, 1, 1), 5, pause=0, sleep=lambda _: None))
    assert len(responses.calls) == 1


def test_limit_above_politeness_cap_is_rejected():
    with pytest.raises(ValueError):
        list(extract.fetch(datetime(2024, 1, 1), extract.MAX_ROWS + 1))


def test_fixture_source_filters_orders_and_limits():
    rows = list(extract.fetch_fixture(datetime(2024, 1, 1), 50_000))
    assert len(rows) == 500
    created = [r["created_date"] for r in rows]
    assert created == sorted(created)
    assert all("" not in r.values() for r in rows)  # empty CSV cells are dropped like the API does
    assert len(list(extract.fetch_fixture(datetime(2024, 1, 1), 10))) == 10
    cutoff = datetime.fromisoformat(created[250])
    later = list(extract.fetch_fixture(cutoff, 50_000))
    assert all(datetime.fromisoformat(r["created_date"]) > cutoff for r in later)
    assert 0 < len(later) < 500
