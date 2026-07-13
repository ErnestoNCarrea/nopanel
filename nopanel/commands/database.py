"""Database management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel.config import load_databases_config, load_users_config, save_databases_config
from nopanel.models import Database, validate_db_name, validate_password

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("add")
def add_database(
    user: str = typer.Option(..., "--user", "-u", help="Owner username"),
    db: str = typer.Option(..., "--db", help="Database name"),
    dbuser: str = typer.Option("", "--dbuser", help="Database username (defaults to db name)"),
    password: str = typer.Option(..., "--password", "-p", help="Database password"),
) -> None:
    """Add a new database."""
    if not validate_db_name(db):
        console.print(f"[red]Error:[/red] Invalid database name: {db}")
        raise typer.Exit(1)

    if not validate_password(password):
        console.print("[red]Error:[/red] Password too short (min 8 characters)")
        raise typer.Exit(1)

    full_name = f"{user}_{db}"
    dbuser = dbuser or db

    users_config = load_users_config()
    if user not in users_config.users:
        console.print(f"[red]Error:[/red] User does not exist: {user}")
        raise typer.Exit(1)

    config = load_databases_config()
    if full_name in config.databases:
        console.print(f"[red]Error:[/red] Database already exists: {full_name}")
        raise typer.Exit(1)

    new_db = Database(user=user, dbuser=dbuser, password=password)
    new_databases = {**config.databases, full_name: new_db}
    new_config = config.model_copy(update={"databases": new_databases})
    save_databases_config(new_config)
    console.print(f"[green]Database created:[/green] {full_name} (run 'nopanel commit' to apply)")


@app.command("mod")
def mod_database(
    user: str = typer.Option(..., "--user", "-u", help="Owner username"),
    db: str = typer.Option(..., "--db", help="Database name"),
    dbuser: str = typer.Option("", "--dbuser", help="New database username"),
    password: str = typer.Option("", "--password", "-p", help="New password"),
) -> None:
    """Modify an existing database."""
    full_name = f"{user}_{db}"

    config = load_databases_config()
    if full_name not in config.databases:
        console.print(f"[red]Error:[/red] Database does not exist: {full_name}")
        raise typer.Exit(1)

    d = config.databases[full_name]
    updates = {}

    if dbuser:
        updates["dbuser"] = dbuser
    if password:
        if not validate_password(password):
            console.print("[red]Error:[/red] Password too short (min 8 characters)")
            raise typer.Exit(1)
        updates["password"] = password

    new_db = d.model_copy(update=updates)
    new_databases = {**config.databases, full_name: new_db}
    new_config = config.model_copy(update={"databases": new_databases})
    save_databases_config(new_config)
    console.print(f"[green]Database modified:[/green] {full_name} (run 'nopanel commit' to apply)")


@app.command("remove")
def remove_database(
    user: str = typer.Option(..., "--user", "-u", help="Owner username"),
    db: str = typer.Option(..., "--db", help="Database name"),
) -> None:
    """Remove a database."""
    full_name = f"{user}_{db}"

    config = load_databases_config()
    if full_name not in config.databases:
        console.print(f"[red]Error:[/red] Database does not exist: {full_name}")
        raise typer.Exit(1)

    new_databases = {k: v for k, v in config.databases.items() if k != full_name}
    new_config = config.model_copy(update={"databases": new_databases})
    save_databases_config(new_config)
    console.print(f"[green]Database removed:[/green] {full_name} (run 'nopanel commit' to apply)")


@app.command("list")
def list_databases() -> None:
    """List all databases."""
    config = load_databases_config()

    table = Table(title="Databases")
    table.add_column("Name", style="cyan")
    table.add_column("User", style="magenta")
    table.add_column("DB User", style="blue")

    for db_name, d in sorted(config.databases.items()):
        table.add_row(db_name, d.user, d.dbuser)

    console.print(table)
