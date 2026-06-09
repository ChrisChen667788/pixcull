"""v2.5-P1 — tests for the client-ready contact-sheet PDF export."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pixcull.report.contact_sheet import (  # noqa: E402
    contact_sheet_from_run,
    render_contact_sheet,
)


def _swatch(path: Path, rgb=(200, 170, 120)):
    Image.new("RGB", (240, 160), rgb).save(path)


def _is_pdf(p: Path) -> bool:
    b = p.read_bytes()
    return b[:5] == b"%PDF-" and b"%%EOF" in b[-1024:]


def test_render_paginates(tmp_path):
    items = []
    for i in range(23):                       # 4×5 = 20 per page → 2 pages
        p = tmp_path / f"i{i}.jpg"
        _swatch(p, (i * 9 % 256, 150, 120))
        items.append((p, f"i{i}.jpg  0.8{i % 10}"))
    out = tmp_path / "sheet.pdf"
    n = render_contact_sheet(items, out, title="Selects", cols=4, rows_per_page=5)
    assert n == 2
    assert _is_pdf(out)
    assert out.stat().st_size > 2000


def test_render_empty_is_one_page(tmp_path):
    out = tmp_path / "empty.pdf"
    assert render_contact_sheet([], out) == 1
    assert _is_pdf(out)


def test_render_missing_image_graceful(tmp_path):
    out = tmp_path / "miss.pdf"
    # nonexistent path → placeholder cell, no exception
    n = render_contact_sheet([(tmp_path / "nope.jpg", "missing")], out)
    assert n == 1 and _is_pdf(out)


def test_from_run_filters_by_decision(tmp_path):
    run = tmp_path / "run"
    (run / "thumbs").mkdir(parents=True)
    for i in range(6):
        _swatch(run / "thumbs" / f"f{i}.jpg")
    with open(run / "scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "decision", "score_final"])
        for i in range(6):
            w.writerow([f"f{i}.jpg", "keep" if i < 4 else "cull", 0.7 + i * 0.01])
    out = run / "gallery.pdf"
    n_pages, n_photos = contact_sheet_from_run(run, out, decision="keep")
    assert n_photos == 4 and n_pages == 1 and _is_pdf(out)
    # decision=all picks up everything
    _, n_all = contact_sheet_from_run(run, run / "all.pdf", decision="all")
    assert n_all == 6


def test_from_run_reads_output_subdir(tmp_path):
    run = tmp_path / "run2"
    (run / "output" / "thumbs").mkdir(parents=True)
    _swatch(run / "output" / "thumbs" / "a.jpg")
    with open(run / "output" / "scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "decision", "score_final"])
        w.writerow(["a.jpg", "keep", 0.91])
    n_pages, n_photos = contact_sheet_from_run(run, run / "g.pdf")
    assert n_photos == 1 and _is_pdf(run / "g.pdf")


def test_from_run_missing_csv_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        contact_sheet_from_run(tmp_path / "nope", tmp_path / "x.pdf")


def test_cli_contact_sheet(tmp_path):
    from typer.testing import CliRunner
    import pixcull.cli as cli
    run = tmp_path / "r"
    (run / "thumbs").mkdir(parents=True)
    _swatch(run / "thumbs" / "p.jpg")
    with open(run / "scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "decision", "score_final"])
        w.writerow(["p.jpg", "keep", 0.88])
    out = tmp_path / "cli.pdf"
    res = CliRunner().invoke(
        cli.app, ["contact-sheet", str(run), "-o", str(out), "-d", "keep"])
    assert res.exit_code == 0, res.output
    assert _is_pdf(out)
