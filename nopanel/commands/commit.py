"""Commit CLI command — apply all pending changes."""

from __future__ import annotations

import typer
from rich.console import Console

from nopanel.commit import CommitEngine
from nopanel.config import DEFAULT_CONFIG_DIR
from nopanel.docker_manager import DockerManager
from nopanel.host_ops import NoOpHostOps, auto_detect_host_ops
from nopanel.services.base import COMPOSE_FILE

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.callback(invoke_without_command=True)
def commit(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show changes without applying"),
    service: str = typer.Option("", "--service", "-s", help="Only commit changes for this service"),
    no_docker: bool = typer.Option(False, "--no-docker", help="Generate configs only, skip Docker operations"),
    no_host: bool = typer.Option(False, "--no-host", help="Skip host operations (user management)"),
) -> None:
    """Apply all pending configuration changes."""
    try:
        if no_host:
            host_ops = NoOpHostOps()
        else:
            host_ops = auto_detect_host_ops(config_dir=DEFAULT_CONFIG_DIR)
        engine = CommitEngine(
            config_dir=DEFAULT_CONFIG_DIR,
            docker_manager=None if no_docker else DockerManager(compose_file=COMPOSE_FILE),
            host_ops=host_ops,
        )
        result = engine.run(dry_run=dry_run, service_filter=service or None)
    except Exception as e:
        console.print(f"[red]Commit failed:[/red] {e}")
        raise typer.Exit(1) from e

    console.print(result.summary)

    if result.errors:
        raise typer.Exit(1)

    if result.generated_files:
        console.print(f"\n[blue]Generated {len(result.generated_files)} config files[/blue]")

    if result.sql_executed:
        console.print(f"[blue]Executed {len(result.sql_executed)} SQL statements[/blue]")

    if result.services_restarted:
        console.print(f"[blue]Restarted services: {', '.join(result.services_restarted)}[/blue]")

    if result.host_commands:
        console.print("\n[yellow]Host commands to run manually (system user management):[/yellow]")
        for cmd in result.host_commands:
            console.print(f"  [bold]{cmd}[/bold]")
