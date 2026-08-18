"""Service management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel.docker_manager import DockerManager
from nopanel.services.base import COMPOSE_FILE

console = Console()
app = typer.Typer(no_args_is_help=True)


def _get_docker() -> DockerManager:
    return DockerManager(compose_file=COMPOSE_FILE)


@app.command("up")
def service_up(
    services: list[str] = typer.Argument(None, help="Services to start (default: all)"),
    build: bool = typer.Option(False, "--build", help="Build images before starting"),
) -> None:
    """Start service containers."""
    docker = _get_docker()
    result = docker.compose_up(services if services else None, build=build)
    if result.success:
        console.print("[green]Services started[/green]")
    else:
        console.print(f"[red]Error:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command("down")
def service_down() -> None:
    """Stop and remove all service containers."""
    docker = _get_docker()
    result = docker.compose_down()
    if result.success:
        console.print("[green]Services stopped[/green]")
    else:
        console.print(f"[red]Error:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command("stop")
def service_stop(
    services: list[str] = typer.Argument(None, help="Services to stop (default: all)"),
) -> None:
    """Stop service containers."""
    docker = _get_docker()
    result = docker.compose_stop(services if services else None)
    if result.success:
        console.print("[green]Services stopped[/green]")
    else:
        console.print(f"[red]Error:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command("restart")
def service_restart(
    services: list[str] = typer.Argument(None, help="Services to restart (default: all)"),
) -> None:
    """Restart service containers."""
    docker = _get_docker()
    result = docker.compose_restart(services if services else None)
    if result.success:
        console.print("[green]Services restarted[/green]")
    else:
        console.print(f"[red]Error:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command("status")
def service_status() -> None:
    """Show status of all service containers."""
    docker = _get_docker()
    running = docker.list_running_services()

    if not running:
        console.print("[yellow]No service containers running[/yellow]")
        return

    table = Table(title="Service Status")
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="green")

    for svc in running:
        table.add_row(svc, "running")

    console.print(table)


@app.command("pull")
def service_pull(
    services: list[str] = typer.Argument(None, help="Services to pull (default: all)"),
) -> None:
    """Pull latest images for service containers."""
    docker = _get_docker()
    result = docker.compose_pull(services if services else None)
    if result.success:
        console.print("[green]Images pulled[/green]")
    else:
        console.print(f"[red]Error:[/red] {result.stderr}")
        raise typer.Exit(1)
