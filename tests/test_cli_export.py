"""v2.40 — `pixcull export` actually exports.

It had been `raise typer.Exit(code=1)  # TODO(V0.5)` since V0.5: no
message, no output, exit 1 — while the package blurb advertised
"XMP/IPTC export, Lightroom & Capture One ready" and the README headlined
Lr/C1 直通.  Export existed, but only inside the web workspace, so the
CLI path v2.31 opened for pip users dead-ended on a silent stub.
"""

import csv
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pixcull.cli import app
from pixcull.io.xmp import decision_to_xmp, read_xmp

REPO = Path(__file__).resolve().parent.parent
runner = CliRunner()

_DECISIONS = ["keep", "keep", "maybe", "cull", "keep"]


@pytest.fixture
def run_dir(tmp_path):
    """A finished run: real JPEGs + a scores.csv pointing at them."""
    from PIL import Image
    import numpy as np

    photos = tmp_path / "photos"
    photos.mkdir()
    out = tmp_path / "run" / "output"
    out.mkdir(parents=True)

    header = ("path,filename,scene,decision,score_final\n")
    lines = []
    for i, d in enumerate(_DECISIONS):
        p = photos / f"e{i}.jpg"
        a = np.zeros((64, 96, 3), np.uint8)
        a[:, :, i % 3] = 200
        Image.fromarray(a).save(p, quality=85)
        lines.append(f"{p},e{i}.jpg,landscape,{d},0.7\n")
    (out / "scores.csv").write_text(header + "".join(lines), encoding="utf-8")
    return out, photos


def test_export_writes_sidecars_next_to_the_originals(run_dir):
    out, photos = run_dir
    res = runner.invoke(app, ["export", str(out)])
    assert res.exit_code == 0, res.output
    for i in range(len(_DECISIONS)):
        assert (photos / f"e{i}.xmp").is_file(), "Lightroom looks here"


def test_exported_ratings_round_trip(run_dir):
    """A sidecar Lightroom can't read back is worthless."""
    out, photos = run_dir
    assert runner.invoke(app, ["export", str(out)]).exit_code == 0
    for i, d in enumerate(_DECISIONS):
        stars, label = decision_to_xmp(d)
        got = read_xmp(photos / f"e{i}.jpg")
        assert got.get("rating") == stars, f"e{i}: rating"
        assert got.get("color_label") == label, f"e{i}: colour label"


def test_collected_target_gathers_them_in_the_run(run_dir):
    out, photos = run_dir
    res = runner.invoke(app, ["export", str(out), "--target", "collected"])
    assert res.exit_code == 0, res.output
    assert sorted(p.name for p in (out / "xmp").glob("*.xmp")) == [
        f"e{i}.xmp" for i in range(5)]
    assert not list(photos.glob("*.xmp")), "should not have touched originals"


def test_csv_export(run_dir):
    out, _ = run_dir
    res = runner.invoke(app, ["export", str(out), "--format", "csv"])
    assert res.exit_code == 0, res.output
    rows = list(csv.DictReader((out / "ratings.csv").open(encoding="utf-8")))
    assert [r["decision"] for r in rows] == _DECISIONS
    assert rows[0]["rating"] == str(decision_to_xmp("keep")[0])
    assert rows[0]["color_label"] == decision_to_xmp("keep")[1]


def test_csv_export_honours_out(run_dir, tmp_path):
    out, _ = run_dir
    dest = tmp_path / "elsewhere" / "r.csv"
    res = runner.invoke(app, ["export", str(out), "-f", "csv", "-o", str(dest)])
    assert res.exit_code == 0 and dest.is_file()


def test_not_a_run_dir_explains_itself(tmp_path):
    res = runner.invoke(app, ["export", str(tmp_path)])
    assert res.exit_code == 2
    assert "scores.csv" in res.output


@pytest.mark.parametrize("args,expect", [
    (["--format", "json"], "format"),
    (["--target", "bogus"], "target"),
])
def test_bad_options_are_rejected_with_a_reason(run_dir, args, expect):
    out, _ = run_dir
    res = runner.invoke(app, ["export", str(out)] + args)
    assert res.exit_code == 2
    assert expect in res.output


def test_unreachable_originals_fail_loudly(run_dir, tmp_path):
    """An external drive being offline must not look like success."""
    out, photos = run_dir
    text = (out / "scores.csv").read_text(encoding="utf-8")
    (out / "scores.csv").write_text(
        text.replace(str(photos), str(tmp_path / "gone")), encoding="utf-8")
    res = runner.invoke(app, ["export", str(out)])
    assert res.exit_code == 1
    assert "nothing written" in res.output


def test_export_is_no_longer_a_stub():
    """Guard against the whole class: a command that exits non-zero with
    no output is indistinguishable from a broken install."""
    src = (REPO / "pixcull" / "cli.py").read_text("utf-8")
    assert "TODO(V0.5)" not in src, "export stub is back"


def test_no_cli_command_is_a_silent_stub():
    """Every registered command must at least produce help; a bare
    `raise typer.Exit(code=1)` body is how export hid for so long."""
    import ast
    tree = ast.parse((REPO / "pixcull" / "cli.py").read_text("utf-8"))
    offenders = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        body = [s for s in fn.body if not isinstance(s, ast.Expr)]
        if len(body) != 1:
            continue
        s = body[0]
        if (isinstance(s, ast.Raise) and isinstance(s.exc, ast.Call)
                and getattr(s.exc.func, "attr", "") == "Exit"):
            offenders.append(fn.name)
    assert not offenders, f"stub command(s) with no output: {offenders}"


def test_export_help_is_reachable_from_the_installed_entry_point():
    r = subprocess.run([sys.executable, "-m", "pixcull", "export", "--help"],
                       capture_output=True, text=True, timeout=180, cwd=REPO,
                       env={"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb",
                            "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0


# ── v2.40 — `pixcull bench` ────────────────────────────────────────────
#
# Also a silent `raise typer.Exit(1)` since V0.5. Found by the
# no-silent-stub guard above rather than by reading the file.

def test_bench_refuses_an_empty_folder(tmp_path):
    res = runner.invoke(app, ["bench", str(tmp_path)])
    assert res.exit_code == 2
    assert "no readable images" in res.output


def test_bench_does_not_index_its_scratch_sample_into_the_library():
    """Caught by running it: bench used to file its throwaway sample into
    the user's cross-run library, and since the scratch dir is deleted
    immediately after, every row became a permanently stale /library hit."""
    src = (REPO / "pixcull" / "cli.py").read_text("utf-8")
    body = src[src.index("def bench("):src.index("def video(")]
    assert "PIXCULL_NO_AUTO_INDEX" in body, (
        "bench no longer suppresses auto-index — it will pollute the "
        "user's library with throwaway rows")


def test_bench_restores_the_env_it_touched():
    src = (REPO / "pixcull" / "cli.py").read_text("utf-8")
    body = src[src.index("def bench("):src.index("def video(")]
    for var in ("PIXCULL_WORKERS", "PIXCULL_NO_AUTO_INDEX"):
        assert f'prev' in body and var in body
        assert f'os.environ.pop("{var}", None)' in body, (
            f"{var} is set but never restored — leaks into the rest of the "
            f"process")


def test_bench_workers_flag_is_actually_wired():
    """run_pipeline takes no `workers` argument; the pool reads
    PIXCULL_WORKERS. A flag that sets neither would be decoration."""
    src = (REPO / "pixcull" / "cli.py").read_text("utf-8")
    body = src[src.index("def bench("):src.index("def video(")]
    assert 'os.environ["PIXCULL_WORKERS"] = str(workers)' in body
    par = (REPO / "pixcull" / "pipeline" / "parallel.py").read_text("utf-8")
    assert "PIXCULL_WORKERS" in par, "the pool stopped reading this var"
