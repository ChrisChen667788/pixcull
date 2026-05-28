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


if __name__ == "__main__":
    app()
