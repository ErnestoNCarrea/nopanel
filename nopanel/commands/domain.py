"""Domain management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nopanel.config import (
    load_domains_config,
    load_services_config,
    load_users_config,
    save_domains_config,
)
from nopanel.models import Domain, SSLMode, validate_domain

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("add")
def add_domain(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain name"),
    user: str = typer.Option(..., "--user", "-u", help="Owner username"),
    php: str = typer.Option("", "--php", help="PHP version (e.g., 8.2)"),
    ssl: str = typer.Option("none", "--ssl", help="SSL mode: auto, self, none"),
    aliases: str = typer.Option("", "--aliases", help="Comma-separated aliases"),
) -> None:
    """Add a new web domain."""
    if not validate_domain(domain):
        console.print(f"[red]Error:[/red] Invalid domain: {domain}")
        raise typer.Exit(1)

    config = load_domains_config()
    if domain in config.domains:
        console.print(f"[red]Error:[/red] Domain already exists: {domain}")
        raise typer.Exit(1)

    users_config = load_users_config()
    if user not in users_config.users:
        console.print(f"[red]Error:[/red] User does not exist: {user}")
        raise typer.Exit(1)

    try:
        ssl_mode = SSLMode(ssl)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid SSL mode: {ssl}")
        raise typer.Exit(1) from None

    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []

    php_version = php or None
    if php_version:
        services_config = load_services_config()
        if php_version not in services_config.php:
            console.print(
                f"[red]Error:[/red] PHP version {php_version} is not configured."
                " Add it to services first."
            )
            raise typer.Exit(1)

    new_domain = Domain(
        user=user,
        php_version=php_version,
        ssl=ssl_mode,
        aliases=alias_list,
    )

    new_domains = {**config.domains, domain: new_domain}
    new_config = config.model_copy(update={"domains": new_domains})
    save_domains_config(new_config)
    console.print(f"[green]Domain created:[/green] {domain} (run 'nopanel commit' to apply)")


@app.command("mod")
def mod_domain(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain name"),
    php: str = typer.Option("", "--php", help="PHP version"),
    ssl: str = typer.Option("", "--ssl", help="SSL mode: auto, self, none"),
    aliases: str | None = typer.Option(
        None,
        "--aliases",
        help="Comma-separated aliases (pass empty string to clear)",
    ),
) -> None:
    """Modify an existing domain."""
    config = load_domains_config()
    if domain not in config.domains:
        console.print(f"[red]Error:[/red] Domain does not exist: {domain}")
        raise typer.Exit(1)

    d = config.domains[domain]
    updates = {}

    if php:
        php_version = php if php != "none" else None
        if php_version:
            services_config = load_services_config()
            if php_version not in services_config.php:
                console.print(
                    f"[red]Error:[/red] PHP version {php_version} is not"
                    " configured. Add it to services first."
                )
                raise typer.Exit(1)
        updates["php_version"] = php_version
    if ssl:
        try:
            updates["ssl"] = SSLMode(ssl)
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid SSL mode: {ssl}")
            raise typer.Exit(1) from None
    if aliases is not None:
        updates["aliases"] = [a.strip() for a in aliases.split(",") if a.strip()]

    new_domain = d.model_copy(update=updates)
    new_domains = {**config.domains, domain: new_domain}
    new_config = config.model_copy(update={"domains": new_domains})
    save_domains_config(new_config)
    console.print(f"[green]Domain modified:[/green] {domain} (run 'nopanel commit' to apply)")


@app.command("remove")
def remove_domain(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain name"),
) -> None:
    """Remove a domain."""
    config = load_domains_config()
    if domain not in config.domains:
        console.print(f"[red]Error:[/red] Domain does not exist: {domain}")
        raise typer.Exit(1)

    new_domains = {k: v for k, v in config.domains.items() if k != domain}
    new_config = config.model_copy(update={"domains": new_domains})
    save_domains_config(new_config)
    console.print(f"[green]Domain removed:[/green] {domain} (run 'nopanel commit' to apply)")


@app.command("list")
def list_domains() -> None:
    """List all domains."""
    config = load_domains_config()

    table = Table(title="Domains")
    table.add_column("Domain", style="cyan")
    table.add_column("User", style="magenta")
    table.add_column("PHP", style="blue")
    table.add_column("SSL", style="yellow")
    table.add_column("Aliases", style="white")

    for domain_name, d in sorted(config.domains.items()):
        table.add_row(
            domain_name,
            d.user,
            d.php_version or "—",
            d.ssl.value,
            ", ".join(d.aliases) if d.aliases else "—",
        )

    console.print(table)
