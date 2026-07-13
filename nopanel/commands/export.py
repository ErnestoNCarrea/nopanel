"""Export CLI command — export all config to a single JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console

from nopanel.config import load_config

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.callback(invoke_without_command=True)
def export(
    output: Path = typer.Option(
        Path("nopanel-export.json"),
        "--output",
        "-o",
        help="Output file path",
    ),
) -> None:
    """Export all noPanel config to a JSON file."""
    config = load_config()
    data = config.model_dump(mode="json")

    output.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.chmod(output, 0o600)
    console.print(f"[green]Config exported to {output}[/green]")
