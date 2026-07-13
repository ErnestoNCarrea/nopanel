"""PHP-FPM service — pool config generation and custom image management.

Pure functions for generating PHP-FPM pool configs and Dockerfiles.
Image building is delegated to DockerManager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nopanel.models import FullConfig
from nopanel.services.base import php_socket_path
from nopanel.templates import render_php_dockerfile, render_php_fpm_pool


def generate_pool_configs(config: FullConfig) -> dict[str, str]:
    """Generate PHP-FPM pool config files for all domains with PHP.

    Returns dict mapping relative paths to file contents.
    Pure function — no side effects.
    """
    files: dict[str, str] = {}

    for domain_name, domain in config.domains.domains.items():
        if not domain.php_version:
            continue

        socket = php_socket_path(domain.php_version)
        pool_conf = render_php_fpm_pool(
            domain=domain_name,
            user=domain.user,
            socket_path=socket,
            php_version=domain.php_version,
        )
        # Group pools by PHP version directory, one file per domain
        version_dir = domain.php_version.replace(".", "")
        files[f"php-fpm/php{version_dir}/{domain_name}.conf"] = pool_conf

    return files


def generate_dockerfiles(config: FullConfig) -> dict[str, str]:
    """Generate Dockerfiles for each PHP version.

    Returns dict mapping relative paths to Dockerfile contents.
    Pure function — no side effects.
    """
    files: dict[str, str] = {}

    # Get PHP versions from services config
    php_versions = sorted(config.services.php.keys())

    # Get additional modules from global config
    additional_modules = config.nopanel.php.additional_modules

    # Default core extensions
    core_extensions = [
        "mysqli",
        "pdo",
        "pdo_mysql",
        "gd",
        "intl",
        "opcache",
        "bcmath",
        "zip",
    ]

    # Default PECL extensions
    pecl_extensions = ["redis", "apcu"]

    # Add additional modules (assume they're core extensions unless prefixed with pecl:)
    for mod in additional_modules:
        if mod.startswith("pecl:"):
            ext = mod[5:]
            if ext not in pecl_extensions:
                pecl_extensions.append(ext)
        elif mod not in core_extensions:
            core_extensions.append(mod)

    for version in php_versions:
        dockerfile = render_php_dockerfile(
            php_version=version,
            core_extensions=core_extensions,
            pecl_extensions=pecl_extensions,
        )
        files[f"docker/php-{version}/Dockerfile"] = dockerfile

    return files


class PHPFpmServiceManager:
    """PHP-FPM service manager for a specific PHP version."""

    def __init__(self, version: str, docker_manager: Any = None) -> None:
        self.version = version
        self._docker = docker_manager

    @property
    def name(self) -> str:
        return f"php-{self.version}"

    @property
    def container_name(self) -> str:
        return f"nopanel-php-{self.version}"

    @property
    def image_tag(self) -> str:
        return f"nopanel/php-{self.version}:latest"

    def generate_config(self, config: FullConfig) -> dict[str, str]:
        """Generate pool configs for this PHP version only."""
        files: dict[str, str] = {}

        for domain_name, domain in config.domains.domains.items():
            if domain.php_version != self.version:
                continue

            socket = php_socket_path(self.version)
            pool_conf = render_php_fpm_pool(
                domain=domain_name,
                user=domain.user,
                socket_path=socket,
                php_version=self.version,
            )
            version_nodot = self.version.replace(".", "")
            files[f"php-fpm/php{version_nodot}/{domain_name}.conf"] = pool_conf

        return files

    def start(self) -> Any:
        if self._docker:
            return self._docker.compose_up([self.name])
        return None

    def stop(self) -> Any:
        if self._docker:
            return self._docker.compose_stop([self.name])
        return None

    def restart(self) -> Any:
        if self._docker:
            return self._docker.compose_restart([self.name])
        return None

    def status(self) -> dict[str, Any]:
        if self._docker:
            return self._docker.get_container_status(self.name) or {}
        return {}

    def build_image(self, dockerfile_dir: Path) -> Any:
        """Build the custom PHP Docker image."""
        if self._docker:
            return self._docker.build_image(
                dockerfile_dir=dockerfile_dir,
                tag=self.image_tag,
            )
        return None


def add_module(
    config: FullConfig,
    php_version: str,
    module: str,
) -> FullConfig:
    """Add a PHP module to the config. Returns a new FullConfig (immutable).

    Note: php_version is currently ignored — modules are global, not per-version.
    All PHP versions share the same additional_modules list and are rebuilt
    with the same extensions.
    """
    current_modules = list(config.nopanel.php.additional_modules)
    if module not in current_modules:
        current_modules.append(module)

    new_php = config.nopanel.php.model_copy(update={"additional_modules": current_modules})
    new_nopanel = config.nopanel.model_copy(update={"php": new_php})
    return config.model_copy(update={"nopanel": new_nopanel})


def remove_module(
    config: FullConfig,
    php_version: str,
    module: str,
) -> FullConfig:
    """Remove a PHP module from the config. Returns a new FullConfig (immutable).

    Note: php_version is currently ignored — modules are global, not per-version.
    """
    current_modules = [m for m in config.nopanel.php.additional_modules if m != module]

    new_php = config.nopanel.php.model_copy(update={"additional_modules": current_modules})
    new_nopanel = config.nopanel.model_copy(update={"php": new_php})
    return config.model_copy(update={"nopanel": new_nopanel})


def list_modules(config: FullConfig, php_version: str) -> list[str]:
    """List configured PHP modules for a version.

    Note: php_version is currently ignored — modules are global, not per-version.
    """
    return list(config.nopanel.php.additional_modules)
