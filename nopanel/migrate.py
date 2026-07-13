"""Migration engine — v1 to v2 in-place migration.

RHEL-only support. Detects v1 installation, converts configs,
stops host services, starts containers, verifies.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from nopanel.config import (
    DEFAULT_CONFIG_DIR,
    convert_v1_databases,
    convert_v1_domains,
    convert_v1_modules,
    convert_v1_nopanel,
    convert_v1_users,
    read_v1_modules,
    read_v1_nopanel,
    read_v1_user_databases,
    read_v1_user_domains,
    read_v1_users,
    save_config,
)
from nopanel.models import FullConfig

logger = logging.getLogger(__name__)

HOME_DIR = Path("/home")

# RHEL service names
RHEL_SERVICES = {
    "apache": "httpd",
    "mariadb": "mariadb",
    "valkey": "valkey",
    "php_fpm_prefix": "php{version_nodot}-php-fpm",
}

# Migration order
MIGRATION_ORDER = ["valkey", "mariadb", "php", "apache"]


# ---------------------------------------------------------------------------
# Protocols for injectable system operations
# ---------------------------------------------------------------------------


class SystemOps(Protocol):
    """Protocol for system operations (injectable for testing)."""

    def detect_os(self) -> str: ...
    def stop_service(self, service: str) -> bool: ...
    def start_service(self, service: str) -> bool: ...
    def disable_service(self, service: str) -> bool: ...
    def get_mariadb_version(self) -> str | None: ...
    def get_installed_php_versions(self) -> list[str]: ...
    def get_v1_user_list(self) -> list[str]: ...


class RealSystemOps:
    """Default system operations using subprocess."""

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        self.config_dir = config_dir

    def detect_os(self) -> str:
        try:
            content = Path("/etc/os-release").read_text()
            for line in content.splitlines():
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip('"').strip("'")
        except FileNotFoundError:
            pass
        return "unknown"

    def stop_service(self, service: str) -> bool:
        result = subprocess.run(["systemctl", "stop", service], capture_output=True)
        return result.returncode == 0

    def start_service(self, service: str) -> bool:
        result = subprocess.run(["systemctl", "start", service], capture_output=True)
        return result.returncode == 0

    def disable_service(self, service: str) -> bool:
        result = subprocess.run(["systemctl", "disable", service], capture_output=True)
        return result.returncode == 0

    def get_mariadb_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["mysql", "--version"], capture_output=True, text=True
            )
            if result.returncode == 0:
                # Parse "mysql  Ver 15.1 Distrib 10.11.8-MariaDB ..."
                for part in result.stdout.split():
                    if "MariaDB" in part or (part and part[0].isdigit()):
                        # Extract version like 10.11.8
                        ver = part.split("-")[0]
                        if ver and ver[0].isdigit():
                            return ver
        except FileNotFoundError:
            pass
        return None

    def get_installed_php_versions(self) -> list[str]:
        versions: list[str] = []
        try:
            result = subprocess.run(
                ["rpm", "-qa"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "-php-fpm" in line and line.startswith("php"):
                    # Extract version from package name like php82-php-fpm
                    parts = line.split("-")
                    if parts[0].startswith("php") and len(parts[0]) > 3:
                        ver_str = parts[0][3:]  # e.g., "82"
                        if len(ver_str) >= 2:
                            version = f"{ver_str[0]}.{ver_str[1:]}"
                            if version not in versions:
                                versions.append(version)
        except FileNotFoundError:
            pass
        return sorted(versions)

    def get_v1_user_list(self) -> list[str]:
        v1_users = read_v1_users(self.config_dir)
        return list(v1_users.keys())


# ---------------------------------------------------------------------------
# Migration result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationStepResult:
    service: str
    success: bool
    message: str
    host_service_stopped: bool = False
    container_started: bool = False


@dataclass(frozen=True)
class MigrationResult:
    os_detected: str
    is_rhel: bool
    v1_detected: bool
    v1_version: str = ""
    mariadb_version: str = ""
    php_versions: list[str] = field(default_factory=list)
    converted_config: FullConfig | None = None
    step_results: list[MigrationStepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return not self.errors and all(r.success for r in self.step_results)


# ---------------------------------------------------------------------------
# Migration engine
# ---------------------------------------------------------------------------


RHEL_VARIANTS = {"rhel", "centos", "almalinux", "rocky", "fedora"}


def is_rhel_based(os_id: str) -> bool:
    """Check if OS is RHEL-based."""
    return os_id.lower() in RHEL_VARIANTS


class MigrationEngine:
    """Orchestrates v1 → v2 migration."""

    def __init__(
        self,
        config_dir: Path = DEFAULT_CONFIG_DIR,
        home_dir: Path = HOME_DIR,
        system_ops: SystemOps | None = None,
        docker_manager: Any = None,
        file_writer: Any = None,
    ) -> None:
        self.config_dir = config_dir
        self.home_dir = home_dir
        self.sysops = system_ops or RealSystemOps(config_dir=config_dir)
        self.docker = docker_manager
        self.file_writer = file_writer

    def detect_v1(self) -> tuple[bool, str]:
        """Detect if v1 is installed. Returns (found, version)."""
        nopanel_json = self.config_dir / "nopanel.json"
        if not nopanel_json.exists():
            return False, ""
        v1_data = read_v1_nopanel(self.config_dir)
        version = v1_data.get("version", "1")
        return True, str(version)

    def pre_migration_check(self) -> MigrationResult:
        """Run pre-migration checks. Returns a MigrationResult with detection info."""
        os_id = self.sysops.detect_os()
        rhel = is_rhel_based(os_id)
        v1_found, v1_version = self.detect_v1()
        mariadb_ver = self.sysops.get_mariadb_version() or ""
        php_vers = self.sysops.get_installed_php_versions()

        errors: list[str] = []
        if not rhel:
            errors.append(
                f"Migration only supports RHEL-based hosts. Detected: {os_id}. "
                "Aborting. v2 can run on any Docker host, but migration requires RHEL."
            )
        if not v1_found:
            errors.append("v1 installation not found. No nopanel.json in /etc/nopanel/.")

        return MigrationResult(
            os_detected=os_id,
            is_rhel=rhel,
            v1_detected=v1_found,
            v1_version=v1_version,
            mariadb_version=mariadb_ver,
            php_versions=php_vers,
            errors=errors,
            dry_run=True,
        )

    def convert_configs(self) -> FullConfig:
        """Convert all v1 configs to v2 format. Pure function (reads files only)."""
        # Read v1 global config
        v1_nopanel = read_v1_nopanel(self.config_dir)

        # Read and convert users
        v1_users = read_v1_users(self.config_dir)
        users_config = convert_v1_users(v1_users)

        nopanel_config = convert_v1_nopanel(v1_nopanel, v1_users)

        # Read and convert per-user domains and databases
        all_domains: dict[str, dict[str, Any]] = {}
        all_databases: dict[str, dict[str, Any]] = {}

        for username in v1_users.keys():
            user_home = self.home_dir / username
            if not user_home.exists():
                logger.warning("User home not found: %s", user_home)
                continue

            v1_domains = read_v1_user_domains(user_home)
            if v1_domains:
                all_domains[username] = v1_domains

            v1_dbs = read_v1_user_databases(user_home)
            if v1_dbs:
                all_databases[username] = v1_dbs

        domains_config = convert_v1_domains(all_domains)
        databases_config = convert_v1_databases(all_databases)

        # Read and convert modules (services)
        v1_modules = read_v1_modules(self.config_dir)
        services_config = convert_v1_modules(v1_modules)

        # Add detected PHP versions if not in modules
        detected_php = self.sysops.get_installed_php_versions()
        for ver in detected_php:
            if ver not in services_config.php:
                from nopanel.models import PHPFpmService
                new_php = {**services_config.php, ver: PHPFpmService()}
                services_config = services_config.model_copy(update={"php": new_php})

        # Set MariaDB version in image if detected
        mariadb_ver = self.sysops.get_mariadb_version()
        if mariadb_ver:
            from nopanel.models import MariaDBService
            # Map version to image tag
            if mariadb_ver.startswith(("10.", "11.")):
                parts = mariadb_ver.split(".")
                image = f"mariadb:{parts[0]}.{parts[1]}"
            else:
                image = "mariadb:lts"
            services_config = services_config.model_copy(
                update={"mariadb": MariaDBService(image=image, root_password=services_config.mariadb.root_password)}
            )

        return FullConfig(
            nopanel=nopanel_config,
            users=users_config,
            domains=domains_config,
            databases=databases_config,
            services=services_config,
        )

    def migrate_service(self, service: str) -> MigrationStepResult:
        """Migrate a single service: stop host, start container."""
        host_service_name = self._get_host_service_name(service)

        # Stop host service
        stopped = self.sysops.stop_service(host_service_name)
        if not stopped:
            return MigrationStepResult(
                service=service,
                success=False,
                message=f"Failed to stop host service: {host_service_name}",
            )

        # Disable host service (prevent auto-start on reboot)
        self.sysops.disable_service(host_service_name)

        # Start container
        container_started = False
        if self.docker:
            result = self.docker.compose_up([service], detach=True)
            container_started = result.success
            if not container_started:
                return MigrationStepResult(
                    service=service,
                    success=False,
                    message=f"Failed to start container: {result.stderr}",
                    host_service_stopped=True,
                )
        else:
            logger.warning("No Docker manager, skipping container start for %s", service)

        return MigrationStepResult(
            service=service,
            success=True,
            message=f"Migrated {service}: host service stopped, container started",
            host_service_stopped=True,
            container_started=container_started,
        )

    def run(
        self,
        dry_run: bool = False,
        service: str | None = None,
        all_services: bool = False,
        reconvert: bool = False,
        diff: bool = False,
    ) -> MigrationResult:
        """Run full migration.

        Args:
            dry_run: If True, only show what would change
            service: Migrate a single service (e.g., 'valkey', 'mariadb', 'php', 'apache')
            all_services: Migrate all remaining services in order
            reconvert: Re-read v1 JSON and regenerate v2 YAML (pre-migration refresh)
            diff: Show differences between v1 and v2 configs
        """
        # Pre-migration checks
        pre = self.pre_migration_check()
        if pre.errors:
            if reconvert:
                # For reconvert, only abort if v1 is not found (skip RHEL check
                # since reconvert doesn't do service cutover)
                if not pre.v1_detected:
                    return pre
            else:
                return pre

        # Convert configs
        try:
            config = self.convert_configs()
        except Exception as e:
            return MigrationResult(
                os_detected=pre.os_detected,
                is_rhel=pre.is_rhel,
                v1_detected=pre.v1_detected,
                v1_version=pre.v1_version,
                errors=[f"Config conversion failed: {e}"],
                dry_run=dry_run,
            )

        # --diff: show v1 vs v2 differences
        if diff:
            return MigrationResult(
                os_detected=pre.os_detected,
                is_rhel=pre.is_rhel,
                v1_detected=pre.v1_detected,
                v1_version=pre.v1_version,
                mariadb_version=pre.mariadb_version,
                php_versions=pre.php_versions,
                converted_config=config,
                dry_run=True,
                errors=[],
            )

        # --reconvert: just re-read v1 and save v2 YAML, no cutover
        if reconvert:
            if not dry_run:
                try:
                    save_config(config, self.config_dir)
                except Exception as e:
                    return MigrationResult(
                        os_detected=pre.os_detected,
                        is_rhel=pre.is_rhel,
                        v1_detected=pre.v1_detected,
                        v1_version=pre.v1_version,
                        errors=[f"Failed to save converted config: {e}"],
                        dry_run=dry_run,
                    )
            return MigrationResult(
                os_detected=pre.os_detected,
                is_rhel=pre.is_rhel,
                v1_detected=pre.v1_detected,
                v1_version=pre.v1_version,
                mariadb_version=pre.mariadb_version,
                php_versions=pre.php_versions,
                converted_config=config,
                dry_run=dry_run,
            )

        if dry_run:
            return MigrationResult(
                os_detected=pre.os_detected,
                is_rhel=pre.is_rhel,
                v1_detected=pre.v1_detected,
                v1_version=pre.v1_version,
                mariadb_version=pre.mariadb_version,
                php_versions=pre.php_versions,
                converted_config=config,
                dry_run=True,
            )

        # Save converted configs
        try:
            save_config(config, self.config_dir)
        except Exception as e:
            return MigrationResult(
                os_detected=pre.os_detected,
                is_rhel=pre.is_rhel,
                v1_detected=pre.v1_detected,
                v1_version=pre.v1_version,
                errors=[f"Failed to save converted config: {e}"],
                dry_run=dry_run,
            )

        # Generate service configs (docker-compose.yml, vhosts, pools, Dockerfiles)
        config_gen_ok = True
        try:
            self._generate_service_configs(config)
        except Exception as e:
            logger.warning("Service config generation failed: %s", e)
            config_gen_ok = False

        # Pull images
        try:
            self._pull_images(config)
        except Exception as e:
            logger.warning("Image pull failed: %s", e)

        # Verify that the compose file was generated before starting containers.
        # Only check if generation appeared to succeed — if it threw, the warning
        # is already logged and we proceed (matching pre-existing behavior).
        if config_gen_ok:
            compose_found = False
            if self.file_writer is not None:
                # Check if the file_writer received docker-compose.yml
                written = getattr(self.file_writer, "written", None)
                if written is not None and "docker-compose.yml" in written:
                    compose_found = True
            if not compose_found:
                from nopanel.services.base import COMPOSE_FILE
                if COMPOSE_FILE.exists():
                    compose_found = True
            if not compose_found:
                return MigrationResult(
                    os_detected=pre.os_detected,
                    is_rhel=pre.is_rhel,
                    v1_detected=pre.v1_detected,
                    v1_version=pre.v1_version,
                    mariadb_version=pre.mariadb_version,
                    php_versions=pre.php_versions,
                    converted_config=config,
                    errors=["Service config generation failed — docker-compose.yml not found. Cannot start containers."],
                    dry_run=dry_run,
                )

        # Determine which services to migrate
        if service:
            # Single service migration
            step_results = [self._migrate_service_with_php(service, pre.php_versions)]
        elif all_services:
            # All services in order
            step_results = self._migrate_all_services(pre.php_versions)
        else:
            # Default: all services in order
            step_results = self._migrate_all_services(pre.php_versions)

        errors = [r.message for r in step_results if not r.success]

        # Post-migration cleanup
        if not errors:
            self._post_migration_cleanup()

        return MigrationResult(
            os_detected=pre.os_detected,
            is_rhel=pre.is_rhel,
            v1_detected=pre.v1_detected,
            v1_version=pre.v1_version,
            mariadb_version=pre.mariadb_version,
            php_versions=pre.php_versions,
            converted_config=config,
            step_results=step_results,
            errors=errors,
        )

    def _get_host_service_name(self, service: str) -> str:
        """Get the RHEL systemd service name for a noPanel service."""
        if service == "apache":
            return RHEL_SERVICES["apache"]
        elif service == "mariadb":
            return RHEL_SERVICES["mariadb"]
        elif service == "valkey":
            return RHEL_SERVICES["valkey"]
        elif service.startswith("php-"):
            version = service[4:]
            version_nodot = version.replace(".", "")
            return RHEL_SERVICES["php_fpm_prefix"].format(version_nodot=version_nodot)
        return service

    def _migrate_service_with_php(
        self, service: str, php_versions: list[str]
    ) -> MigrationStepResult:
        """Migrate a single service, handling PHP multi-version specially."""
        if service == "php":
            # Migrate all PHP versions
            for ver in php_versions:
                result = self.migrate_service(f"php-{ver}")
                if not result.success:
                    return result
            return MigrationStepResult(
                service="php",
                success=True,
                message=f"Migrated all PHP versions: {', '.join(php_versions)}",
                host_service_stopped=True,
                container_started=True,
            )
        else:
            return self.migrate_service(service)

    def _migrate_all_services(
        self, php_versions: list[str]
    ) -> list[MigrationStepResult]:
        """Migrate all services in the recommended order."""
        step_results: list[MigrationStepResult] = []
        for svc in MIGRATION_ORDER:
            if svc == "php":
                for ver in php_versions:
                    result = self.migrate_service(f"php-{ver}")
                    step_results.append(result)
                    if not result.success:
                        return step_results
            else:
                result = self.migrate_service(svc)
                step_results.append(result)
                if not result.success:
                    return step_results
        return step_results

    def _generate_service_configs(self, config: FullConfig) -> None:
        """Generate docker-compose.yml, Apache vhosts, PHP-FPM pools, and Dockerfiles.

        Uses the commit engine's config generation logic without applying changes.
        Writes to the generated/ directory using file_writer if available.
        """
        from nopanel.services.php import generate_dockerfiles, generate_pool_configs
        from nopanel.services.web import generate_vhost_configs
        from nopanel.templates import render_compose

        files: dict[str, str] = {}
        files.update(generate_vhost_configs(config))
        files.update(generate_pool_configs(config))
        files.update(generate_dockerfiles(config))

        compose_content = render_compose(
            services=config.services.model_dump(mode="json"),
            network_mode=config.nopanel.settings.network_mode.value,
            php_versions=sorted(config.services.php.keys()),
        )
        files["docker-compose.yml"] = compose_content

        # MariaDB env file (keeps root password out of compose file)
        files["mariadb.env"] = (
            f"MARIADB_ROOT_PASSWORD={config.services.mariadb.root_password}\n"
        )

        if self.file_writer:
            for rel_path, content in files.items():
                self.file_writer.write(rel_path, content)
        else:
            # Default: write to generated/ directory
            from nopanel.commit import RealFileWriter
            from nopanel.services.base import GENERATED_DIR
            writer = RealFileWriter(GENERATED_DIR)
            for rel_path, content in files.items():
                writer.write(rel_path, content)

    def _pull_images(self, config: FullConfig) -> None:
        """Pre-pull non-PHP images and build custom PHP images.

        PHP images are built from generated Dockerfiles, not pulled from a registry.
        """
        if not self.docker:
            logger.info("No Docker manager, skipping image pull/build")
            return

        # Pull non-PHP service images
        self.docker.compose_pull(["apache", "mariadb", "valkey"])

        # Build custom PHP images from generated Dockerfiles
        from nopanel.services.base import GENERATED_DIR
        for version in sorted(config.services.php):
            dockerfile_dir = GENERATED_DIR / f"docker/php-{version}"
            tag = f"nopanel/php-{version}:latest"
            try:
                self.docker.build_image(dockerfile_dir=dockerfile_dir, tag=tag)
                logger.info("Built PHP image %s", tag)
            except Exception as e:
                logger.warning("Failed to build PHP image %s: %s", tag, e)

    def _post_migration_cleanup(self) -> None:
        """Post-migration cleanup: backup then remove v1 config files."""
        v1_files = ["nopanel.json", "users.json", "modules.json"]
        for filename in v1_files:
            v1_file = self.config_dir / filename
            if v1_file.exists():
                backup_path = v1_file.parent / f"{v1_file.name}.v1.bak"
                try:
                    backup_path.write_bytes(v1_file.read_bytes())
                    v1_file.unlink()
                    logger.info("Backed up and removed %s", v1_file)
                except Exception as e:
                    logger.warning("Failed to clean up %s: %s", v1_file, e)
