from __future__ import annotations

from click.testing import CliRunner
from PIL import Image

from conduit import cli


def test_run_fixture_offline(tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["run", "--source", "fixture", "--since", "2024-01-01", "--data-dir", str(tmp_path / "d")],
    )
    assert result.exit_code == 0, result.output
    assert "fetched" in result.output and "500" in result.output
    assert "quality gate: PASSED" in result.output


def test_second_run_reports_nothing_new(tmp_path):
    args = ["run", "--source", "fixture", "--data-dir", str(tmp_path / "d")]
    CliRunner().invoke(cli.main, args)
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code == 0
    assert "fetched          0" in result.output


def test_limit_above_cap_is_a_usage_error(tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["run", "--source", "fixture", "--limit", "50001", "--data-dir", str(tmp_path / "d")],
    )
    assert result.exit_code != 0


def test_report_writes_1600px_charts(tmp_path):
    d, media = tmp_path / "d", tmp_path / "media"
    CliRunner().invoke(cli.main, ["run", "--source", "fixture", "--data-dir", str(d)])
    result = CliRunner().invoke(cli.main, ["report", "--data-dir", str(d), "--out-dir", str(media)])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in media.glob("*.png"))
    assert names == [
        "hero.png",
        "quality_gate.png",
        "response_time_by_borough.png",
        "sla_breach_rate.png",
        "top_complaints_by_zip.png",
    ]
    for p in media.glob("*.png"):
        with Image.open(p) as img:
            assert img.width == 1600
            assert not img.getexif()
    assert "| layer" in result.output  # markdown run summary


def test_report_before_any_run_is_a_clean_error(tmp_path):
    result = CliRunner().invoke(cli.main, ["report", "--data-dir", str(tmp_path / "nope")])
    assert result.exit_code != 0
    assert "conduit run" in result.output
