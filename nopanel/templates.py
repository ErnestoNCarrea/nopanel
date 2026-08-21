"""Template engine — Jinja2 template rendering for generated configs.

All templates live in nopanel/templates/ as .j2 files.
Rendering is a pure function — takes template name + context dict, returns string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"

_env: Environment | None = None


def _get_env() -> Environment:
    """Get or create the Jinja2 environment (singleton)."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(disabled_extensions=("j2", "conf", "yml", "yaml")),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
    return _env


def render_template(template_name: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context.

    Pure function — no side effects (reads template from disk, returns string).

    Args:
        template_name: Path relative to templates/ dir (e.g. "compose/docker-compose.yml.j2")
        context: Variables to pass to the template
    """
    env = _get_env()
    template = env.get_template(template_name)
    return template.render(**context)


def render_compose(
    services: dict[str, Any],
    network_mode: str,
    volumes: list[str] | None = None,
    php_versions: list[str] | None = None,
) -> str:
    """Render the docker-compose.yml for all services.

    Args:
        services: Service config dict (from ServicesConfig.model_dump())
        network_mode: "host" or "bridge"
        volumes: Override volume list (defaults to per-service tailored mounts)
        php_versions: PHP versions to include
    """
    if php_versions is None:
        php_versions = sorted(services.get("php", {}).keys())

    if volumes is None:
        apache_volumes = _apache_volumes()
        php_volumes = _php_volumes()
        mariadb_volumes = _mariadb_volumes()
        valkey_volumes = _valkey_volumes()
    else:
        apache_volumes = php_volumes = mariadb_volumes = valkey_volumes = volumes

    return render_template(
        "compose/docker-compose.yml.j2",
        {
            "services": services,
            "network_mode": network_mode,
            "apache_volumes": apache_volumes,
            "php_volumes": php_volumes,
            "mariadb_volumes": mariadb_volumes,
            "valkey_volumes": valkey_volumes,
            "php_versions": php_versions,
        },
    )


def render_apache_vhost_http(
    domain: str,
    user: str,
    docroot: str,
    aliases: list[str],
    php_socket: str | None,
    log_dir: str,
    email: str = "",
    ssl_mode: str = "none",
) -> str:
    """Render an HTTP Apache vhost config."""
    return render_template(
        "apache/domain.http.conf.j2",
        {
            "domain": domain,
            "user": user,
            "docroot": docroot,
            "aliases": aliases,
            "php_socket": php_socket,
            "log_dir": log_dir,
            "email": email or f"webmaster@{domain}",
            "ssl_mode": ssl_mode,
        },
    )


def render_apache_vhost_https(
    domain: str,
    user: str,
    docroot: str,
    aliases: list[str],
    php_socket: str | None,
    log_dir: str,
    email: str = "",
    ssl_cert: str = "",
    ssl_key: str = "",
) -> str:
    """Render an HTTPS Apache vhost config."""
    return render_template(
        "apache/domain.https.conf.j2",
        {
            "domain": domain,
            "user": user,
            "docroot": docroot,
            "aliases": aliases,
            "php_socket": php_socket,
            "log_dir": log_dir,
            "email": email or f"webmaster@{domain}",
            "ssl_cert": ssl_cert,
            "ssl_key": ssl_key,
        },
    )


def render_mod_md_config(
    domains: list[str],
    admin_email: str,
    ca_url: str = "https://acme-v02.api.letsencrypt.org/directory",
) -> str:
    """Render mod_md configuration for automatic ACME SSL."""
    return render_template(
        "apache/mod_md.conf.j2",
        {
            "domains": domains,
            "admin_email": admin_email,
            "ca_url": ca_url,
        },
    )


def render_php_fpm_pool(
    domain: str,
    user: str,
    socket_path: str,
    php_version: str,
) -> str:
    """Render a PHP-FPM pool configuration."""
    return render_template(
        "php-fpm/pool.conf.j2",
        {
            "domain": domain,
            "user": user,
            "socket_path": socket_path,
            "php_version": php_version,
        },
    )


def render_httpd_base(modules: list[str] | None = None) -> str:
    """Render the base Apache httpd config with LoadModule directives."""
    if modules is None:
        modules = ["md", "proxy", "proxy_fcgi", "rewrite", "ssl"]
    return render_template(
        "apache/httpd.conf.j2",
        {"modules": modules},
    )


def render_php_dockerfile(
    php_version: str,
    core_extensions: list[str] | None = None,
    pecl_extensions: list[str] | None = None,
) -> str:
    """Render a custom PHP-FPM Dockerfile."""
    if core_extensions is None:
        core_extensions = ["mysqli", "pdo", "pdo_mysql", "gd", "intl", "opcache", "bcmath", "zip"]
    if pecl_extensions is None:
        pecl_extensions = ["redis", "apcu"]
    return render_template(
        "php/Dockerfile.j2",
        {
            "php_version": php_version,
            "core_extensions": core_extensions,
            "pecl_extensions": pecl_extensions,
        },
    )


# ---------------------------------------------------------------------------
# Default volume mounts
# ---------------------------------------------------------------------------


def _default_volumes() -> list[str]:
    """Return the standard volume mounts (used as fallback)."""
    return [
        "/home:/home:rw",
        "/var/lib/mysql:/var/lib/mysql:rw",
        "/etc/nopanel:/etc/nopanel:rw",
        "/etc/nopanel/generated/apache:/usr/local/apache2/conf.d:ro",
        "/etc/nopanel/generated/php-fpm:/usr/local/etc/php-fpm.d:ro",
        "/var/run:/var/run:rw",
        "/var/log/nopanel/apache:/var/log/apache2:rw",
        "/var/log/nopanel/apache/domains:/var/log/apache2/domains:rw",
        "/etc/nopanel/pki:/usr/local/apache2/md:rw",
    ]


def _apache_volumes() -> list[str]:
    """Volume mounts for the Apache container."""
    return [
        "/home:/home:rw",
        "/etc/nopanel/generated/apache:/usr/local/apache2/conf.d:ro",
        "/var/run:/var/run:rw",
        "/var/log/nopanel/apache:/var/log/apache2:rw",
        "/var/log/nopanel/apache/domains:/var/log/apache2/domains:rw",
        "/etc/nopanel/pki:/usr/local/apache2/md:rw",
    ]


def _php_volumes() -> list[str]:
    """Volume mounts for PHP-FPM containers."""
    return [
        "/home:/home:rw",
        "/etc/passwd:/etc/passwd:ro",
        "/etc/group:/etc/group:ro",
        "/etc/nopanel/generated/php-fpm:/usr/local/etc/php-fpm.d:ro",
        "/var/run:/var/run:rw",
        "/var/log/nopanel/apache/domains:/var/log/apache2/domains:rw",
    ]


def _mariadb_volumes() -> list[str]:
    """Volume mounts for the MariaDB container."""
    return [
        "/var/lib/mysql:/var/lib/mysql:rw",
    ]


def _valkey_volumes() -> list[str]:
    """Volume mounts for the Valkey container."""
    return [
        "/var/run:/var/run:rw",
    ]
