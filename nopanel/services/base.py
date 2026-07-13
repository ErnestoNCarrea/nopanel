"""Base service protocol and shared utilities.

Service modules implement the Service protocol for generating configs,
starting/stopping containers, and managing their lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from nopanel.models import FullConfig


@runtime_checkable
class Service(Protocol):
    """Protocol for service modules."""

    @property
    def name(self) -> str:
        """Service name (e.g., 'apache', 'php-8.2', 'mariadb', 'valkey')."""
        ...

    def generate_config(self, config: FullConfig) -> dict[str, str]:
        """Generate config files for this service.

        Returns a dict mapping relative file paths to file contents.
        The caller writes these to the generated/ directory.
        """
        ...

    def start(self) -> Any:
        """Start the service container."""
        ...

    def stop(self) -> Any:
        """Stop the service container."""
        ...

    def status(self) -> dict[str, Any]:
        """Get service status."""
        ...


# ---------------------------------------------------------------------------
# Shared paths and constants
# ---------------------------------------------------------------------------

GENERATED_DIR = Path("/etc/nopanel/generated")
APACHE_CONF_DIR = GENERATED_DIR / "apache"
APACHE_DOMAINS_DIR = APACHE_CONF_DIR / "domains"
PHP_FPM_CONF_DIR = GENERATED_DIR / "php-fpm"
COMPOSE_FILE = GENERATED_DIR / "docker-compose.yml"

PKI_DIR = Path("/etc/nopanel/pki")
SELF_SIGNED_DIR = PKI_DIR / "self"

# Path inside the Apache container (PKI_DIR is mounted at /usr/local/apache2/md)
APACHE_MD_DIR = "/usr/local/apache2/md"

# Alpine PHP-FPM socket path pattern (php:X-fpm-alpine containers)
PHP_FPM_SOCKET_PATTERN = "/var/run/php-fpm/php{version_nodot}-www.sock"


def php_socket_path(php_version: str) -> str:
    """Get the PHP-FPM socket path for a given PHP version.

    Uses Alpine path convention: /var/run/php-fpm/php82-www.sock
    (php:X-fpm-alpine containers)
    """
    version_nodot = php_version.replace(".", "")
    return PHP_FPM_SOCKET_PATTERN.format(version_nodot=version_nodot)


def docroot_path(user: str, domain: str, docroot: str = "public_html") -> str:
    """Get the document root path for a domain.

    Args:
        user: Username
        domain: Domain name
        docroot: Document root relative to /home/$user/web/$domain/
    """
    return f"/home/{user}/web/{domain}/{docroot}"


def domain_log_dir() -> str:
    """Get the log directory for domain logs (container-side path).

    Host /var/log/nopanel/apache is mounted at /var/log/apache2 in containers.
    Vhost configs are read inside the container, so they must use the container path.
    """
    return "/var/log/apache2"


def self_signed_cert_path(domain: str) -> str:
    """Get the container-side SSL certificate path for a self-signed domain."""
    return f"{APACHE_MD_DIR}/self/{domain}.crt"


def self_signed_key_path(domain: str) -> str:
    """Get the container-side SSL key path for a self-signed domain."""
    return f"{APACHE_MD_DIR}/self/{domain}.key"
