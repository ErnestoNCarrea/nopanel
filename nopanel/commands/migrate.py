"""Migration CLI command — v1 to v2 in-place migration."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel.docker_manager import DockerManager
from nopanel.migrate import MigrationEngine
from nopanel.services.base import COMPOSE_FILE

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.callback(invoke_without_command=True)
def migrate(
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Check and convert without cutover"
    ),
    pre_check: bool = typer.Option(False, "--pre-check", help="Only run pre-migration checks"),
    service: str | None = typer.Option(
        None,
        "--service",
        help="Migrate a single service (valkey, mariadb, php, apache)",
    ),
    all_services: bool = typer.Option(False, "--all", help="Migrate all services in order"),
    reconvert: bool = typer.Option(
        False, "--reconvert", help="Re-read v1 JSON and regenerate v2 YAML"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show differences between v1 and v2 configs"),
) -> None:
    """Migrate from noPanel v1 to v2 in-place."""
    engine = MigrationEngine(docker_manager=DockerManager(compose_file=COMPOSE_FILE))

    if pre_check:
        result = engine.pre_migration_check()
        _print_pre_check(result)
        if result.errors:
            raise typer.Exit(1)
        return

    result = engine.run(
        dry_run=dry_run,
        service=service,
        all_services=all_services,
        reconvert=reconvert,
        diff=diff,
    )

    # Print detection info
    _print_pre_check(result)

    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for err in result.errors:
            console.print(f"  ! {err}")
        raise typer.Exit(1)

    if result.converted_config:
        cfg = result.converted_config
        console.print("\n[blue]Converted config:[/blue]")
        console.print(f"  Users: {len(cfg.users.users)}")
        console.print(f"  Domains: {len(cfg.domains.domains)}")
        console.print(f"  Databases: {len(cfg.databases.databases)}")
        console.print(f"  PHP versions: {', '.join(sorted(cfg.services.php.keys())) or 'none'}")

    if diff:
        console.print("\n[yellow](diff mode — showing v1 vs v2, no changes applied)[/yellow]")
        return

    if reconvert:
        if dry_run:
            console.print("\n[yellow](dry run — no changes applied)[/yellow]")
        else:
            console.print("\n[green]Configs re-converted from v1 JSON[/green]")
        return

    if result.dry_run:
        console.print("\n[yellow](dry run — no changes applied)[/yellow]")
        return

    if result.step_results:
        console.print("\n[blue]Migration steps:[/blue]")
        for step in result.step_results:
            status = "[green]OK[/green]" if step.success else "[red]FAIL[/red]"
            console.print(f"  {status} {step.service}: {step.message}")

    if result.success:
        console.print("\n[green]Migration complete![/green]")
    else:
        console.print("\n[red]Migration incomplete — see errors above[/red]")
        raise typer.Exit(1)


def _print_pre_check(result) -> None:
    """Print pre-migration check results."""
    table = Table(title="Migration Pre-Check")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="white")

    table.add_row("OS", f"{result.os_detected} ({'RHEL-based' if result.is_rhel else 'NOT RHEL'})")
    table.add_row("v1 detected", "yes" if result.v1_detected else "no")
    if result.v1_version:
        table.add_row("v1 version", result.v1_version)
    if result.mariadb_version:
        table.add_row("MariaDB", result.mariadb_version)
    if result.php_versions:
        table.add_row("PHP versions", ", ".join(result.php_versions))

    console.print(table)
