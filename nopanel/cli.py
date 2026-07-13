"""Main CLI entry point — Typer app with all subcommands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel import __version__

console = Console()
app = typer.Typer(
    name="nopanel",
    help="Containerized web hosting control panel",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    """noPanel v2 — containerized web hosting control panel."""
    if version:
        console.print(f"nopanel v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print("noPanel v2 — containerized web hosting control panel")
        console.print("Run 'nopanel --help' for available commands.")
        raise typer.Exit()


# Register subcommand groups
from nopanel.commands import commit as commit_cmd  # noqa: E402
from nopanel.commands import database as database_cmd  # noqa: E402
from nopanel.commands import domain as domain_cmd  # noqa: E402
from nopanel.commands import export as export_cmd  # noqa: E402
from nopanel.commands import import_cmd as import_cmd  # noqa: E402
from nopanel.commands import migrate as migrate_cmd  # noqa: E402
from nopanel.commands import php as php_cmd  # noqa: E402
from nopanel.commands import service as service_cmd  # noqa: E402
from nopanel.commands import user as user_cmd  # noqa: E402

app.add_typer(user_cmd.app, name="user", help="Manage users")
app.add_typer(domain_cmd.app, name="domain", help="Manage web domains")
app.add_typer(database_cmd.app, name="database", help="Manage databases")
app.add_typer(service_cmd.app, name="service", help="Manage service containers")
app.add_typer(commit_cmd.app, name="commit", help="Apply pending changes")
app.add_typer(export_cmd.app, name="export", help="Export config to JSON")
app.add_typer(import_cmd.app, name="import", help="Import config from JSON")
app.add_typer(migrate_cmd.app, name="migrate", help="Migrate from v1 to v2")
app.add_typer(php_cmd.app, name="php", help="Manage PHP-FPM modules and images")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config"),
) -> None:
    """Initialize noPanel config directory."""

    import shutil

    from nopanel.config import DEFAULT_CONFIG_DIR, init_config_dir
    from nopanel.state import get_committed_dir

    config_dir = DEFAULT_CONFIG_DIR
    if config_dir.exists() and any(config_dir.iterdir()) and not force:
        console.print("[red]Error:[/red] Config directory already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    # Derived directories (relative to config_dir for testability)
    generated_dir = config_dir / "generated"
    pki_dir = config_dir / "pki"

    # With --force, clean up stale state from previous installation
    if force:
        committed_dir = get_committed_dir(config_dir)
        if committed_dir.exists():
            shutil.rmtree(committed_dir)
        if generated_dir.exists():
            shutil.rmtree(generated_dir)

    init_config_dir(config_dir)

    # Create runtime directories for generated configs and SSL certs
    generated_dir.mkdir(parents=True, exist_ok=True)
    pki_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[green]Initialized noPanel config at {config_dir}[/green]")


@app.command()
def status() -> None:
    """Show overall noPanel status."""
    from nopanel.config import load_config
    from nopanel.state import diff_configs, format_diff, load_committed

    try:
        desired = load_config()
        committed = load_committed()
        diff = diff_configs(desired, committed)

        table = Table(title="noPanel Status")
        table.add_column("Component", style="cyan")
        table.add_column("Count", style="magenta")
        table.add_column("Pending Changes", style="yellow")

        table.add_row("Users", str(len(desired.users.users)), str(diff.users.total_changes))
        table.add_row("Domains", str(len(desired.domains.domains)), str(diff.domains.total_changes))
        table.add_row("Databases", str(len(desired.databases.databases)), str(diff.databases.total_changes))
        non_php_services = 1  # web (apache) is always enabled
        if desired.services.mariadb.enabled:
            non_php_services += 1
        if desired.services.valkey.enabled:
            non_php_services += 1
        table.add_row("Services", str(len(desired.services.php) + non_php_services), str(diff.services.total_changes))
        table.add_row("Settings", "—", "yes" if diff.settings_changed else "no")

        console.print(table)

        if not diff.is_empty:
            console.print("\n[yellow]Pending changes:[/yellow]")
            console.print(format_diff(diff))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
