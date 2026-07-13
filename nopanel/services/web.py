"""Apache web service — vhost generation and mod_md config.

Pure functions for generating Apache configs from domain config.
Side-effectful operations (start/stop) are delegated to DockerManager.
"""

from __future__ import annotations

from typing import Any

from nopanel.models import FullConfig, SSLMode
from nopanel.services.base import (
    docroot_path,
    domain_log_dir,
    php_socket_path,
    self_signed_cert_path,
    self_signed_key_path,
)
from nopanel.templates import (
    render_apache_vhost_http,
    render_apache_vhost_https,
    render_httpd_base,
    render_mod_md_config,
)


def generate_vhost_configs(config: FullConfig) -> dict[str, str]:
    """Generate all Apache vhost config files from domain config.

    Returns dict mapping relative paths to file contents.
    Pure function — no side effects.
    """
    files: dict[str, str] = {}

    # Base httpd.conf — use modules from web service config
    files["apache/httpd.conf"] = render_httpd_base(
        modules=config.services.web.modules
    )

    # mod_md config for auto-SSL domains
    auto_ssl_domains = [
        name for name, domain in config.domains.domains.items() if domain.ssl == SSLMode.AUTO
    ]
    if auto_ssl_domains:
        files["apache/mod_md.conf"] = render_mod_md_config(
            domains=auto_ssl_domains,
            admin_email=config.nopanel.settings.admin_email,
        )

    # Per-domain vhosts
    for domain_name, domain in config.domains.domains.items():
        user_email = config.users.users.get(domain.user)
        email = user_email.email if user_email else ""

        php_sock = None
        if domain.php_version:
            php_sock = php_socket_path(domain.php_version)

        docroot = docroot_path(domain.user, domain_name, domain.docroot)
        log_dir = domain_log_dir()

        # HTTP vhost
        http_conf = render_apache_vhost_http(
            domain=domain_name,
            user=domain.user,
            docroot=docroot,
            aliases=domain.aliases,
            php_socket=php_sock,
            log_dir=log_dir,
            email=email,
            ssl_mode=domain.ssl.value,
        )
        files[f"apache/domains/{domain_name}.http.conf"] = http_conf

        # HTTPS vhost (only for SSL-enabled domains)
        if domain.ssl in (SSLMode.AUTO, SSLMode.SELF):
            ssl_cert = ""
            ssl_key = ""
            if domain.ssl == SSLMode.SELF:
                ssl_cert = self_signed_cert_path(domain_name)
                ssl_key = self_signed_key_path(domain_name)
            https_conf = render_apache_vhost_https(
                domain=domain_name,
                user=domain.user,
                docroot=docroot,
                aliases=domain.aliases,
                php_socket=php_sock,
                log_dir=log_dir,
                email=email,
                ssl_cert=ssl_cert,
                ssl_key=ssl_key,
            )
            files[f"apache/domains/{domain_name}.https.conf"] = https_conf

    return files


class WebService:
    """Apache web service manager."""

    def __init__(self, docker_manager: Any = None) -> None:
        self._docker = docker_manager

    @property
    def name(self) -> str:
        return "apache"

    def generate_config(self, config: FullConfig) -> dict[str, str]:
        return generate_vhost_configs(config)

    def start(self) -> Any:
        if self._docker:
            return self._docker.compose_up(["apache"])
        return None

    def stop(self) -> Any:
        if self._docker:
            return self._docker.compose_stop(["apache"])
        return None

    def restart(self) -> Any:
        if self._docker:
            return self._docker.compose_restart(["apache"])
        return None

    def status(self) -> dict[str, Any]:
        if self._docker:
            return self._docker.get_container_status("apache") or {}
        return {}
