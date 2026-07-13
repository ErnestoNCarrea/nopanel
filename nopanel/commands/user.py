"""User management CLI commands."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from nopanel.config import DEFAULT_CONFIG_DIR, load_databases_config, load_domains_config, load_users_config, save_users_config
from nopanel.models import LoginType, User, validate_password, validate_username

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("add")
def add_user(
    username: str = typer.Option(..., "--user", "-u", help="Username"),
    password: str = typer.Option(..., "--password", "-p", help="Password"),
    fullname: str = typer.Option("", "--fullname", help="Full name"),
    email: str = typer.Option("", "--email", help="Email address"),
    login: str = typer.Option("sftp", "--login", help="Login type: ssh, sftp, no"),
    admin: bool = typer.Option(False, "--admin", help="Admin user"),
) -> None:
    """Add a new user."""
    if not validate_username(username):
        console.print(f"[red]Error:[/red] Invalid username: {username}")
        raise typer.Exit(1)

    if not validate_password(password):
        console.print("[red]Error:[/red] Password too short (min 8 characters)")
        raise typer.Exit(1)

    config = load_users_config()
    if username in config.users:
        console.print(f"[red]Error:[/red] User already exists: {username}")
        raise typer.Exit(1)

    try:
        login_type = LoginType(login)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid login type: {login}")
        raise typer.Exit(1)

    new_user = User(
        fullname=fullname,
        email=email,
        login=login_type,
        admin=admin,
        password=password,
    )

    new_users = {**config.users, username: new_user}
    new_config = config.model_copy(update={"users": new_users})
    save_users_config(new_config)
    console.print(f"[green]User created:[/green] {username}")
    console.print("[dim]Run 'nopanel user host-commands' to see the required host commands, then run 'nopanel commit'[/dim]")


@app.command("mod")
def mod_user(
    username: str = typer.Option(..., "--user", "-u", help="Username"),
    password: str = typer.Option("", "--password", "-p", help="New password"),
    fullname: str | None = typer.Option(None, "--fullname", help="Full name (pass empty string to clear)"),
    email: str | None = typer.Option(None, "--email", help="Email address (pass empty string to clear)"),
    login: str | None = typer.Option(None, "--login", help="Login type: ssh, sftp, no"),
    admin: bool | None = typer.Option(None, "--admin/--no-admin", help="Grant or revoke admin privileges"),
) -> None:
    """Modify an existing user."""
    config = load_users_config()
    if username not in config.users:
        console.print(f"[red]Error:[/red] User does not exist: {username}")
        raise typer.Exit(1)

    user = config.users[username]

    updates = {}
    if password:
        if not validate_password(password):
            console.print("[red]Error:[/red] Password too short (min 8 characters)")
            raise typer.Exit(1)
        updates["password"] = password
    if fullname is not None:
        updates["fullname"] = fullname
    if email is not None:
        updates["email"] = email
    if login is not None:
        try:
            updates["login"] = LoginType(login)
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid login type: {login}")
            raise typer.Exit(1)
    if admin is not None:
        updates["admin"] = admin

    new_user = user.model_copy(update=updates)
    new_users = {**config.users, username: new_user}
    new_config = config.model_copy(update={"users": new_users})
    save_users_config(new_config)
    console.print(f"[green]User modified:[/green] {username} (run 'nopanel commit' to apply)")


@app.command("remove")
def remove_user(
    username: str = typer.Option(..., "--user", "-u", help="Username"),
) -> None:
    """Remove a user."""
    config = load_users_config()
    if username not in config.users:
        console.print(f"[red]Error:[/red] User does not exist: {username}")
        raise typer.Exit(1)

    new_users = {k: v for k, v in config.users.items() if k != username}
    new_config = config.model_copy(update={"users": new_users})
    save_users_config(new_config)
    console.print(f"[green]User removed:[/green] {username}")

    # Warn about orphaned domains and databases
    domains = load_domains_config()
    orphaned_domains = [d for d in domains.domains if domains.domains[d].user == username]
    if orphaned_domains:
        console.print(f"[yellow]Warning:[/yellow] User {username} still has domains: {', '.join(orphaned_domains)}")
        console.print("[dim]Remove these domains with 'nopanel domain remove' before committing.[/dim]")

    databases = load_databases_config()
    orphaned_dbs = [db for db in databases.databases if databases.databases[db].user == username]
    if orphaned_dbs:
        console.print(f"[yellow]Warning:[/yellow] User {username} still has databases: {', '.join(orphaned_dbs)}")
        console.print("[dim]Remove these databases with 'nopanel database remove' before committing.[/dim]")

    console.print("[dim]Run 'nopanel user host-commands' to see the required host commands, then run 'nopanel commit'[/dim]")


@app.command("list")
def list_users() -> None:
    """List all users."""
    config = load_users_config()

    table = Table(title="Users")
    table.add_column("Username", style="cyan")
    table.add_column("Full Name", style="white")
    table.add_column("Email", style="blue")
    table.add_column("Login", style="magenta")
    table.add_column("Admin", style="yellow")

    for username, user in sorted(config.users.items()):
        table.add_row(
            username,
            user.fullname,
            user.email,
            user.login.value,
            "yes" if user.admin else "no",
        )

    console.print(table)


@app.command("host-commands")
def host_commands(
    raw: bool = typer.Option(False, "--raw", help="Output plain commands only (for script consumption)"),
    done: bool = typer.Option(False, "--done", help="Clear the pending host commands file"),
) -> None:
    """Show or clear pending system user commands for the host.

    Since noPanel runs inside a container, it cannot directly create,
    modify, or delete system users. The commit engine writes pending
    commands to /etc/nopanel/pending-host-cmds.sh. This command reads
    that file.

    Use --done to clear the file after the host wrapper has executed
    the commands successfully.
    """
    from nopanel.config import DEFAULT_CONFIG_DIR

    pending_file = DEFAULT_CONFIG_DIR / "pending-host-cmds.sh"

    if done:
        if pending_file.exists():
            pending_file.unlink()
            if not raw:
                console.print("[green]Cleared pending host commands.[/green]")
        else:
            if not raw:
                console.print("[green]No pending host commands to clear.[/green]")
        return

    if not pending_file.exists():
        if raw:
            return
        console.print("[green]No pending host commands.[/green]")
        return

    content = pending_file.read_text()

    if raw:
        for line in content.splitlines():
            if line and not line.startswith("#"):
                print(line)
        return

    console.print("[yellow]Pending host commands:[/yellow]\n")
    for line in content.splitlines():
        if line.startswith("#"):
            console.print(f"[dim]{line}[/dim]")
        elif line:
            console.print(f"  [bold]{line}[/bold]")
    console.print("\n[dim]Run 'nopanel host-commands --run' on the host to execute these.[/dim]")
