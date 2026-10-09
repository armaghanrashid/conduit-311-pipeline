"""Orchestration: extract -> bronze -> silver (staging) -> quality gate -> silver -> gold -> state.

The watermark moves only after every stage has succeeded, so a failed run is simply retried
from the same point. Every stage writes deterministically (content-hashed bronze batches,
full recompute for silver and gold), which is what makes re-running safe.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from conduit import bronze, extract, gold, quality, silver, state

Fetcher = Callable[[datetime, datetime | None, int], Iterable[dict]]


class QualityGateError(RuntimeError):
    def __init__(self, report: quality.Report):
        self.report = report
        super().__init__(
            f"quality gate failed: {report.failed}/{report.total} rows "
            f"({report.fail_rate:.2%}) broke a rule; threshold is {report.threshold:.2%}"
        )


@dataclass(frozen=True)
class RunResult:
    source: str
    since: str
    fetched: int
    batch_id: str | None
    silver_rows: int
    good_rows: int
    quarantined: int
    fail_rate: float
    threshold: float
    rule_failures: dict[str, int]
    gold_rows: dict[str, int] = field(default_factory=dict)
    watermark: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _default_fetcher(source: str) -> Fetcher:
    if source == "fixture":
        return lambda since, until, limit: extract.fetch_fixture(since, limit, until=until)
    if source == "api":
        return lambda since, until, limit: extract.fetch(since, limit, until=until)
    raise ValueError(f"unknown source {source!r}")


def _track_newest(rows: Iterable[dict], seen: list[datetime]) -> Iterator[dict]:
    """Pass rows through while remembering the newest created_date (the next watermark)."""
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_date"])
        except (KeyError, ValueError):
            created = None
        if created is not None and (not seen or created > seen[0]):
            seen[:] = [created]
        yield row


def run(
    *,
    source: str,
    since: datetime,
    limit: int,
    data_dir: Path,
    until: datetime | None = None,
    threshold: float = quality.THRESHOLD,
    lookback_days: int = 0,
    sla_hours: int = gold.DEFAULT_SLA_HOURS,
    ingest_date: date | None = None,
    fetcher: Fetcher | None = None,
) -> RunResult:
    fetcher = fetcher or _default_fetcher(source)
    state_path = data_dir / "state.json"
    current = state.load(state_path)
    start = state.effective_since(current, since, lookback_days=lookback_days)

    newest: list[datetime] = []
    rows = _track_newest(fetcher(start, until, limit), newest)
    batch = bronze.ingest(rows, data_dir, ingest_date=ingest_date or date.today(), source=source)

    staged = silver.build(data_dir)
    report = quality.run(staged, threshold)
    if not report.passed:
        silver.write_quarantine(report.quarantine, data_dir)  # keep the evidence, publish nothing
        raise QualityGateError(report)

    silver.publish(report.good, report.quarantine, data_dir)
    gold_rows = gold.build(data_dir, sla_hours=sla_hours)

    new_watermark = current.advance(newest[0] if newest else None).watermark
    result = RunResult(
        source=source,
        since=start.isoformat(timespec="seconds"),
        fetched=batch.rows,
        batch_id=batch.batch_id,
        silver_rows=report.total,
        good_rows=report.good.num_rows,
        quarantined=report.quarantine.num_rows,
        fail_rate=report.fail_rate,
        threshold=report.threshold,
        rule_failures=report.rule_failures,
        gold_rows=gold_rows,
        watermark=new_watermark.isoformat() if new_watermark else None,
    )
    state.save(state_path, state.State(new_watermark, result.to_dict()))
    return result
