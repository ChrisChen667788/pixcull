import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

app = typer.Typer(help="PixCull — AI photo culling & scoring", no_args_is_help=True)
console = Console()


@app.command()
def scan(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder to scan recursively"),
) -> None:
    """List all supported images in a folder (dry run, no analysis)."""
    from pixcull.io.loader import list_images

    paths = list_images(folder)
    table = Table(title=f"Found {len(paths)} images under {folder}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Path")
    for i, p in enumerate(paths[:50], start=1):
        table.add_row(str(i), str(p.relative_to(folder)))
    if len(paths) > 50:
        table.caption = f"… and {len(paths) - 50} more"
    console.print(table)


@app.command()
def run(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Input folder"),
    output: Path = typer.Option(Path("./output"), "--output", "-o", help="Output folder"),
    scene: Optional[str] = typer.Option(
        None, "--scene", help="Force scene (portrait/wildlife/event/stilllife/landscape/street)"
    ),
    strictness: str = typer.Option("standard", "--strictness", help="strict | standard | lenient"),
    rescorer_mode: Optional[str] = typer.Option(
        None, "--rescorer-mode",
        help="V1.2 learned-head mode: off | shadow | adjudicate. "
             "Overrides config.rescorer.mode. Default (unset) uses the YAML "
             "config value, which ships as 'off'. 'shadow' scores every row "
             "and records the prediction without changing decisions — safe to "
             "leave on. 'adjudicate' lets the rescorer flip rule-maybe rows "
             "to keep (or cull) when confident; only flip this on when "
             "scripts/check_v1_2_trigger.py reports STATUS: READY."
    ),
    rescorer_path: Optional[str] = typer.Option(
        None, "--rescorer-path",
        help="Path to a rescorer joblib. Overrides config.rescorer.model_path. "
             "Default (unset) uses models/rescorer_v1.joblib."
    ),
    vlm_mode: Optional[str] = typer.Option(
        None, "--vlm-mode",
        help="Vision judge that actually looks at the pixels. "
             "'minimax' (MiniMax M3, cloud — needs MINIMAX_API_KEY) | "
             "'local' (Qwen3-VL via MLX, on-device) | 'off'. "
             "Default (unset): 'minimax' when a MiniMax key is present, "
             "else 'off'. Photos ARE uploaded in cloud modes."
    ),
    meta_mode: Optional[str] = typer.Option(
        None, "--meta-mode",
        help="Text LLM that consolidates every signal into one calibrated "
             "verdict: 'deepseek' | 'off'. Sends metrics, never images."
    ),
) -> None:
    """Run full culling + scoring pipeline on a folder."""
    from pixcull.pipeline.orchestrator import run_pipeline

    # v2.48 — the run command had no --vlm-mode at all, so the vision
    # judge was unreachable for anyone using the CLI: run_pipeline
    # defaults vlm_mode="off" and nothing here ever overrode it. The
    # backend could be perfectly configured and still never run.
    if vlm_mode is None:
        from pixcull.scoring.m3 import api_key_from_env
        vlm_mode = "minimax" if api_key_from_env() else "off"

    # v2.50 — the consent gate. Auto-enabling an upload because a key
    # happens to be present would be exactly the trick this is here to
    # prevent, so ask once, record it, and make declining a first-class
    # outcome rather than an error.
    if vlm_mode not in ("off", "local") and not vlm_mode.startswith("local"):
        from pixcull.scoring.m3 import CONSENT_NOTICE, grant_consent, has_consent
        if not has_consent():
            console.print(CONSENT_NOTICE)
            if not sys.stdin.isatty():
                console.print(
                    "[yellow]No consent on file and nothing to ask.[/yellow] "
                    "Run `pixcull m3 consent --grant` once, or pass "
                    "`--vlm-mode off`. Continuing on-device.")
                vlm_mode = "off"
            elif typer.confirm("Upload photos to MiniMax for judging?",
                               default=False):
                grant_consent()
                console.print("[dim]Recorded. "
                              "`pixcull m3 consent --revoke` undoes it.[/dim]")
            else:
                console.print("[green]Staying on-device[/green] for this and "
                              "every future run until you say otherwise.")
                vlm_mode = "off"
        if vlm_mode != "off":
            console.print("[dim]Judging with MiniMax M3 — photos are "
                          "uploaded. `--vlm-mode off` keeps a run local.[/dim]")

    run_pipeline(
        folder, output,
        scene_override=scene,
        strictness=strictness,
        rescorer_mode=rescorer_mode,
        rescorer_path=rescorer_path,
        vlm_mode=vlm_mode,
        meta_mode=meta_mode or "off",
    )


@app.command()
def export(
    run_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False,
        help="Run output dir (the one containing scores.csv)"),
    fmt: str = typer.Option("xmp", "--format", "-f", help="xmp | csv"),
    target: str = typer.Option(
        "alongside", "--target", "-t",
        help="alongside = sidecar next to each original (what Lightroom "
             "and Capture One pick up) | collected = sidecars gathered in "
             "<run>/xmp/ | embedded = write IPTC into the originals "
             "(needs exiftool)"),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="CSV path (--format csv only)"),
) -> None:
    """Export ratings to XMP sidecars (Lightroom / C1) or CSV.

    v2.40 — this was a stub that raised ``typer.Exit(1)`` with no message
    since V0.5, while the packaging blurb advertised "XMP/IPTC export,
    Lightroom & Capture One ready".  Export did exist, but only inside
    the web workspace, so the CLI path v2.31 opened up for pip users
    dead-ended here.  It now runs the *same* code the server does —
    ``_build_results`` for the rows, then ``write_xmp`` /
    ``write_iptc_to_file`` — rather than a second implementation that
    could drift.
    """
    scores = run_dir / "scores.csv"
    if not scores.is_file():
        console.print(f"[red]no scores.csv in {run_dir}[/] — point this at a "
                      f"run's output dir (the one `pixcull run --output` "
                      f"created).")
        raise typer.Exit(code=2)

    fmt = fmt.strip().lower()
    if fmt not in ("xmp", "csv"):
        console.print(f"[red]unknown --format {fmt!r}[/] (xmp | csv)")
        raise typer.Exit(code=2)

    if fmt == "csv":
        dest = out or (run_dir / "ratings.csv")
        n = _export_ratings_csv(scores, dest)
        console.print(f"[green]✓[/] {n} rows → {dest}")
        return

    target = target.strip().lower()
    if target not in ("alongside", "collected", "embedded"):
        console.print(f"[red]unknown --target {target!r}[/] "
                      f"(alongside | collected | embedded)")
        raise typer.Exit(code=2)

    written, skipped, per_decision = _export_xmp(run_dir, target)
    if not written:
        console.print("[yellow]nothing written[/] — no source images were "
                      "resolvable (moved originals, or an external drive is "
                      "offline)")
        raise typer.Exit(code=1)
    breakdown = " · ".join(f"{k} {v}" for k, v in sorted(per_decision.items()))
    where = {"alongside": "next to each original",
             "collected": f"{run_dir / 'xmp'}",
             "embedded": "embedded in the originals"}[target]
    console.print(f"[green]✓[/] {written} sidecars → {where}"
                  + (f"  [dim]({breakdown})[/dim]" if breakdown else ""))
    if skipped:
        console.print(f"[yellow]{skipped} skipped[/] "
                      f"[dim](source image not reachable)[/dim]")


def _export_ratings_csv(scores_csv: Path, dest: Path) -> int:
    """filename, decision, stars, colour label — the flat form C1 and
    spreadsheet workflows ask for."""
    import csv as _csv
    from pixcull.io.xmp import decision_to_xmp

    rows = []
    with scores_csv.open(encoding="utf-8", newline="") as fh:
        for r in _csv.DictReader(fh):
            decision = (r.get("decision") or "").strip()
            stars, label = decision_to_xmp(decision)
            rows.append({"filename": r.get("filename", ""),
                         "decision": decision,
                         "rating": stars,
                         "color_label": label,
                         "score_final": r.get("score_final", "")})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["filename", "decision", "rating",
                                            "color_label", "score_final"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _export_xmp(run_dir: Path, target: str) -> tuple[int, int, dict]:
    """Write XMP/IPTC for every row, mirroring the server's exporter."""
    import csv as _csv
    from collections import Counter

    from pixcull.io.xmp import (
        build_iptc_fields_from_row, decision_to_xmp, write_xmp,
    )

    path_map = _run_path_map(run_dir)
    xmp_dir = run_dir / "xmp"
    if target == "collected":
        xmp_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    per_decision: Counter = Counter()
    with (run_dir / "scores.csv").open(encoding="utf-8", newline="") as fh:
        for row in _csv.DictReader(fh):
            fn = row.get("filename") or ""
            if not fn:
                continue
            decision = (row.get("decision") or "").strip()
            stars, label = decision_to_xmp(decision)
            iptc = build_iptc_fields_from_row(row, run_id=run_dir.parent.name)

            if target == "collected":
                write_xmp(xmp_dir / Path(fn).name, stars, label,
                          keywords=iptc["keywords"],
                          description=iptc["description"],
                          headline=iptc["headline"])
            else:
                src = path_map.get(fn)
                if src is None:
                    skipped += 1
                    continue
                if target == "embedded":
                    from pixcull.io.iptc_embed import write_iptc_to_file
                    if not write_iptc_to_file(
                            src, rating=stars, color_label=label,
                            keywords=iptc["keywords"],
                            description=iptc["description"],
                            headline=iptc["headline"]):
                        skipped += 1
                        continue
                else:
                    write_xmp(src, stars, label,
                              keywords=iptc["keywords"],
                              description=iptc["description"],
                              headline=iptc["headline"])
            written += 1
            per_decision[decision] += 1
    return written, skipped, dict(per_decision)


@app.command(name="contact-sheet")
def contact_sheet(
    run_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False,
        help="Run output dir (contains scores.csv)"),
    out: Path = typer.Option(Path("contact_sheet.pdf"), "--out", "-o",
                             help="Output PDF path"),
    decision: str = typer.Option("keep", "--decision", "-d",
                                 help="keep | maybe | cull | all"),
    cols: int = typer.Option(4, "--cols", help="Thumbnails per row"),
    rows: int = typer.Option(5, "--rows", help="Rows per page"),
    title: str = typer.Option(None, "--title",
                              help="Sheet title (default: run name + count)"),
    images_dir: Path = typer.Option(
        None, "--images",
        help="Where to find thumbnails (default: <run>/thumbs)"),
    studio: str = typer.Option(
        None, "--studio", help="Studio / photographer name on the cover"),
    date: str = typer.Option(
        None, "--date", help="Shoot date line on the cover"),
    no_cover: bool = typer.Option(
        False, "--no-cover", help="Skip the branded cover page"),
) -> None:
    """v2.5-P1 — export a client-ready contact-sheet PDF of a run's selects.

    A branded deliverable: cover page (studio / date), then a printable
    grid — thumbnail + filename + 1-5 star rating per cell — of the
    photos with the chosen decision.
    """
    from pixcull.report.contact_sheet import contact_sheet_from_run
    n_pages, n_photos = contact_sheet_from_run(
        run_dir, out, decision=decision, cols=cols, rows_per_page=rows,
        title=title, images_dir=images_dir,
        studio=studio, date=date, with_cover=not no_cover)
    typer.echo(
        f"✓ {out}  ·  {n_photos} {decision} photo(s)  ·  {n_pages} page(s)")


@app.command()
def bench(
    folder: Path = typer.Argument(..., exists=True, file_okay=False),
    limit: int = typer.Option(24, "--limit", "-n",
                              help="How many images to time (0 = all)"),
    workers: Optional[int] = typer.Option(
        None, "--workers", "-w", help="Worker processes (default: auto)"),
    keep_output: bool = typer.Option(
        False, "--keep-output", help="Leave the scratch run dir in place"),
) -> None:
    """Benchmark images-per-second throughput on this machine.

    v2.40 — was a stub that exited 1 with no message since V0.5.  Runs
    the real pipeline (the same one `pixcull run` uses), because the
    number people actually want is end-to-end throughput, not a
    micro-benchmark of one detector.

    The first run on a cold machine also pays model loading, which is
    reported separately so a 24-image sample isn't mistaken for the
    steady-state rate.
    """
    import shutil
    import tempfile
    import time

    from pixcull.io.loader import list_images

    images = list_images(folder)
    if not images:
        console.print(f"[red]no readable images in {folder}[/]")
        raise typer.Exit(code=2)
    if limit and limit > 0:
        images = images[:limit]

    scratch = Path(tempfile.mkdtemp(prefix="pixcull_bench_"))
    sample_dir = scratch / "sample"
    sample_dir.mkdir()
    # Symlink rather than copy: copying a few hundred RAWs would time the
    # disk instead of the pipeline.
    for p in images:
        try:
            (sample_dir / p.name).symlink_to(p.resolve())
        except OSError:
            shutil.copy2(p, sample_dir / p.name)

    # run_pipeline takes no `workers` argument — the pool reads
    # PIXCULL_WORKERS (pipeline/parallel.py::_default_workers), so set
    # that rather than offering a flag that silently does nothing.
    prev_workers = os.environ.get("PIXCULL_WORKERS")
    if workers and workers > 0:
        os.environ["PIXCULL_WORKERS"] = str(workers)
    # A benchmark must not file its throwaway sample into the user's
    # cross-run library: the scratch dir is deleted straight after, so
    # every row would become a permanently stale hit in /library.
    prev_noindex = os.environ.get("PIXCULL_NO_AUTO_INDEX")
    os.environ["PIXCULL_NO_AUTO_INDEX"] = "1"

    console.print(f"[cyan]Benchmarking[/] {len(images)} image(s) from {folder}"
                  + (f" · {workers} workers" if workers else ""))
    try:
        from pixcull.pipeline.orchestrator import run_pipeline
        t0 = time.perf_counter()
        run_pipeline(sample_dir, scratch / "out")
        elapsed = time.perf_counter() - t0
    finally:
        if prev_workers is None:
            os.environ.pop("PIXCULL_WORKERS", None)
        else:
            os.environ["PIXCULL_WORKERS"] = prev_workers
        if prev_noindex is None:
            os.environ.pop("PIXCULL_NO_AUTO_INDEX", None)
        else:
            os.environ["PIXCULL_NO_AUTO_INDEX"] = prev_noindex
        if not keep_output:
            shutil.rmtree(scratch, ignore_errors=True)

    n = len(images)
    rate = n / elapsed if elapsed else 0.0
    console.print(
        f"\n[bold green]{rate:.2f} img/s[/]  "
        f"[dim]({n} images in {elapsed:.1f}s, {elapsed / n:.2f}s each)[/dim]")
    for shoot, label in ((500, "small shoot"), (1500, "wedding"),
                         (5000, "multi-day event")):
        if rate:
            mins = shoot / rate / 60
            console.print(f"  [dim]{shoot:>5,} photos ({label}): "
                          f"~{mins:.0f} min[/dim]")
    console.print("[dim]First run includes one-off model loading; re-run for "
                  "the steady-state rate.[/dim]")
    if keep_output:
        console.print(f"[dim]scratch kept at {scratch}[/dim]")


@app.command()
def transcribe(
    media: Path = typer.Argument(..., exists=True, dir_okay=False,
                                 help="Video or audio file"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Run dir to write transcript.json + transcript.srt into "
             "(default: alongside the media file)"),
    engine: str = typer.Option(
        "auto", "--engine", "-e",
        help="auto | paraformer (Mandarin-first, FunASR) | whisper"),
    language: str = typer.Option(
        "", "--language", "-l", help="Language hint, e.g. zh / en"),
    shots: bool = typer.Option(
        True, "--shots/--no-shots",
        help="Tag each line with the shot it starts in (needs "
             "pixcull[shots]); makes 'jump to this line' land on a real "
             "shot rather than mid-cut"),
    speakers: bool = typer.Option(
        False, "--speakers",
        help="Label who is speaking (Paraformer only; loads cam++). "
             "Needs a long enough clip — FunASR's clusterer gives up "
             "under 20 speech segments and reports one speaker."),
    hotword: list[str] = typer.Option(
        [], "--hotword", "-H",
        help="Bias recognition towards a term (repeatable). Shoot-specific "
             "vocabulary — a venue, a couple's names — on top of the "
             "built-in Mandarin lexicon. Paraformer only."),
) -> None:
    """Transcribe speech to transcript.json + an SRT sidecar.

    v2.43 — before this, PixCull could tell you a clip was sharp, stable
    and had a laugh in it, but not a word of what was said.
    """
    from pixcull.scoring.transcribe import (
        TranscriptionUnavailable, available_engines, transcribe as _run,
        write_transcript,
    )

    out_dir = output or media.parent
    cut_points = []
    if shots:
        from pixcull.scoring.shot_boundaries import available as _shots_ok
        from pixcull.scoring.shot_boundaries import detect_cuts
        if _shots_ok():
            cut_points = detect_cuts(media)
            if cut_points:
                console.print(f"[dim]{len(cut_points)} shot boundaries[/dim]")

    try:
        result = _run(media, engine=engine, language=language,
                      cut_points=cut_points, hotwords=hotword,
                      speakers=speakers)
    except TranscriptionUnavailable as exc:
        # escape(): rich reads "[asr]" as a style tag and swallows it,
        # which turned the install hint into `pip install "pixcull"` —
        # i.e. we'd be telling the user the wrong command.
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(code=3) from None
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(code=2) from None

    if not result.segments:
        console.print("[yellow]no speech found[/] "
                      "[dim](silent clip, or the wrong --language)[/dim]")
        raise typer.Exit(code=1)

    if speakers:
        found = {s.speaker for s in result.segments if s.speaker}
        if found:
            console.print(f"[dim]{len(found)} speaker(s) distinguished[/dim]")
        else:
            console.print(
                "[yellow]no speakers distinguished[/] [dim](one person, or "
                "the clip is too short for the clusterer — see "
                "--speakers help)[/dim]")

    written = write_transcript(result, out_dir)
    dur = max((s.end_s for s in result.segments), default=0.0)
    console.print(
        f"[green]✓[/] {written['n_segments']} lines · {dur:.1f}s · "
        f"{result.engine}"
        + (f" · {result.language}" if result.language else ""))
    console.print(f"  [dim]{written['json']}[/dim]")
    console.print(f"  [dim]{written['srt']}[/dim]")
    _ = available_engines


@app.command(name="transcribe-engines")
def transcribe_engines() -> None:
    """List installed ASR engines (diagnostic)."""
    from pixcull.scoring.transcribe import ENGINES, available_engines

    have = available_engines()
    for e in ENGINES:
        mark = "[green]✓[/]" if e in have else "[dim]·[/]"
        extra = "asr" if e == "paraformer" else "asr-whisper"
        hint = "" if e in have else (
            f'  [dim]pip install "pixcull{escape("[" + extra + "]")}"[/dim]')
        console.print(f"  {mark} {e}{hint}")
    if not have:
        console.print("[yellow]no engine installed[/] — "
                      "`pixcull transcribe` will exit 3 until one is")


@app.command()
def video(
    path: Path = typer.Argument(
        ..., exists=True, dir_okay=False,
        help="Video file (.mp4 / .mov / .mkv / .m4v / …)",
    ),
    output: Path = typer.Option(
        Path("./output"), "--output", "-o",
        help="Run output folder (frames land in video_frames/<id>/)",
    ),
    mode: str = typer.Option(
        "interval", "--mode",
        help="interval (1 frame / interval-s) | keyframe (1 frame / GOP)",
    ),
    interval_s: float = typer.Option(
        1.0, "--interval-s",
        help="Seconds between frames in interval mode (auto-widened "
             "if it would exceed --max-frames).",
    ),
    max_frames: int = typer.Option(
        3000, "--max-frames",
        help="Safety cap on extracted frames.",
    ),
    max_dim: Optional[int] = typer.Option(
        None, "--max-dim",
        help="v2.0-P2-1 proxy: cap extracted-frame long edge to N px "
             "(e.g. 1920 for 4K/8K). Faster + lighter scoring; full res "
             "if unset.",
    ),
    extract_only: bool = typer.Option(
        False, "--extract-only",
        help="Stop after frame extraction; skip the scoring pipeline.",
    ),
    scene: Optional[str] = typer.Option(
        None, "--scene",
        help="Force scene for the scoring pass (see `run`).",
    ),
    strictness: str = typer.Option("standard", "--strictness"),
    rescorer_mode: Optional[str] = typer.Option(
        None, "--rescorer-mode",
        help="off | shadow | adjudicate (see `run`).",
    ),
    no_temporal: bool = typer.Option(
        False, "--no-temporal",
        help="Skip the v2.0-P0-2 temporal pass (score_temporal + "
             "per-window aggregation).",
    ),
    window_s: float = typer.Option(
        1.0, "--window-s",
        help="Time-window length (s) for temporal aggregation.",
    ),
    no_reel: bool = typer.Option(
        False, "--no-reel",
        help="Skip the v2.0-P0-3 reel-candidate detector.",
    ),
    reel_max: int = typer.Option(
        20, "--reel-max",
        help="Max reel candidates to emit (default 10–20).",
    ),
) -> None:
    """v2.0 — Import a video: extract → score → temporal → reel candidates.

    The extracted ``video_frames/<id>/`` folder is scored by the same
    pipeline as a photo shoot, so the video becomes one PixCull "run"
    (a dense burst group).  After scoring, a temporal pass adds
    ``score_temporal`` per frame + per-window scores (``temporal.json``),
    then a reel-candidate detector emits the best diverse clips
    (``reel_candidates.json``).  Use ``--extract-only`` to stop after
    frame extraction, ``--no-temporal`` / ``--no-reel`` to skip a stage.
    """
    from pixcull.io.video import import_video, FFmpegError

    try:
        result = import_video(
            path, output,
            mode=mode, interval_s=interval_s, max_frames=max_frames,
            max_dim=max_dim,
        )
    except FFmpegError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)
    except ValueError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)

    m = result.meta
    table = Table(title=f"Imported {m.source_name} → {result.frame_count} frames")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("video_id", m.video_id)
    table.add_row("codec", str(m.codec))
    table.add_row("resolution", f"{m.width}×{m.height}")
    table.add_row("fps", str(m.fps))
    table.add_row("duration", f"{m.duration_s}s")
    table.add_row("audio tracks", str(m.audio_track_count))
    table.add_row("mode", result.mode + (
        f" ({result.interval_s}s)" if result.interval_s else ""))
    table.add_row("frames", str(result.frame_count))
    table.add_row("frames dir", str(result.frames_dir))
    console.print(table)

    if extract_only:
        console.print("[dim]--extract-only set; skipping scoring.[/dim]")
        return

    console.print("[bold]Scoring extracted frames…[/bold]")
    from pixcull.pipeline.orchestrator import run_pipeline

    run_pipeline(
        result.frames_dir, output,
        scene_override=scene,
        strictness=strictness,
        rescorer_mode=rescorer_mode,
    )
    console.print(f"[green]✓ Run complete → {output}[/green]")

    if no_temporal:
        console.print("[dim]--no-temporal set; skipping temporal pass.[/dim]")
        return

    console.print("[bold]Temporal pass (score_temporal + windows)…[/bold]")
    from pixcull.scoring.temporal import run_temporal_analysis

    temporal = run_temporal_analysis(
        output, result.frames_dir, window_s=window_s)
    best = max(temporal.windows, key=lambda w: w.window_score, default=None)
    if best is not None:
        console.print(
            f"[green]✓ Temporal → temporal.json[/green]  "
            f"({len(temporal.windows)} windows; best "
            f"[{best.start_s:.1f}–{best.end_s:.1f}s] "
            f"score={best.window_score:.2f}, peak {best.peak_frame_id})"
        )

    if no_reel:
        console.print("[dim]--no-reel set; skipping reel detector.[/dim]")
        return

    console.print("[bold]Reel candidate detector…[/bold]")
    from pixcull.scoring.reel import run_reel_detection

    candidates = run_reel_detection(output, n_max=reel_max)
    console.print(
        f"[green]✓ Reel → reel_candidates.json[/green]  "
        f"({len(candidates)} candidates)"
    )
    rtab = Table(title="Top reel candidates")
    rtab.add_column("#", style="cyan", justify="right")
    rtab.add_column("span")
    rtab.add_column("score", justify="right")
    rtab.add_column("why")
    for c in candidates[:8]:
        rtab.add_row(
            str(c.rank),
            f"{c.start_s:.1f}–{c.end_s:.1f}s",
            f"{c.score:.2f}",
            c.why,
        )
    if candidates:
        console.print(rtab)


@app.command()
def reel(
    run_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False,
        help="A video run dir (with reel_candidates.json + manifest).",
    ),
    ranks: Optional[str] = typer.Option(
        None, "--ranks",
        help="Comma-separated candidate ranks to assemble (default: "
             "top-scoring up to --target-s).",
    ),
    target_s: float = typer.Option(
        60.0, "--target-s", help="Target reel length when auto-selecting."),
    crossfade_s: float = typer.Option(
        0.5, "--crossfade", help="Cross-fade seconds (0 = hard cuts)."),
    reel_id: str = typer.Option("reel", "--id", help="Output reel id."),
    edl_only: bool = typer.Option(
        False, "--edl-only", help="Write the EDL only; skip ffmpeg render."),
    add: Optional[list[Path]] = typer.Option(
        None, "--add",
        help="v2.1 — add another video run dir to build a multi-clip "
             "SHOOT reel (repeatable). Each run contributes its top "
             "candidates across --target-s.",
    ),
    export: Optional[str] = typer.Option(
        None, "--export",
        help="v2.2 — also re-frame the reel to a delivery preset "
             "(reels | square | wide) with loudness-normalised audio.",
    ),
) -> None:
    """v2.0/v2.1 — Auto-assemble reel candidates into one cut + EDL.

    Single run by default; pass --add <run> (repeatable) to stitch a
    shoot-level reel across multiple clips.
    """
    from pixcull.io.reel_assembly import (
        assemble_from_run, assemble_shoot, export_preset)
    from pixcull.io.video import FFmpegError

    def _maybe_export(result) -> None:
        if not export or not getattr(result, "mp4_path", None):
            return
        try:
            ep = export_preset(result.mp4_path, result.mp4_path.parent, export)
            console.print(f"  Export ({export}): {ep}")
        except (FFmpegError, ValueError) as exc:
            console.print(f"  [yellow]export skipped: {exc}[/yellow]")

    # v2.1-P1-2 — multi-run shoot reel.
    if add:
        try:
            result = assemble_shoot(
                [run_dir, *add], run_dir, target_s=target_s,
                crossfade_s=crossfade_s, reel_id="shoot_reel",
                edl_only=edl_only)
        except (FFmpegError, FileNotFoundError, ValueError) as exc:
            console.print(f"[red]✗ {exc}[/red]")
            raise typer.Exit(code=2)
        console.print(
            f"[green]✓ Shoot reel assembled[/green] — {len(result.clips)} "
            f"clips from {1 + len(add)} runs, {result.duration_s}s")
        console.print(f"  EDL: {result.edl_path}")
        if result.mp4_path:
            console.print(f"  MP4: {result.mp4_path}")
        _maybe_export(result)
        return

    rank_list = None
    if ranks:
        try:
            rank_list = [int(x) for x in ranks.split(",") if x.strip()]
        except ValueError:
            console.print("[red]✗ --ranks must be comma-separated ints[/red]")
            raise typer.Exit(code=2)
    try:
        result = assemble_from_run(
            run_dir, ranks=rank_list, target_s=target_s,
            crossfade_s=crossfade_s, reel_id=reel_id, edl_only=edl_only)
    except (FFmpegError, FileNotFoundError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)

    console.print(
        f"[green]✓ Reel assembled[/green] — {len(result.clips)} clips, "
        f"{result.duration_s}s")
    console.print(f"  EDL: {result.edl_path}")
    if result.mp4_path:
        console.print(f"  MP4: {result.mp4_path}")
        _maybe_export(result)
    else:
        console.print("  [dim](--edl-only; no MP4 rendered)[/dim]")


@app.command()
def proxy(
    path: Path = typer.Argument(..., exists=True, dir_okay=False,
                                help="A RAW or video file."),
    output: Path = typer.Option(Path("./output"), "--output", "-o",
                                help="Where the ProRes proxy is written."),
    transcoder: Optional[str] = typer.Option(
        None, "--transcoder",
        help="Vendor RAW transcoder, called as `<tool> <in> <out>` "
             "(else PIXCULL_RAW_TRANSCODER)."),
) -> None:
    """v2.1 — Make a ProRes proxy (RAW → guided transcode bridge)."""
    from pixcull.io.raw_proxy import make_proxy, raw_proxy_recipe, needs_proxy
    from pixcull.io.video import FFmpegError

    if needs_proxy(path):
        console.print(f"[yellow]{path.name} is RAW video.[/yellow] "
                      f"{raw_proxy_recipe(path).advice}")
    try:
        out = make_proxy(path, output, transcoder=transcoder)
    except FFmpegError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)
    console.print(f"[green]✓ proxy → {out}[/green]  (then: pixcull video {out})")


# v0.13.13 — plugin management.
plugins_app = typer.Typer(help="Manage PixCull plugins (v0.13.13).",
                           no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list() -> None:
    """Show installed plugins + enabled state."""
    from pixcull.plugins import get_registry, load_all
    load_all()
    info = get_registry().info()
    if not info:
        console.print("[yellow]No plugins installed.[/yellow]")
        console.print("Drop a .py file into "
                      "[cyan]~/.pixcull/plugins/[/cyan] then "
                      "[cyan]pixcull plugins reload[/cyan].")
        return
    table = Table(title=f"PixCull plugins ({len(info)})",
                   show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Version", style="dim")
    table.add_column("Author", style="dim")
    table.add_column("Status")
    table.add_column("Axes", justify="right")
    table.add_column("Reasons", justify="right")
    table.add_column("Handlers", justify="right")
    for p in info:
        status = "[green]enabled[/green]" if p.enabled else "[dim]disabled[/dim]"
        table.add_row(
            p.name, p.version, p.author or "—", status,
            str(p.n_axes), str(p.n_cull_reasons),
            str(p.n_event_handlers),
        )
    console.print(table)


@plugins_app.command("enable")
def plugins_enable(name: str = typer.Argument(...)) -> None:
    """Mark a plugin as active."""
    from pixcull.plugins import get_registry, load_all
    load_all()
    reg = get_registry()
    if reg.enable(name):
        console.print(f"[green]✓ enabled {name}[/green]")
    else:
        console.print(f"[red]✗ no plugin named {name!r}[/red]")
        raise typer.Exit(code=2)


@plugins_app.command("disable")
def plugins_disable(name: str = typer.Argument(...)) -> None:
    """Mark a plugin as inactive (kept on disk)."""
    from pixcull.plugins import get_registry, load_all
    load_all()
    reg = get_registry()
    if reg.disable(name):
        console.print(f"[yellow]✓ disabled {name}[/yellow]")
    else:
        console.print(f"[red]✗ no plugin named {name!r}[/red]")
        raise typer.Exit(code=2)


@plugins_app.command("reload")
def plugins_reload() -> None:
    """Re-scan + re-register all plugin files."""
    from pixcull.plugins import load_all, get_registry
    n = load_all()
    console.print(f"[green]✓ re-loaded {n} plugin(s)[/green]")
    n_axes = len(get_registry().axes())
    n_reasons = len(get_registry().cull_reasons())
    console.print(
        f"  {n_axes} custom axes · {n_reasons} custom cull reasons "
        f"(enabled only)")


# v2.2-P1-2 — optional learned-model manager.
models_app = typer.Typer(
    help="Pull + locate PixCull's optional learned models (v2.2-P1-2).",
    no_args_is_help=True)
app.add_typer(models_app, name="models")


# --------------------------------------------------------------------------
# v2.48 — MiniMax M3, the primary vision judge
# --------------------------------------------------------------------------

m3_app = typer.Typer(
    help="MiniMax M3 — the cloud vision judge (v2.48).",
    no_args_is_help=True)
app.add_typer(m3_app, name="m3")


@m3_app.command("doctor")
def m3_doctor(
    image: Path = typer.Option(None, "--image",
                               help="A photo to probe image input with."),
    video: Path = typer.Option(None, "--video",
                               help="A short clip (<50 MB) to probe video "
                                    "input with. Without this, the video "
                                    "content-part shape stays unverified "
                                    "and score_video() will refuse to run."),
    save: bool = typer.Option(True, "--save/--no-save",
                              help="Record findings to "
                                   "~/.pixcull/m3_capabilities.json"),
) -> None:
    """Make real calls to M3 and report what the endpoint actually accepts.

    Every failure mode in this integration is silent: a stale endpoint,
    a stale model string, an expired key and a wrong video content-part
    all surface identically — as ``verdict.error`` on every row — so a
    run of 3000 nulls reads exactly like a run that worked.  This command
    is the loud version.

    It also settles the one thing the vendor docs would not tell us: which
    JSON encoding of a video content part the live endpoint accepts.  It
    tries each candidate and records the winner.
    """
    from pixcull.scoring.m3 import (
        BASE_URL, MODEL, api_key_from_env, capability_path,
        probe_capabilities, save_capabilities,
    )

    key = api_key_from_env()
    if not key:
        console.print(
            "[red]No MiniMax key found.[/red]\n"
            "PixCull reads it from the environment or the macOS keychain — "
            "never from the repo.\n\n"
            "  export MINIMAX_API_KEY=…            (this shell only)\n"
            "  security add-generic-password -a \"$USER\" \\\n"
            "      -s MINIMAX_API_KEY -w           (persistent, prompts you)\n")
        raise typer.Exit(code=2)

    console.print(f"[dim]endpoint[/dim] {BASE_URL}   [dim]model[/dim] {MODEL}")
    caps = probe_capabilities(key, image, video)

    table = Table(title="M3 capability probe")
    table.add_column("Capability", style="bold")
    table.add_column("Result")

    def _row(label: str, detail: object, skipped_hint: str = "") -> None:
        if detail is None:
            table.add_row(label, f"[dim]not probed — {skipped_hint}[/dim]")
        elif detail == "ok":
            table.add_row(label, "[green]ok[/green]")
        else:
            table.add_row(label, f"[red]{detail}[/red]")

    _row("auth + model string", caps.get("text"))
    # The failure the owner actually hits. Printing a raw 402 next to a
    # raw 401 leaves them to work out which of two opposite fixes applies.
    from pixcull.scoring.m3 import explain_api_error
    _hint = explain_api_error(Exception(str(caps.get("text") or "")))
    _row("json_object output", caps.get("json_object"))
    _row("image input", caps.get("image"), "pass --image <photo>")

    shape = caps.get("video_part_shape")
    if not caps.get("video_attempts"):
        table.add_row("video input",
                      "[dim]not probed — pass --video <clip.mp4>[/dim]")
    elif shape:
        table.add_row("video input", f"[green]ok[/green] — shape: {shape}")
    else:
        table.add_row("video input", "[red]no candidate shape accepted[/red]")
    console.print(table)

    for name, detail in (caps.get("video_attempts") or {}).items():
        if detail != "ok":
            console.print(f"  [dim]video shape {name}: {detail}[/dim]")

    if _hint:
        console.print(f"\n[yellow]{_hint}[/yellow]")
    if save:
        save_capabilities(caps)
        console.print(f"[dim]saved → {capability_path()}[/dim]")

    # Exit non-zero when the load-bearing capability failed, so this is
    # usable as a pre-flight check in a script.
    if caps.get("text") != "ok":
        raise typer.Exit(code=1)


@m3_app.command("consent")
def m3_consent(
    grant: bool = typer.Option(False, "--grant",
                               help="Record that you agree to upload."),
    revoke: bool = typer.Option(False, "--revoke",
                                help="Withdraw it. Cloud judging then "
                                     "refuses to run until re-granted."),
) -> None:
    """Show, grant or withdraw permission to upload photos to MiniMax.

    v2.50 ships cloud judging on by default. That is defensible only if
    the first upload is something you chose — wedding and commercial
    contracts routinely forbid third-party cloud processing of client
    images, and the person who signed one cannot find out afterwards.
    """
    from pixcull.scoring.m3 import (
        CONSENT_NOTICE, consent_path, grant_consent, has_consent,
        revoke_consent,
    )

    if revoke:
        console.print("[green]Withdrawn.[/green] Cloud judging will refuse "
                      "to run; `--vlm-mode off` is unaffected."
                      if revoke_consent() else
                      "[dim]Nothing on file to withdraw.[/dim]")
        return
    if grant:
        console.print(CONSENT_NOTICE)
        p = grant_consent()
        console.print(f"[green]Recorded[/green] → {p}\n"
                      f"[dim]Withdraw at any time: "
                      f"pixcull m3 consent --revoke[/dim]")
        return

    if has_consent():
        console.print(f"[green]Granted.[/green] {consent_path()}")
    else:
        console.print(CONSENT_NOTICE)
        console.print("[yellow]Not granted.[/yellow] Cloud judging will "
                      "refuse to run.\n  pixcull m3 consent --grant")


@m3_app.command("eval")
def m3_eval(
    labels: Path = typer.Option(..., "--labels", exists=True,
                                help="Your corrected label sheet — a CSV "
                                     "with `filename` and `manual_label`."),
    scores: Path = typer.Option(None, "--scores", exists=True,
                                help="scores.csv with `path` + detector "
                                     "metrics. Defaults to --labels when "
                                     "that file carries them itself."),
    limit: int = typer.Option(None, "--limit",
                              help="Evaluate only the first N rows — use "
                                   "this to sanity-check cost first."),
    out: Path = typer.Option(Path("docs/M3-EVAL.md"), "--out",
                             help="Where to write the report."),
    vertical: str = typer.Option(None, "--vertical"),
    review: list[Path] = typer.Option(None, "--review", exists=True,
                                      help="A saved `pixcull m3 review` "
                                           "result. Your verdicts override "
                                           "the label sheet — which is the "
                                           "whole point: a label set that "
                                           "never contradicts the rule stack "
                                           "cannot rank it against anything. "
                                           "Repeatable: pass --review once "
                                           "per review pass and they merge."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Check the join, the photo paths and "
                                      "the estimated cost — without calling "
                                      "M3 or spending anything."),
) -> None:
    """Measure whether M3 actually decides better than the rule stack.

    This is the gate in front of the positioning rewrite. v2.48 built a
    judge that CAN decide; nothing showed it decides WELL, and rewriting
    the product's public promises on an unmeasured assumption is a bet.

    The report's headline is a verdict, and it is allowed to say no.
    """
    import csv as _csv

    from pixcull.config import PixCullConfig
    from pixcull.scoring.m3 import (
        MODEL, VerdictCache, api_key_from_env, default_cache_path,
    )
    from pixcull.scoring.vlm_eval import evaluate, load_labels, render_report
    from pixcull.scoring.vlm_judge import make_minimax_judge

    key = api_key_from_env()
    if not key:
        console.print("[red]No MiniMax key.[/red] "
                      "See `pixcull m3 doctor` for how to supply one.")
        raise typer.Exit(code=2)

    lab = load_labels(labels)
    # v2.53.2 — repeatable. As a single Option this silently kept only the
    # LAST --review: passing both review passes threw the first one's
    # judgements away and reported a smaller, quieter number as if it were
    # the whole evidence base.
    if review:
        from pixcull.report.review_sheet import load_verdicts
        applied, seen = 0, {}
        for src in review:
            for fn, verdict in load_verdicts(src).items():
                # The same frame judged twice, differently, is the reviewer
                # contradicting themselves. Silently taking the later file
                # would bury that; it is worth their attention.
                if fn in seen and seen[fn][1] != verdict:
                    console.print(
                        f"[yellow]conflict:[/yellow] {fn} — "
                        f"{seen[fn][0].name} says {seen[fn][1]}, "
                        f"{src.name} says {verdict}; using {verdict}")
                seen[fn] = (src, verdict)
                if fn in lab and lab[fn].get("manual_label") != verdict:
                    lab[fn] = {**lab[fn], "manual_label": verdict}
                    applied += 1
        console.print(f"[dim]review: {applied} label(s) replaced by your "
                      f"own verdict, from {len(review)} pass(es)[/dim]")
    if not lab:
        console.print(f"[red]{labels} has no rows with a manual_label.[/red] "
                      "An unlabelled row cannot make anyone right or wrong.")
        raise typer.Exit(code=2)

    src = scores or labels
    with open(src, encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.DictReader(fh))

    n_join = sum(1 for r in rows if (r.get("filename") or "").strip() in lab)
    console.print(f"[dim]{len(lab)} labelled · {len(rows)} scored · "
                  f"{n_join} joined[/dim]")
    if not n_join:
        console.print("[red]Nothing joined on `filename`.[/red] The label "
                      "sheet and the scores file describe different shoots.")
        raise typer.Exit(code=2)
    if not any(r.get("path") for r in rows):
        console.print("[yellow]No `path` column — M3 cannot be shown the "
                      "photos.[/yellow] Pass --scores pointing at a run's "
                      "scores.csv.")
        raise typer.Exit(code=2)

    # v2.49 — verify before spending. A 608-row run that dies on row 3
    # because the photos moved has still been billed for rows 1 and 2,
    # and the failure mode looks identical to "the model had no opinion".
    live = sum(1 for r in rows
               if r.get("path") and Path(str(r["path"])).exists())
    console.print(f"[dim]{live}/{n_join} joined rows have a readable photo"
                  f"[/dim]")
    if not live:
        console.print(
            "[red]None of the photos are where the CSV says they are.[/red] "
            "Paths go stale when a drive remounts under a different name or "
            "a /tmp working copy is cleared — fix the paths, not the eval.")
        raise typer.Exit(code=2)
    todo = min(live, limit) if limit else live
    # v2.49.2 — measured, not assumed. The first estimate used 150 output
    # tokens; M3 is a reasoning model and actually spends ~1400 (it thinks
    # inside <think> before answering), so the real per-photo cost is
    # ~¥0.021 rather than ~¥0.005. Under-quoting a bill by 4x is worse
    # than not quoting it.
    est = todo * 0.021
    console.print(f"[dim]≈{todo} calls, ≈¥{est:.2f}, "
                  f"≈{todo / 200 * 60:.0f}s at the 200 RPM limit[/dim]")
    if dry_run:
        console.print("[green]Dry run — nothing was sent.[/green] "
                      "Drop --dry-run to measure for real.")
        return

    judge = make_minimax_judge(key)
    judge._cache = VerdictCache(default_cache_path())
    res = evaluate(rows, lab, judge, PixCullConfig.load(),
                   vertical=vertical, limit=limit,
                   progress=lambda n, t, fn: (
                       console.print(f"[dim]{n}/{t} {fn}[/dim]")
                       if n % 25 == 0 or n == t else None))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(res, labels_path=str(labels.name),
                                 model=MODEL), encoding="utf-8")

    table = Table(title="M3 vs rule stack")
    table.add_column("", style="bold")
    table.add_column("rule", justify="right")
    table.add_column("M3", justify="right")
    for label in ("keep", "cull"):
        r = res.rule.get(label)
        v = res.vlm.get(label)
        table.add_row(f"{label} F1", f"{r.f1:.3f}" if r else "—",
                      f"{v.f1:.3f}" if v else "—")
    table.add_row("macro F1", f"{res.rule_macro_f1:.3f}",
                  f"{res.vlm_macro_f1:.3f}")
    console.print(table)
    console.print(f"\n[bold]{res.verdict}[/bold]\n")
    console.print(
        f"[yellow]{res.n_overrides} hard-cull override(s) need your eyes[/] — "
        f"evidence fusion stands or falls on whether they were right.")
    console.print(f"[dim]report → {out}[/dim]")


@m3_app.command("review")
def m3_review(
    labels: Path = typer.Option(..., "--labels", exists=True),
    scores: Path = typer.Option(..., "--scores", exists=True),
    out: Path = typer.Option(Path("~/pixcull_review.html"), "--out"),
    only: str = typer.Option("overrides", "--only",
                             help="'overrides' — frames M3 rescued from a "
                                  "hard cull (the highest-signal set) | "
                                  "'disagreements' — every row the two "
                                  "systems decided differently."),
    limit: int = typer.Option(60, "--limit",
                              help="Cap the page. 60 is about as many as "
                                   "anyone reviews carefully in one sitting."),
) -> None:
    """Build a page for judging M3 against your own eye.

    This is the mechanism that unblocked the whole M3 evaluation. The
    label set had been reviewed but never CONTRADICTED, so the rule stack
    scored 1.000 against its own answers and no comparison was possible.
    Ten minutes on 18 frames produced the first labels that could tell
    the two systems apart.

    Uses only cached verdicts — a frame M3 has not judged is skipped
    rather than billed, so building the page is free.

    The photos never leave this machine: thumbnails are embedded in a
    local HTML file. Reviewing your own client work should not require
    uploading it anywhere, including to us.
    """
    import csv as _csv

    from pixcull.config import PixCullConfig
    from pixcull.report.review_sheet import write
    from pixcull.scoring.decision import decide
    from pixcull.scoring.m3 import (
        VerdictCache, api_key_from_env, default_cache_path,
    )
    from pixcull.scoring.vlm_eval import _flags_of, load_labels
    from pixcull.scoring.vlm_judge import make_minimax_judge

    cfg = PixCullConfig.load()
    lab = load_labels(labels)
    with open(scores, encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.DictReader(fh))

    judge = make_minimax_judge(api_key_from_env() or "x" * 8)
    judge._cache = VerdictCache(default_cache_path())
    judge._require_consent = False

    items, no_verdict = [], 0
    for r in rows:
        fn = (r.get("filename") or "").strip()
        p = r.get("path") or ""
        if fn not in lab or not p or not Path(p).exists():
            continue
        v = judge.score(Path(p), scene=str(r.get("scene") or ""), row=r)
        # elapsed_s == 0 marks a cache hit; anything else means we would
        # be paying to build a review page, which is not a trade anyone
        # asked for.
        if v.error or v.elapsed_s > 0:
            no_verdict += 1
            continue
        axes = {k: a.stars for k, a in v.axes.items()}
        try:
            final = float(r.get("score_final") or 0)
        except ValueError:
            final = 0.0
        flags, scene = _flags_of(r), str(r.get("scene") or "")
        m3_dec, reasons = decide(final, flags, cfg, "standard", scene=scene,
                                 vlm_label=v.overall_label, vlm_axes=axes,
                                 vlm_authority="primary")
        rule_dec, _ = decide(final, flags, cfg, "standard", scene=scene)
        rescued = [x for x in reasons if "vlm_kept_despite" in x]
        if only == "overrides" and not rescued:
            continue
        if only != "overrides" and rule_dec.value == m3_dec.value:
            continue
        items.append({
            "fn": fn, "path": p, "scene": scene, "axes": axes,
            # The stakes differ per direction, so record it: M3 wanting to
            # CULL a rule-keep can destroy a keeper, while a demotion to
            # maybe costs a second look. stratify() covers the first kind
            # in full rather than proportionally.
            "bucket": f"{rule_dec.value}->{m3_dec.value}",
            "a": rule_dec.value, "b": m3_dec.value,
            "a_label": "规则", "b_label": "M3",
            "note": ("推翻了 " + rescued[0].split("(")[1].rstrip(")")
                     if rescued else ""),
            "why": v.overall_rationale,
            # The verdict saved for each answer is that side's actual
            # decision, which varies per row: a keep→maybe demotion
            # records `maybe` when M3 was right, not `keep`.
            "yes_value": m3_dec.value, "no_value": rule_dec.value,
            "yes": f"M3 对了 · {m3_dec.value}",
            "no": f"规则对了 · {rule_dec.value}",
        })

    if items and len(items) > limit:
        from pixcull.report.review_sheet import stratify
        # keep->cull first (destroying a keeper), then maybe->cull.
        items = stratify(items, limit,
                         priority=("keep->cull", "maybe->cull"))

    if not items:
        console.print("[yellow]Nothing to review.[/yellow] "
                      + (f"{no_verdict} rows had no cached verdict — run "
                         f"`pixcull m3 eval` first." if no_verdict else ""))
        raise typer.Exit(code=1)

    dest = write(
        items, Path(str(out)).expanduser(),
        title=f"M3 推翻硬性剔除 · {len(items)} 张待复核"
              if only == "overrides" else f"M3 与规则分歧 · {len(items)} 张",
        slug="m3-overrides" if only == "overrides" else "m3-disagreements",
        yes_key="keep", no_key="cull",
        lede="这些照片本机检测器判定必须剔除,但 M3 <b>在 prompt 里已经读到了"
             "那些实测值</b>,仍然选择保留。<br>「证据融合」成立与否就压在这批"
             "推翻对不对上 —— <b>只有你能判</b>。判完点「保存结果」,"
             "存成 JSON 再喂给 <code>pixcull m3 eval --review</code>。")
    console.print(f"[green]{len(items)} frames[/green] → {dest}")
    if no_verdict:
        console.print(f"[dim]{no_verdict} rows skipped: no cached verdict "
                      f"(building this page never spends money)[/dim]")
    console.print(f"[dim]open {dest}[/dim]")


@m3_app.command("status")
def m3_status() -> None:
    """Show the recorded capabilities, key presence, and today's spend."""
    from pixcull.llm_budget import snapshot
    from pixcull.scoring.m3 import (
        MODEL, api_key_from_env, capability_path, default_cache_path,
        load_capabilities,
    )

    caps = load_capabilities()
    cache = default_cache_path()
    n_cached = 0
    if cache.exists():
        try:
            n_cached = sum(1 for line in cache.open(encoding="utf-8")
                           if line.strip())
        except OSError:
            pass

    table = Table(title="M3 status")
    table.add_column("", style="bold")
    table.add_column("")
    table.add_row("key", "[green]found[/green]" if api_key_from_env()
                  else "[red]missing[/red]")
    table.add_row("model", MODEL)
    table.add_row("probed", caps.get("probed_at")
                  or "[red]never — run `pixcull m3 doctor`[/red]")
    table.add_row("video shape", caps.get("video_part_shape")
                  or "[dim]unverified[/dim]")
    table.add_row("cached verdicts", f"{n_cached} ({cache})")
    try:
        snap = snapshot()
        table.add_row("spend today",
                      f"¥{snap.get('total_today', 0):.2f} / "
                      f"¥{snap.get('cap_yuan', 0):.2f}")
    except Exception:  # noqa: BLE001
        pass
    console.print(table)
    console.print(f"[dim]capabilities → {capability_path()}[/dim]")


@models_app.command("list")
def models_list() -> None:
    """Show the optional-model catalogue + install state."""
    from pixcull.models_manager import list_models
    rows = list_models()
    table = Table(title=f"PixCull optional models ({len(rows)})")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Size", justify="right", style="dim")
    table.add_column("Used by", style="dim")
    for r in rows:
        if r.installed:
            status = "[green]installed[/green]"
        elif r.spec.published:
            status = "[cyan]available — pull[/cyan]"
        else:
            status = "[dim]unpublished[/dim]"
        size = f"{r.spec.size / 1e6:.1f} MB" if r.spec.size else "—"
        table.add_row(r.spec.name, status, size, r.spec.used_by)
    console.print(table)
    console.print(
        "Cache: [cyan]~/.pixcull/models/[/cyan]  ·  fetch with "
        "[cyan]pixcull models pull <name>[/cyan]")


@models_app.command("pull")
def models_pull(
    name: str = typer.Argument(..., help="Catalogue name, e.g. audio-tagger."),
    force: bool = typer.Option(False, "--force", "-f",
                               help="Re-download even if already cached."),
) -> None:
    """Download + checksum-verify a model into ~/.pixcull/models/."""
    from pixcull.models_manager import pull, ChecksumError, NotPublishedError
    try:
        path = pull(name, force=force)
    except KeyError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)
    except NotPublishedError as exc:
        console.print(f"[yellow]• {exc}[/yellow]")
        raise typer.Exit(code=3)
    except ChecksumError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=4)
    except Exception as exc:  # noqa: BLE001 — network / IO
        console.print(f"[red]✗ download failed: {exc}[/red]")
        raise typer.Exit(code=5)
    console.print(f"[green]✓ {name} → {path}[/green]")


@models_app.command("path")
def models_path(
    name: str = typer.Argument(..., help="Catalogue name, e.g. audio-tagger."),
) -> None:
    """Print a model's local cache path (exit 1 if not installed).

    Scriptable: ``MODEL=$(pixcull models path audio-tagger) && …``.
    """
    from pixcull.models_manager import get_spec, is_installed, resolve_path
    try:
        get_spec(name)
    except KeyError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2)
    print(resolve_path(name))          # plain stdout, no rich markup
    if not is_installed(name):
        raise typer.Exit(code=1)


# v2.4-P0-2 — personal taste profile learned from your own corrections.
personalize_app = typer.Typer(
    help="Learn / show / reset a local taste profile from your keep-cull "
         "corrections (v2.4-P0-2).", no_args_is_help=True)
app.add_typer(personalize_app, name="personalize")

_PROFILE_PATH = Path.home() / ".pixcull" / "personal_profile.json"


@personalize_app.command("learn")
def personalize_learn(
    runs_root: Path = typer.Option(
        Path.home() / ".pixcull" / "runs",
        help="Where your run dirs (annotations.jsonl + scores.csv) live."),
) -> None:
    """Fit a taste profile from your corrections + report held-out
    keep-F1, personalised vs generic."""
    from pixcull.scoring.personal_learn import (
        evaluate, gather_examples_from_runs, learn_profile)
    from pixcull.scoring.personalized import (
        MIN_ANNS_FOR_PERSONALIZATION, save_profile)
    exs = gather_examples_from_runs(runs_root)
    if not exs:
        console.print(f"[yellow]No corrections found under {runs_root}.[/yellow] "
                      "Cull a batch first (1 / 2 / 3), then re-run.")
        raise typer.Exit(code=1)
    prof = learn_profile(exs)
    save_profile(prof, _PROFILE_PATH)
    ev = evaluate(exs)
    console.print(f"[green]✓ learned from {prof.n_annotations} corrections[/green] "
                  f"→ {_PROFILE_PATH}")
    table = Table(title="Your taste")
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_row("keep rate", f"{prof.keep_rate:.0%}")
    table.add_row("threshold shift", f"{prof.keep_threshold_shift:+.3f}")
    table.add_row("most-cared axis", prof.most_cared_axis or "—")
    table.add_row("held-out keep-F1 · generic", f"{ev['generic_f1']:.3f}")
    table.add_row("held-out keep-F1 · personal", f"{ev['personal_f1']:.3f}")
    table.add_row("Δ (personal − generic)", f"{ev['delta']:+.3f}")
    console.print(table)
    if not prof.is_active():
        console.print(
            f"[dim]< {MIN_ANNS_FOR_PERSONALIZATION} corrections — the pipeline "
            "treats personalization as inactive until then.[/dim]")


@personalize_app.command("show")
def personalize_show() -> None:
    """Print the current saved taste profile."""
    from pixcull.scoring.personalized import load_profile
    prof = load_profile(_PROFILE_PATH)
    if prof is None:
        console.print("[yellow]No profile yet.[/yellow] Run "
                      "[cyan]pixcull personalize learn[/cyan].")
        raise typer.Exit(code=1)
    console.print(
        f"[bold]Taste profile[/bold] ({prof.n_annotations} corrections) · "
        f"keep {prof.keep_rate:.0%} · shift {prof.keep_threshold_shift:+.3f} · "
        f"cares most about [cyan]{prof.most_cared_axis or '—'}[/cyan]")


@personalize_app.command("reset")
def personalize_reset() -> None:
    """Delete the saved profile (back to generic scoring)."""
    if _PROFILE_PATH.exists():
        _PROFILE_PATH.unlink()
        console.print("[green]✓ profile reset[/green] — scoring is generic again.")
    else:
        console.print("[dim]No profile to reset.[/dim]")


@app.command(name="dedup-across")
def dedup_across(
    runs: list[Path] = typer.Argument(
        ..., help="Run output dirs, each with embeddings.npz + scores.csv"),
    threshold: float = typer.Option(
        0.92, "--threshold", "-t", help="Cosine floor (0.5–0.999)"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write a JSON report"),
) -> None:
    """Find visually near-duplicate photos that recur ACROSS shoots.

    The cross-session cull: a frame delivered in one shoot that reappears in
    another. Each run dir needs an ``embeddings.npz`` (built by semantic
    search or the near-dup fold); runs without one are skipped with a note.
    """
    import csv
    import json

    import numpy as np

    from pixcull.scoring.near_dup import (
        group_cross_shoot, pick_cross_shoot_heroes)

    shoots: list[tuple[str, list[str], np.ndarray]] = []
    scores: dict[tuple[str, str], float] = {}
    for rd in runs:
        npz = rd / "embeddings.npz"
        if not npz.exists():
            console.print(
                f"[yellow]skip {rd} — no embeddings.npz "
                f"(run semantic search / near-dup first)[/yellow]")
            continue
        data = np.load(npz, allow_pickle=True)
        fns = [str(x) for x in data["filenames"]]
        vecs = np.asarray(data["vectors"], dtype=np.float32)
        sid = rd.parent.name if rd.name == "output" else rd.name
        shoots.append((sid, fns, vecs))
        sc = rd / "scores.csv"
        if sc.exists():
            with open(sc, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    try:
                        scores[(sid, row["filename"])] = float(
                            row.get("score_final") or 0.0)
                    except (ValueError, KeyError, TypeError):
                        pass
    if len(shoots) < 2:
        console.print(
            "[red]Need >=2 runs with embeddings.npz for cross-shoot dedup.[/red]")
        raise typer.Exit(1)

    groups = group_cross_shoot(shoots, threshold=threshold)
    if not groups:
        console.print(
            f"[green]No cross-shoot visual near-dups (threshold {threshold}).[/green]")
        return
    heroes = pick_cross_shoot_heroes(groups, scores)
    table = Table(title=f"Cross-shoot near-dups — {len(groups)} group(s) "
                        f"@ threshold {threshold}")
    table.add_column("#", justify="right")
    table.add_column("keep (hero)")
    table.add_column("duplicates (safe to cull)")
    for i, h in enumerate(heroes, 1):
        hero = f"{h['hero'][0]} / {h['hero'][1]}"
        dups = "\n".join(f"{s} / {f}" for s, f in h["duplicates"])
        table.add_row(str(i), hero, dups)
    console.print(table)
    n_dups = sum(len(h["duplicates"]) for h in heroes)
    console.print(f"[bold]{n_dups} cross-shoot duplicate(s) can be cleaned.[/bold]")

    if output:
        rep = {
            "schema": "pixcull.dedup_across.v1",
            "threshold": threshold,
            "groups": [
                {"hero": list(h["hero"]),
                 "members": [list(m) for m in h["members"]],
                 "duplicates": [list(d) for d in h["duplicates"]]}
                for h in heroes],
        }
        output.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        console.print(f"[dim]report → {output}[/dim]")


@app.command(name="trim-dupes")
def trim_dupes(
    frames_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False,
        help="Dir of extracted video frames (frame_*.jpg)"),
    max_distance: int = typer.Option(
        6, "--max-distance", "-d", help="dHash Hamming floor for 'same frame'"),
    min_run: int = typer.Option(
        2, "--min-run", help="Min consecutive frames to call a static run"),
    keep: str = typer.Option(
        "first", "--keep", help="first | middle | last — frame kept per run"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the JSON trim plan"),
) -> None:
    """Find near-static / duplicate frame runs in an extracted-frames dir.

    A locked-off or paused stretch leaves a run of near-identical frames;
    each run collapses to one representative and the rest are reported as
    trim candidates (reported, never deleted — review before acting).
    """
    import json

    from pixcull.scoring.dup_frames import dhash, trim_plan

    exts = {".jpg", ".jpeg", ".png"}
    frames = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in exts)
    if not frames:
        console.print(f"[red]no frames in {frames_dir}[/red]")
        raise typer.Exit(1)
    ids = [p.name for p in frames]
    hashes = [dhash(p) for p in frames]
    plan = trim_plan(ids, hashes, max_distance=max_distance,
                     min_run=min_run, keep=keep)
    n_drop = len(plan["drop_ids"])
    if not plan["runs"]:
        console.print(
            f"[green]No near-static runs in {len(frames)} frames.[/green]")
        return
    table = Table(title=f"Near-static runs — {len(plan['runs'])} run(s), "
                        f"{n_drop} trimmable / {len(frames)} frames")
    table.add_column("run", justify="right")
    table.add_column("frames")
    table.add_column("keep")
    for i, r in enumerate(plan["runs"], 1):
        span = f"{r['start']}–{r['end']} ({r['end'] - r['start'] + 1})"
        table.add_row(str(i), span, r["keep"])
    console.print(table)
    console.print(
        f"[bold]{n_drop} duplicate frame(s) trimmable[/bold] "
        f"({100 * n_drop // max(1, len(frames))}% of {len(frames)})")
    if output:
        output.write_text(json.dumps(
            {"schema": "pixcull.trim_dupes.v1", "max_distance": max_distance,
             "min_run": min_run, "keep": keep, "n_frames": len(frames), **plan},
            ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]plan → {output}[/dim]")


if __name__ == "__main__":
    app()


@app.command()
def serve(
    port: int = typer.Option(8770, help="Preferred port (auto-falls back if busy)"),
    host: str = typer.Option("127.0.0.1",
                             help="Bind address. 0.0.0.0 exposes to the LAN — "
                                  "no auth, only on networks you trust."),
    root: Optional[Path] = typer.Option(
        None, "--root",
        help="Where runs live (default ~/.pixcull/runs for an installed "
             "PixCull, /tmp/pixcull_demo in a dev checkout)"),
    open_browser: bool = typer.Option(True, "--open/--no-open",
                                      help="Open a browser tab on startup"),
) -> None:
    """v2.31 — launch the review workspace (the keyboard-first culling
    grid, lightbox glass box, compare, XMP export).

    Until now this only ran from a git checkout via
    ``python scripts/serve_demo.py``; the server now ships inside the
    package, so a ``pip install pixcull`` user gets the same UI.
    """
    import sys as _sys

    # serve_app evaluates _DEMO_ROOT from PIXCULL_DEMO_ROOT AT IMPORT TIME,
    # so the env must be set BEFORE the import — setting it afterwards
    # silently served the wrong tree (caught while prepping a real
    # labeling session: --root pointed at runs the server never listed).
    if root is not None:
        os.environ["PIXCULL_DEMO_ROOT"] = str(Path(root).expanduser())
    elif not os.environ.get("PIXCULL_DEMO_ROOT"):
        # A pip-installed user has no /tmp/pixcull_demo convention and no
        # repo; default their runs to a stable home directory instead.
        import importlib.util as _ilu
        _in_checkout = (Path(__file__).resolve().parent.parent
                        / "pyproject.toml").is_file()
        if not _in_checkout:
            os.environ["PIXCULL_DEMO_ROOT"] = str(
                Path.home() / ".pixcull" / "runs")

    from pixcull.report import serve_app

    # serve_app.main() parses sys.argv (argparse) — hand it the flags it
    # expects rather than duplicating its ~30 options here.
    argv = ["pixcull-serve", "--port", str(port), "--host", host]
    if not open_browser:
        argv.append("--no-open")
    _saved, _sys.argv = _sys.argv, argv
    try:
        serve_app.main()
    finally:
        _sys.argv = _saved


# ── v2.32-P0 — cross-run library search ────────────────────────────────
library_app = typer.Typer(
    help="Search every shoot at once (v2.32): build and query a "
         "cross-run semantic index.",
    no_args_is_help=True)
app.add_typer(library_app, name="library")


def _iter_run_dirs(root: Path):
    """Yield (run_id, output_dir) for every run under `root`."""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        out = child / "output"
        if out.is_dir() and (out / "scores.csv").is_file():
            yield child.name, out


@library_app.command("index")
def library_index_cmd(
    root: Optional[Path] = typer.Option(
        None, "--root", help="Runs directory (default: PIXCULL_DEMO_ROOT, "
                             "else ~/.pixcull/runs, else /tmp/pixcull_demo)"),
    library: Optional[Path] = typer.Option(
        None, "--library", help="Index location (default ~/.pixcull/library)"),
    encode_missing: bool = typer.Option(
        False, "--encode-missing",
        help="Also CLIP-encode runs that have no embeddings.npz yet. SLOW "
             "(minutes per thousand photos); off by default so indexing "
             "stays a near-instant copy of caches search already built."),
) -> None:
    """Add every run's photos to the cross-run index.

    Reuses each run's ``output/embeddings.npz`` — the cache per-run
    semantic search already builds — so this is a copy, not a re-encode.
    Idempotent: re-running only picks up new or changed photos.
    """
    from pixcull.scoring import library_index as LX
    from pixcull.scoring.semantic_search import (
        build_embeddings_cache, load_embeddings_cache,
    )

    if root is None:
        env = os.environ.get("PIXCULL_DEMO_ROOT")
        if env:
            root = Path(env)
        elif (Path.home() / ".pixcull" / "runs").is_dir():
            root = Path.home() / ".pixcull" / "runs"
        else:
            root = Path("/tmp/pixcull_demo")
    lib = library or LX.LIBRARY_DIR

    runs = list(_iter_run_dirs(root))
    if not runs:
        console.print(f"[yellow]no runs under {root}[/yellow]")
        raise typer.Exit(0)

    total_added = total_skipped = 0
    for run_id, out_dir in runs:
        cache_path = out_dir / "embeddings.npz"
        cache = load_embeddings_cache(cache_path)
        if cache is None:
            if not encode_missing:
                console.print(
                    f"[dim]{run_id}: no embeddings.npz — skipped "
                    f"(--encode-missing to build it)[/dim]")
                continue
            paths = _resolve_run_images(out_dir)
            if not paths:
                console.print(f"[dim]{run_id}: no readable images[/dim]")
                continue
            console.print(f"[cyan]{run_id}: encoding {len(paths)} photos…[/cyan]")
            cache = build_embeddings_cache(paths, cache_path)

        names = [str(x) for x in cache["filenames"]]
        path_map = _run_path_map(out_dir)      # one pass, not one per photo
        entries, rows = [], []
        for i, fn in enumerate(names):
            p = path_map.get(fn)
            if p is None:
                continue          # can't record a path we can't resolve
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            entries.append((fn, str(p), mtime))
            rows.append(i)
        if not entries:
            console.print(
                f"[dim]{run_id}: {len(names)} vectors but no source photo "
                f"resolved — moved, or an external drive is offline[/dim]")
            continue

        res = LX.append_run(run_id, entries, cache["vectors"][rows],
                            library_dir=lib, model=cache.get("model", ""))
        total_added += res["added"]
        total_skipped += res["skipped"]
        if res["added"]:
            console.print(f"[green]{run_id}: +{res['added']}[/green]"
                          + (f" ({res['skipped']} already indexed)"
                             if res["skipped"] else ""))

    st = LX.status(lib)
    console.print(f"\n[bold]library:[/bold] {st['n_photos']:,} photos · "
                  f"{st['n_runs']} runs · {st['disk_bytes']/1024/1024:.1f} MB"
                  f"  [dim](+{total_added} this pass, "
                  f"{total_skipped} unchanged)[/dim]")


def _run_path_map(out_dir: Path) -> dict[str, Path]:
    """``filename -> absolute source path`` for one run.

    v2.34 — built ONCE per run.  The v2.32 resolvers it replaces read
    manifest.json again for *every* photo, which is one file parse per
    photo on a 20,000-image shoot.

    Sources, most authoritative first:

    1. **scores.csv's own ``path`` column** — what the pipeline actually
       recorded per photo.  This is the only source that works for a
       plain ``pixcull run``, which writes no manifest.json and has no
       sibling ``input/`` directory.  v2.32 didn't consult it, so
       ``pixcull library index`` resolved *nothing* on real CLI runs and
       reported "nothing resolvable" even with vectors present.
    2. ``manifest.json`` — the demo server's filename→path map.
    3. ``<run>/input/<filename>`` — the demo server's on-disk layout.

    Only paths that exist right now are returned: indexing needs an
    mtime, and the library's own ``stale`` state covers photos that go
    missing *after* they were indexed.
    """
    import csv
    import json as _json

    out: dict[str, Path] = {}

    scores = out_dir / "scores.csv"
    if scores.is_file():
        try:
            with scores.open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    fn, p = r.get("filename"), r.get("path")
                    if fn and p:
                        cand = Path(p)
                        if cand.is_file():
                            out[fn] = cand
        except (OSError, ValueError):
            pass

    manifest = out_dir / "manifest.json"
    if manifest.is_file():
        try:
            m = _json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(m, dict):
                for fn, p in m.items():
                    if fn not in out and isinstance(p, str) and Path(p).is_file():
                        out[fn] = Path(p)
        except (OSError, ValueError):
            pass

    inp = out_dir.parent / "input"
    if inp.is_dir():
        for cand in inp.iterdir():
            if cand.name not in out and cand.is_file():
                out[cand.name] = cand

    return out


def _resolve_run_images(out_dir: Path) -> list[Path]:
    """A run's source images, in scores.csv order where available."""
    return list(_run_path_map(out_dir).values())


@library_app.command("status")
def library_status_cmd(
    library: Optional[Path] = typer.Option(None, "--library"),
) -> None:
    """Show index size, run coverage, and how many photos went missing."""
    from pixcull.scoring import library_index as LX
    st = LX.status(library or LX.LIBRARY_DIR)
    console.print(f"[bold]{st['n_photos']:,}[/bold] photos across "
                  f"[bold]{st['n_runs']}[/bold] runs · "
                  f"{st['disk_bytes']/1024/1024:.1f} MB · dim {st['dim']}")
    console.print(f"[dim]{st['library_dir']}[/dim]")
    if st["n_stale"]:
        console.print(
            f"[yellow]{st['n_stale']} photo(s) not on disk right now[/yellow] "
            f"[dim](deleted, moved, or an external drive is offline — they "
            f"stay indexed and come back when the drive does)[/dim]")


@library_app.command("search")
def library_search_cmd(
    query: str = typer.Argument(..., help='e.g. "backlit hands close-up"'),
    k: int = typer.Option(20, "-k", help="How many hits"),
    library: Optional[Path] = typer.Option(None, "--library"),
) -> None:
    """Search across every indexed shoot."""
    from pixcull.scoring import library_index as LX
    from pixcull.scoring.semantic_search import encode_query

    lib = library or LX.LIBRARY_DIR
    if LX.status(lib)["n_photos"] == 0:
        console.print("[yellow]library is empty — run "
                      "`pixcull library index` first[/yellow]")
        raise typer.Exit(1)

    hits = LX.search(encode_query(query), k=k, library_dir=lib)
    if not hits:
        console.print("[dim]no hits[/dim]")
        raise typer.Exit(0)

    table = Table(title=f'library search — "{query}"')
    table.add_column("sim", justify="right")
    table.add_column("run")
    table.add_column("photo")
    table.add_column("")
    for h in hits:
        table.add_row(f"{h['similarity']:.3f}", h["run_id"], h["filename"],
                      "[yellow]missing[/yellow]" if h["stale"] else "")
    console.print(table)


@library_app.command("prune")
def library_prune_cmd(
    run: Optional[str] = typer.Option(
        None, "--run", help="Drop one run's rows instead of the stale ones"),
    library: Optional[Path] = typer.Option(None, "--library"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Remove rows whose photos are gone (or one run's rows)."""
    from pixcull.scoring import library_index as LX
    lib = library or LX.LIBRARY_DIR
    st = LX.status(lib)
    if run is None and st["n_stale"] and not yes:
        console.print(
            f"[yellow]About to drop {st['n_stale']} row(s) whose files "
            f"aren't on disk.[/yellow] If an external drive is merely "
            f"offline, reconnect it instead — pruning loses those entries "
            f"until you re-index. Pass --yes to proceed.")
        raise typer.Exit(1)
    res = LX.prune(lib, run_id=run)
    console.print(f"removed {res['removed']}, {res['remaining']} remaining")


@app.command(name="cut")
def cut(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False,
                                   help="Run dir holding transcript.json"),
    drop_line: list[int] = typer.Option(
        [], "--drop-line", "-d",
        help="Transcript line to strike (0-based, repeatable)"),
    drop_chars: list[str] = typer.Option(
        [], "--drop-chars",
        help="Strike characters within a line: LINE:FIRST-LAST "
             "(0-based, inclusive). Needs an engine that reports "
             "per-character times."),
    source: str = typer.Option("source.mp4", "--source",
                               help="Clip name written into the EDL"),
    fps: float = typer.Option(25.0, "--fps"),
    edl: Optional[Path] = typer.Option(None, "--edl",
                                       help="Write a CMX-3600 EDL here"),
    render: bool = typer.Option(
        False, "--render",
        help="Also cut the source into <run>/edit/edit.mp4 (needs ffmpeg "
             "and the original video still on disk)"),
    crossfade: float = typer.Option(
        None, "--crossfade",
        help="Seconds of dissolve between kept spans. Default 0 — a "
             "dissolve mid-sentence eats the words you kept."),
) -> None:
    """Cut a clip by striking transcript text.

    v2.44 — the counterpart to `transcribe`: that one tells you what was
    said, this one removes it. Deletions are layered over an immutable
    transcript, so `edit.json` is a record of decisions, not a mangled
    copy of the source.
    """
    from pixcull.scoring.edit_model import EditError, EditSession
    from pixcull.scoring.transcribe import load_transcript

    tr = load_transcript(run_dir)
    if tr is None or not tr.segments:
        console.print(
            f"[red]no transcript in {run_dir}[/] "
            f"[dim]— run `pixcull transcribe` first[/dim]")
        raise typer.Exit(code=1)

    sess = EditSession(tr)
    console.print(
        f"[dim]{len(tr.segments)} lines · {sess.duration():.1f}s · "
        f"{sess.precision}-level edits available[/dim]")

    try:
        # Character ranges first: striking a whole line afterwards would
        # make an index the user typed refer to a line that is already
        # gone, and silently cutting the wrong words is the failure this
        # command exists to avoid.
        for spec in drop_chars:
            try:
                line, rng = spec.split(":", 1)
                first, last = rng.split("-", 1)
                sess.delete_chars(int(line), int(first), int(last))
            except ValueError as exc:
                console.print(f"[red]bad --drop-chars {escape(spec)!r}: "
                              f"{escape(str(exc))}[/]")
                raise typer.Exit(code=2) from None
        for i in drop_line:
            sess.delete_segment(i)
    except EditError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(code=2) from None

    (run_dir / "edit.json").write_text(sess.dumps(), encoding="utf-8")
    console.print(f"[green]✓[/] {sess.duration():.1f}s kept "
                  f"({len(sess.kept_spans())} clips)")
    console.print(f"  [dim]{run_dir / 'edit.json'}[/dim]")

    if edl:
        from pixcull.io.reel_assembly import build_edl
        edl.write_text(build_edl(sess.to_clips(), source, fps),
                       encoding="utf-8")
        console.print(f"  [dim]{edl}[/dim]")

    if render:
        from pixcull.io.reel_assembly import (
            EDIT_CROSSFADE_S, FFmpegError, assemble_from_edit,
        )
        xf = EDIT_CROSSFADE_S if crossfade is None else float(crossfade)
        try:
            res = assemble_from_edit(run_dir, crossfade_s=xf)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[red]{escape(str(exc))}[/]")
            raise typer.Exit(code=2) from None
        except FFmpegError as exc:
            console.print(f"[red]render failed:[/] {escape(str(exc))}")
            raise typer.Exit(code=4) from None
        console.print(f"[green]✓[/] {res.duration_s:.1f}s rendered")
        console.print(f"  [dim]{res.mp4_path}[/dim]")
