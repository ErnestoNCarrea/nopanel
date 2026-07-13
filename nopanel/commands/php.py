"""PHP module management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel.config import load_config, save_config
from nopanel.models import validate_module_name
from nopanel.services.php import add_module, list_modules, remove_module

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("add-module")
def add_php_module(
    version: str = typer.Option(..., "--version", "-v", help="PHP version (e.g., 8.2)"),
    module: str = typer.Argument(..., help="Module name (prefix with pecl: for PECL extensions)"),
) -> None:
    """Add a PHP module to a PHP version."""
    if not validate_module_name(module):
        console.print(f"[red]Error:[/red] Invalid module name: {module!r}. "
                      "Only alphanumeric, dashes, underscores, and optional 'pecl:' prefix allowed.")
        raise typer.Exit(1)

    config = load_config()
    if version not in config.services.php:
        console.print(f"[red]Error:[/red] PHP version {version} is not configured.")
        raise typer.Exit(1)

    new_config = add_module(config, version, module)
    save_config(new_config)
    console.print(
        f"[green]Module added:[/green] {module} for PHP {version} "
        "(run 'nopanel commit' to rebuild image)"
    )
    console.print(
        "[yellow]Note:[/yellow] Modules are global — all PHP versions "
        "share the same additional_modules list and will be rebuilt."
    )


@app.command("remove-module")
def remove_php_module(
    version: str = typer.Option(..., "--version", "-v", help="PHP version (e.g., 8.2)"),
    module: str = typer.Argument(..., help="Module name"),
) -> None:
    """Remove a PHP module from a PHP version."""
    if not validate_module_name(module):
        console.print(f"[red]Error:[/red] Invalid module name: {module!r}")
        raise typer.Exit(1)

    config = load_config()
    if version not in config.services.php:
        console.print(f"[red]Error:[/red] PHP version {version} is not configured.")
        raise typer.Exit(1)

    new_config = remove_module(config, version, module)
    save_config(new_config)
    console.print(
        f"[green]Module removed:[/green] {module} for PHP {version} "
        "(run 'nopanel commit' to rebuild image)"
    )
    console.print(
        "[yellow]Note:[/yellow] Modules are global — all PHP versions "
        "share the same additional_modules list and will be rebuilt."
    )


@app.command("list-modules")
def list_php_modules(
    version: str = typer.Option(..., "--version", "-v", help="PHP version (e.g., 8.2)"),
) -> None:
    """List configured PHP modules for a version."""
    config = load_config()
    modules = list_modules(config, version)

    if not modules:
        console.print(f"[yellow]No additional modules configured for PHP {version}[/yellow]")
        return

    table = Table(title=f"PHP {version} Modules")
    table.add_column("Module", style="cyan")
    table.add_column("Type", style="magenta")

    for mod in sorted(modules):
        mod_type = "PECL" if mod.startswith("pecl:") else "Core"
        table.add_row(mod, mod_type)

    console.print(table)


@app.command("list-versions")
def list_php_versions() -> None:
    """List configured PHP versions."""
    config = load_config()

    if not config.services.php:
        console.print("[yellow]No PHP versions configured[/yellow]")
        return

    table = Table(title="PHP Versions")
    table.add_column("Version", style="cyan")
    table.add_column("Image", style="blue")
    table.add_column("Custom", style="magenta")

    for version, svc in sorted(config.services.php.items()):
        table.add_row(version, svc.image or f"nopanel/php-{version}:latest", "yes" if svc.custom_image else "no")

    console.print(table)
