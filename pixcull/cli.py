from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
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
) -> None:
    """Run full culling + scoring pipeline on a folder."""
    from pixcull.pipeline.orchestrator import run_pipeline

    run_pipeline(
        folder, output,
        scene_override=scene,
        strictness=strictness,
        rescorer_mode=rescorer_mode,
        rescorer_path=rescorer_path,
    )


@app.command()
def export(
    project: Path = typer.Argument(..., help="Project SQLite path"),
    fmt: str = typer.Option("xmp", "--format", "-f", help="xmp | csv"),
) -> None:
    """Export ratings to XMP sidecars (Lightroom / C1) or CSV. (V0.5+)"""
    raise typer.Exit(code=1)  # TODO(V0.5)


@app.command()
def bench(
    folder: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Benchmark images-per-second throughput. (V0.5+)"""
    raise typer.Exit(code=1)  # TODO(V0.5)


if __name__ == "__main__":
    app()
