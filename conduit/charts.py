"""Charts and the markdown run summary, both computed from the files a run leaves in data/."""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from PIL import Image  # noqa: E402

from conduit import gold, quality, state  # noqa: E402
from conduit.silver import QUARANTINE_REL, SILVER_REL  # noqa: E402

# Dark surface and the first five categorical hues of a palette validated for dark backgrounds
# (lightness band, chroma floor, colour-blind separation and 3:1 contrast all pass).
SURFACE = "#1a1a19"
PANEL = "#222221"
INK = "#ffffff"
INK_2 = "#c3c2b7"
INK_3 = "#8d8c84"
GRID = "#34342f"
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]
BOROUGHS = list(quality.BOROUGHS)
BOROUGH_COLOUR = dict(zip(BOROUGHS, SERIES, strict=True))
BAD = "#e66767"
GOOD = "#199e70"
WIDTH_IN, DPI = 16, 100  # 1600 px wide

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "text.color": INK,
        "axes.labelcolor": INK_2,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "axes.edgecolor": GRID,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "legend.frameon": False,
    }
)


# --------------------------------------------------------------------------- data access


def _q(sql: str) -> list[tuple]:
    return duckdb.sql(sql).fetchall()


def _gold(data_dir: Path, name: str) -> str:
    return f"read_parquet('{gold.gold_path(data_dir, name)}')"


def collect_stats(data_dir: Path) -> dict:
    """Row counts and quality numbers, read back from the stored layers."""
    bronze_glob = data_dir / "bronze" / "ingest_date=*" / "*.parquet"
    bronze_rows, bronze_batches, bronze_keys = _q(
        f"SELECT count(*), count(DISTINCT _batch_id), count(DISTINCT unique_key) "
        f"FROM read_parquet('{bronze_glob}')"
    )[0]
    silver_path, quarantine_path = data_dir / SILVER_REL, data_dir / QUARANTINE_REL
    silver_rows, first, last, months = _q(
        f"SELECT count(*), min(created_at), max(created_at), "
        f"count(DISTINCT date_trunc('month', created_at)) FROM read_parquet('{silver_path}')"
    )[0]
    failed_rules = [r[0] for r in _q(f"SELECT failed_rules FROM read_parquet('{quarantine_path}')")]
    rules = Counter({name: 0 for name in quality.RULES})
    for tags in failed_rules:
        rules.update(tags.split(","))
    quarantined = len(failed_rules)
    staged = silver_rows + quarantined
    last_run = state.load(data_dir / "state.json").last_run
    synthetic = last_run.get("source") == "fixture"
    return {
        "source_label": (
            "synthetic fixture (tests/fixtures/sample.csv)"
            if synthetic
            else "NYC Open Data, 311 Service Requests (erm2-nwe9)"
        ),
        "bronze_rows": bronze_rows,
        "bronze_batches": bronze_batches,
        "bronze_keys": bronze_keys,
        "silver_rows": silver_rows,
        "quarantined": quarantined,
        "staged_rows": staged,
        "fail_rate": quarantined / staged if staged else 0.0,
        "threshold": last_run.get("threshold", quality.THRESHOLD),
        "rules": dict(rules),
        "first": first,
        "last": last,
        "months": months,
        "gold_rows": {
            name: _q(f"SELECT count(*) FROM {_gold(data_dir, name)}")[0][0] for name in gold.GOLD_TABLES
        },
        "sla_hours": _q(f"SELECT max(sla_hours) FROM {_gold(data_dir, 'sla_breach_rate')}")[0][0],
    }


def markdown_summary(stats: dict) -> str:
    rows = [
        ("bronze", f"raw rows in {stats['bronze_batches']} batch file(s)", stats["bronze_rows"]),
        ("bronze", "distinct unique_key", stats["bronze_keys"]),
        ("silver", "silver_311 (published, latest version per key)", stats["silver_rows"]),
        ("quarantine", "quarantine_311 (failed a quality rule)", stats["quarantined"]),
        *(("gold", name, n) for name, n in stats["gold_rows"].items()),
    ]
    width = max(len(r[1]) for r in rows)
    out = [
        f"| {'layer':<10} | {'table':<{width}} | {'rows':>7} |",
        f"|{'-' * 12}|{'-' * (width + 2)}|{'-' * 9}|",
    ]
    out += [f"| {layer:<10} | {name:<{width}} | {n:>7,} |" for layer, name, n in rows]
    rules = ", ".join(f"{k}: {v}" for k, v in stats["rules"].items())
    out += [
        "",
        f"- created_at range: {stats['first']:%Y-%m-%d} to {stats['last']:%Y-%m-%d} "
        f"({stats['months']} calendar months)",
        f"- quality gate: {stats['quarantined']:,} of {stats['staged_rows']:,} de-duplicated rows "
        f"quarantined = {stats['fail_rate']:.2%} (fails above {stats['threshold']:.0%})",
        f"- rows failing each rule: {rules}",
        f"- SLA threshold used for gold: {stats['sla_hours']} hours",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- drawing helpers


def _new_figure(height_in: float) -> plt.Figure:
    return plt.figure(figsize=(WIDTH_IN, height_in), dpi=DPI)


def _title(fig: plt.Figure, title: str, subtitle: str) -> None:
    h = fig.get_figheight()
    fig.text(0.04, 1 - 0.40 / h, title, fontsize=21, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 1 - 0.95 / h, subtitle, fontsize=12.5, color=INK_2, va="top")


def _footer(fig: plt.Figure, stats: dict) -> None:
    text = (
        f"Source: {stats['source_label']}   |   "
        f"{stats['silver_rows']:,} published rows, {stats['first']:%Y-%m-%d} to {stats['last']:%Y-%m-%d}"
    )
    fig.text(0.04, 0.02, text, fontsize=10, color=INK_3, va="bottom")


def _save(fig: plt.Figure, path: Path) -> Path:
    """Render at exactly 1600 px wide and re-save through PIL so no metadata survives."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI)
    plt.close(fig)
    buf.seek(0)
    with Image.open(buf) as img:
        clean = Image.frombytes(img.mode, img.size, img.tobytes())
        clean.save(path, format="PNG", optimize=True)
    return path


def _style_axes(ax) -> None:
    ax.tick_params(length=0)
    ax.grid(axis="x", visible=False)


def _months(rows: list[tuple]) -> list[str]:
    return sorted({f"{r[0]:%Y-%m}" for r in rows})


# --------------------------------------------------------------------------- panels


def _draw_response_times(ax, data_dir: Path, *, compact: bool = False) -> None:
    rows = _q(
        "SELECT month, borough, median_response_hours "
        f"FROM {_gold(data_dir, 'response_time_by_borough_month')}"
    )
    months = _months(rows)
    x = {m: i for i, m in enumerate(months)}
    for borough in BOROUGHS:
        pts = sorted((x[f"{m:%Y-%m}"], v) for m, b, v in rows if b == borough)
        if not pts:
            continue
        xs, ys = zip(*pts, strict=True)
        colour = BOROUGH_COLOUR[borough]
        ax.plot(
            xs,
            ys,
            color=colour,
            linewidth=2,
            marker="o",
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            label=borough.title(),
            zorder=3,
        )
    ax.set_xticks(range(len(months)), months, rotation=0 if len(months) < 9 else 45)
    ax.set_xlim(-0.3, len(months) - 0.7)
    peak = max(v for _, _, v in rows)
    ax.set_ylim(0, peak * 1.2)
    ax.set_ylabel("median hours to close")
    _style_axes(ax)
    ax.legend(
        loc="upper left",
        ncols=5,
        fontsize=10.5 if compact else 12,
        labelcolor=INK_2,
        handlelength=1.4,
        columnspacing=1.2,
    )


def _breach_by_agency(data_dir: Path, top: int = 8) -> list[tuple]:
    return _q(
        f"""SELECT agency, sum(breached_tickets) * 1.0 / sum(tickets) AS rate, sum(tickets) AS n
            FROM {_gold(data_dir, "sla_breach_rate")}
            GROUP BY agency ORDER BY n DESC LIMIT {top}"""
    )


def _draw_breach_bars(ax, data_dir: Path, sla_hours: int) -> None:
    rows = sorted(_breach_by_agency(data_dir), key=lambda r: r[1])
    names = [r[0] for r in rows]
    ax.barh(names, [r[1] for r in rows], color=SERIES[0], height=0.55)
    for i, (_, rate, n) in enumerate(rows):
        ax.text(rate + 0.012, i, f"{rate:.0%}  of {n:,}", va="center", fontsize=10.5, color=INK_2)
    ax.set_xlim(0, max(r[1] for r in rows) * 1.35 + 0.02)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel(f"requests past a {sla_hours}-hour SLA")
    ax.grid(axis="y", visible=False)
    ax.tick_params(length=0)


# --------------------------------------------------------------------------- charts


def chart_response_time(data_dir: Path, out: Path, stats: dict) -> Path:
    fig = _new_figure(8.5)
    _title(
        fig,
        "Median time to close a 311 request, by borough and month",
        "Median hours from creation to closure, closed requests only",
    )
    ax = fig.add_axes([0.07, 0.12, 0.89, 0.68])
    _draw_response_times(ax, data_dir)
    _footer(fig, stats)
    return _save(fig, out)


def chart_sla(data_dir: Path, out: Path, stats: dict) -> Path:
    rows = _q(f"SELECT agency, month, breach_rate, tickets FROM {_gold(data_dir, 'sla_breach_rate')}")
    agencies = [r[0] for r in _breach_by_agency(data_dir, top=10)]
    months = _months([(r[1],) for r in rows])
    grid = {(a, f"{m:%Y-%m}"): rate for a, m, rate, _ in rows}
    fig = _new_figure(8.5)
    _title(
        fig,
        f"SLA breach rate by agency and month ({stats['sla_hours']}-hour threshold)",
        "Share of requests closed late, or still open past the threshold; 10 busiest agencies",
    )
    ax = fig.add_axes([0.07, 0.12, 0.89, 0.68])
    ax.grid(False)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "seq", [PANEL, "#1f4f8f", SERIES[0], "#9cc4f5"]
    )
    data = [[grid.get((a, m), float("nan")) for m in months] for a in agencies]
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(months)), months)
    ax.set_yticks(range(len(agencies)), agencies)
    ax.tick_params(length=0)
    for i, a in enumerate(agencies):
        for j, m in enumerate(months):
            v = grid.get((a, m))
            if v is not None:
                ax.text(
                    j,
                    i,
                    f"{v:.0%}",
                    ha="center",
                    va="center",
                    fontsize=11,
                    color=INK if v < 0.75 else SURFACE,
                )
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(months))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(agencies))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.015)
    cbar.ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(colors=INK_2, length=0)
    _footer(fig, stats)
    return _save(fig, out)


def chart_top_complaints(data_dir: Path, out: Path, stats: dict) -> Path:
    zips = [
        r[0]
        for r in _q(
            f"SELECT incident_zip FROM {_gold(data_dir, 'top_complaints_by_zip')} "
            "GROUP BY 1 ORDER BY sum(tickets) DESC, 1 LIMIT 6"
        )
    ]
    fig = _new_figure(9.5)
    _title(
        fig,
        "What each busy ZIP code complains about",
        "Top five complaint types in the six ZIP codes with the most requests",
    )
    for i, z in enumerate(zips):
        ax = fig.add_axes([0.04 + (i % 3) * 0.325 + 0.115, 0.55 - (i // 3) * 0.40 + 0.0, 0.19, 0.28])
        rows = _q(
            f"SELECT complaint_type, tickets, share_of_zip FROM {_gold(data_dir, 'top_complaints_by_zip')} "
            f"WHERE incident_zip = '{z}' ORDER BY rank DESC"
        )
        ax.barh([r[0] for r in rows], [r[1] for r in rows], color=SERIES[0], height=0.6)
        top = max(r[1] for r in rows)
        for j, (_, n, share) in enumerate(rows):
            ax.text(n + top * 0.02, j, f"{n:,} ({share:.0%})", va="center", fontsize=9.5, color=INK_2)
        ax.set_xlim(0, top * 1.55)
        ax.set_title(f"ZIP {z}", loc="left", fontsize=13, fontweight="bold", color=INK)
        ax.tick_params(length=0, labelsize=9.5)
        ax.set_xticks([])
        ax.grid(False)
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_color(GRID)
    _footer(fig, stats)
    return _save(fig, out)


def chart_quality(out: Path, stats: dict) -> Path:
    fig = _new_figure(6.2)
    _title(
        fig,
        "Quality gate: what was quarantined, and why",
        f"{stats['quarantined']:,} of {stats['staged_rows']:,} de-duplicated rows failed "
        f"({stats['fail_rate']:.2%}); the run fails above {stats['threshold']:.0%}",
    )
    rate = stats["fail_rate"]
    ax = fig.add_axes([0.07, 0.56, 0.89, 0.17])
    top = max(stats["threshold"] * 1.25, rate * 1.25, 0.01)
    ax.barh([0], [rate], color=BAD, height=0.5)
    ax.axvline(stats["threshold"], color=INK, linewidth=2)
    ax.text(
        stats["threshold"],
        0.62,
        f"  gate: {stats['threshold']:.0%}",
        color=INK,
        fontsize=12,
        va="bottom",
    )
    ax.text(rate + top * 0.01, 0, f" {rate:.2%} quarantined", color=INK_2, va="center", fontsize=12)
    ax.set_xlim(0, top)
    ax.set_ylim(-0.5, 1.0)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(axis="y", visible=False)
    ax.tick_params(length=0)

    ax2 = fig.add_axes([0.22, 0.12, 0.74, 0.30])
    names = list(stats["rules"])[::-1]
    counts = [stats["rules"][n] for n in names]
    ax2.barh(names, counts, color=SERIES[1], height=0.55)
    peak = max(counts) if counts and max(counts) else 1
    for i, c in enumerate(counts):
        ax2.text(c + peak * 0.015, i, f"{c:,}", va="center", color=INK_2, fontsize=11)
    ax2.set_xlim(0, peak * 1.12)
    ax2.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax2.set_xlabel("rows failing the rule (a row can fail several)")
    ax2.grid(axis="y", visible=False)
    ax2.tick_params(length=0)
    fig.text(
        0.04,
        0.02,
        f"Source: {stats['source_label']}",
        fontsize=10,
        color=INK_3,
    )
    return _save(fig, out)


def _tile(fig, x: float, label: str, value: str, note: str, accent: str) -> None:
    ax = fig.add_axes([x, 0.70, 0.174, 0.13])
    ax.set_axis_off()
    ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0,rounding_size=0.06",
            transform=ax.transAxes,
            facecolor=PANEL,
            edgecolor="none",
        )
    )
    ax.add_patch(plt.Rectangle((0, 0.12), 0.012, 0.76, transform=ax.transAxes, facecolor=accent))
    ax.text(0.07, 0.78, label, fontsize=11, color=INK_2, transform=ax.transAxes, va="center")
    ax.text(
        0.07,
        0.42,
        value,
        fontsize=24,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
        va="center",
    )
    ax.text(0.07, 0.13, note, fontsize=9.5, color=INK_3, transform=ax.transAxes, va="center")


def chart_hero(data_dir: Path, out: Path, stats: dict) -> Path:
    fig = _new_figure(9)
    _title(
        fig,
        "conduit: NYC 311 batch pipeline",
        "extract  >  bronze (raw Parquet)  >  silver (typed, de-duplicated)  >  quality gate  >  gold (SQL)",
    )
    gate_ok = stats["fail_rate"] <= stats["threshold"]
    tiles = [
        (
            "bronze rows",
            f"{stats['bronze_rows']:,}",
            f"{stats['bronze_batches']} batch file(s)",
            SERIES[1],
        ),
        ("silver rows", f"{stats['silver_rows']:,}", "latest version per key", SERIES[0]),
        (
            "quarantined",
            f"{stats['quarantined']:,}",
            f"{stats['fail_rate']:.2%} of staged rows",
            BAD,
        ),
        (
            "gold tables",
            str(len(stats["gold_rows"])),
            f"{sum(stats['gold_rows'].values()):,} rows total",
            SERIES[2],
        ),
        (
            "quality gate",
            "PASSED" if gate_ok else "FAILED",
            f"fails above {stats['threshold']:.0%}",
            GOOD if gate_ok else BAD,
        ),
    ]
    for i, t in enumerate(tiles):
        _tile(fig, 0.04 + i * 0.1865, *t)

    ax1 = fig.add_axes([0.07, 0.12, 0.50, 0.45])
    ax1.set_title("Median hours to close, by borough", loc="left", fontsize=13, fontweight="bold", pad=12)
    _draw_response_times(ax1, data_dir, compact=True)
    ax2 = fig.add_axes([0.70, 0.12, 0.26, 0.45])
    ax2.set_title(
        f"Past a {stats['sla_hours']}-hour SLA, by agency",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    _draw_breach_bars(ax2, data_dir, stats["sla_hours"])
    _footer(fig, stats)
    return _save(fig, out)


def render_all(data_dir: Path, out_dir: Path, stats: dict) -> list[Path]:
    return [
        chart_hero(data_dir, out_dir / "hero.png", stats),
        chart_response_time(data_dir, out_dir / "response_time_by_borough.png", stats),
        chart_sla(data_dir, out_dir / "sla_breach_rate.png", stats),
        chart_top_complaints(data_dir, out_dir / "top_complaints_by_zip.png", stats),
        chart_quality(out_dir / "quality_gate.png", stats),
    ]
