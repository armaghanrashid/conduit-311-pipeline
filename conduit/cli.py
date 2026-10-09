"""Command line interface: `conduit run` and `conduit report`."""

from __future__ import annotations

from pathlib import Path

import click

from conduit import extract, gold, pipeline, quality, silver

DATE_FORMATS = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]
DATA_DIR = click.Path(file_okay=False, path_type=Path)


@click.group()
@click.version_option(package_name="conduit")
def main() -> None:
    """Batch ETL for NYC 311 service requests."""


@main.command()
@click.option("--source", type=click.Choice(["fixture", "api"]), default="fixture", show_default=True)
@click.option(
    "--since",
    type=click.DateTime(DATE_FORMATS),
    default="2024-01-01",
    show_default=True,
    help="Only requests created after this. A saved watermark can move it later.",
)
@click.option(
    "--until",
    type=click.DateTime(DATE_FORMATS),
    default=None,
    help="Only requests created up to this (inclusive).",
)
@click.option(
    "--limit",
    type=click.IntRange(1, extract.MAX_ROWS),
    default=extract.MAX_ROWS,
    show_default=True,
    help="Maximum rows to pull this run.",
)
@click.option("--data-dir", type=DATA_DIR, default=Path("data"), show_default=True)
@click.option(
    "--lookback-days",
    type=click.IntRange(0),
    default=0,
    show_default=True,
    help="Re-pull this many days before the watermark to catch late updates.",
)
@click.option(
    "--threshold",
    type=click.FloatRange(0, 1),
    default=quality.THRESHOLD,
    show_default=True,
    help="Fail the run if more than this share of rows breaks a quality rule.",
)
@click.option("--sla-hours", type=click.IntRange(1), default=gold.DEFAULT_SLA_HOURS, show_default=True)
def run(source, since, until, limit, data_dir, lookback_days, threshold, sla_hours) -> None:
    """Extract, load and transform one incremental batch."""
    try:
        result = pipeline.run(
            source=source,
            since=since,
            until=until,
            limit=limit,
            data_dir=data_dir,
            lookback_days=lookback_days,
            threshold=threshold,
            sla_hours=sla_hours,
        )
    except pipeline.QualityGateError as exc:
        rep = exc.report
        lines = [str(exc)] + [f"  {name:<28} {n}" for name, n in rep.rule_failures.items()]
        lines.append(f"  quarantined rows kept in {data_dir / silver.QUARANTINE_REL}; nothing published")
        raise click.ClickException("\n".join(lines)) from exc
    except (silver.NoBronzeData, extract.ExtractError) as exc:
        raise click.ClickException(str(exc)) from exc

    def line(label: str, value) -> None:
        click.echo(f"{label:<16} {value}")

    line("source", result.source)
    line("window start", result.since)
    line("fetched", f"{result.fetched:,}")
    line("silver rows", f"{result.silver_rows:,} (latest version per unique_key)")
    line(
        "quarantined",
        f"{result.quarantined:,} ({result.fail_rate:.2%} of {result.silver_rows:,}; "
        f"limit {result.threshold:.0%})",
    )
    line("published", f"{result.good_rows:,} rows to silver")
    for name, count in result.gold_rows.items():
        line("gold", f"{name}: {count:,} rows")
    line("watermark", result.watermark)
    click.echo("quality gate: PASSED")


@main.command()
@click.option("--data-dir", type=DATA_DIR, default=Path("data"), show_default=True)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("docs/media"),
    show_default=True,
)
def report(data_dir: Path, out_dir: Path) -> None:
    """Render charts from the gold tables and print a markdown run summary."""
    from conduit import charts

    if not gold.gold_path(data_dir, gold.GOLD_TABLES[0]).exists():
        raise click.ClickException(f"no gold tables in {data_dir}; run `conduit run` first")
    stats = charts.collect_stats(data_dir)
    for path in charts.render_all(data_dir, out_dir, stats):
        click.echo(f"wrote {path}", err=True)
    click.echo(charts.markdown_summary(stats))
