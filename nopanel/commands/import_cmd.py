"""Import CLI command — import config from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from nopanel.config import save_config
from nopanel.models import FullConfig

console = Console()
app = typer.Typer()


@app.callback(invoke_without_command=True)
def import_config(
    input_file: Path = typer.Option(..., "--file", "-f", help="JSON file to import"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate without saving"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config"),
) -> None:
    """Import noPanel config from a JSON file."""
    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(1)

    try:
        data = json.loads(input_file.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON: {e}")
        raise typer.Exit(1) from e

    try:
        config = FullConfig.model_validate(data)
    except Exception as e:
        console.print(f"[red]Validation error:[/red] {e}")
        raise typer.Exit(1) from e

    if dry_run:
        console.print("[green]Validation successful (dry run)[/green]")
        console.print(f"  Users: {len(config.users.users)}")
        console.print(f"  Domains: {len(config.domains.domains)}")
        console.print(f"  Databases: {len(config.databases.databases)}")
        return

    from nopanel.config import DEFAULT_CONFIG_DIR, load_config

    existing = load_config(DEFAULT_CONFIG_DIR)
    has_existing = existing.users.users or existing.domains.domains or existing.databases.databases
    if has_existing and not force:
        console.print("[red]Error:[/red] Existing config is not empty. Use --force to overwrite.")
        raise typer.Exit(1)

    save_config(config)

    # Clear committed state so the next commit sees everything as new
    from nopanel.state import get_committed_dir

    committed_dir = get_committed_dir(DEFAULT_CONFIG_DIR)
    if committed_dir.exists():
        import shutil

        shutil.rmtree(committed_dir)

    console.print(f"[green]Config imported from {input_file}[/green]")
    console.print("[yellow]Run 'nopanel commit' to apply changes[/yellow]")
