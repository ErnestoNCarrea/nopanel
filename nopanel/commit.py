"""Commit engine — the heart of noPanel.

Diffs desired vs committed state, generates configs, applies changes,
reloads services, and snapshots the committed state.

Each step is a separate method for testability. The engine accepts
injectable dependencies (DockerManager, SQLExecutor, filesystem path).
"""

from __future__ import annotations

import fcntl
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from nopanel.config import (
    DEFAULT_CONFIG_DIR,
    load_config,
    save_config,
)
from nopanel.docker_manager import DockerManager
from nopanel.host_ops import (
    LOGIN_SHELLS,
    HostOps,
    HostOpResult,
    NoOpHostOps,
    PendingCommandsHostOps,
)
from nopanel.services.base import GENERATED_DIR, SELF_SIGNED_DIR
from nopanel.models import Database, FullConfig, LoginType, SSLMode
from nopanel.services.database import (
    SQLExecutor,
    apply_database_changes,
)
from nopanel.services.php import generate_dockerfiles, generate_pool_configs
from nopanel.services.web import generate_vhost_configs
from nopanel.state import (
    ConfigDiff,
    diff_configs,
    format_diff,
    load_committed,
    save_committed,
)
from nopanel.templates import render_compose

logger = logging.getLogger(__name__)

# Lock file to prevent concurrent commits (relative to config_dir at runtime)
LOCK_FILE_NAME = ".commit.lock"


# ---------------------------------------------------------------------------
# Commit result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitResult:
    """Result of a commit operation."""

    diff: ConfigDiff
    generated_files: dict[str, str] = field(default_factory=dict)
    sql_executed: list[str] = field(default_factory=list)
    services_restarted: list[str] = field(default_factory=list)
    host_commands: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def summary(self) -> str:
        if self.diff.is_empty:
            return "No changes to commit."
        parts = [format_diff(self.diff)]
        if self.errors:
            parts.append("\nErrors:")
            for err in self.errors:
                parts.append(f"  ! {err}")
        if self.dry_run:
            parts.append("\n(dry run — no changes applied)")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Filesystem protocol for injectable file writing
# ---------------------------------------------------------------------------


class FileWriter(Protocol):
    """Protocol for writing generated files (injectable for testing)."""

    def write(self, path: str, content: str) -> None: ...


class RealFileWriter:
    """Default file writer that writes to the filesystem."""

    def __init__(self, base_dir: Path = GENERATED_DIR) -> None:
        self.base_dir = base_dir

    def write(self, path: str, content: str) -> None:
        full_path = self.base_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        if path.endswith(".env"):
            full_path.chmod(0o600)

    def remove(self, path: str) -> None:
        full_path = self.base_dir / path
        if full_path.exists():
            full_path.unlink()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERVICE_NAME_MAP = {"web": "apache"}


def _to_compose_names(diff_names: list[str], config: FullConfig) -> list[str]:
    """Map diff service names to docker-compose service names.

    The services diff operates on flattened keys (web, php-8.2, php-8.3,
    mariadb, valkey). Compose services are named apache, php-8.2, php-8.3,
    mariadb, valkey. The 'web' key maps to 'apache'. Individual 'php-X.Y'
    keys pass through as-is.
    """
    result: list[str] = []
    for name in diff_names:
        if name == "php":
            result.extend(f"php-{v}" for v in sorted(config.services.php))
        else:
            result.append(_SERVICE_NAME_MAP.get(name, name))
    return result


# ---------------------------------------------------------------------------
# Commit Engine
# ---------------------------------------------------------------------------


class CommitEngine:
    """Orchestrates the commit workflow: diff → generate → apply → reload → snapshot.

    Dependencies are injected for testability:
    - docker_manager: DockerManager for container operations
    - sql_executor: SQLExecutor for MariaDB operations
    - file_writer: FileWriter for writing generated configs
    """

    def __init__(
        self,
        config_dir: Path = DEFAULT_CONFIG_DIR,
        docker_manager: DockerManager | None = None,
        sql_executor: SQLExecutor | None = None,
        file_writer: FileWriter | None = None,
        host_ops: HostOps | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.docker = docker_manager
        self.sql = sql_executor
        self.file_writer = file_writer or RealFileWriter(GENERATED_DIR)
        self.host_ops = host_ops or PendingCommandsHostOps(config_dir=config_dir)

    def run(self, dry_run: bool = False, service_filter: str | None = None) -> CommitResult:
        """Run the full commit workflow.

        Args:
            dry_run: If True, only compute and show what would change
            service_filter: If set, only commit changes for this service

        Returns:
            CommitResult with details of what was done
        """
        valid_filters = {"databases", "web", "apache", "services", "users", "php"}
        if service_filter and service_filter not in valid_filters and not re.match(r"^php-\d+\.\d+$", service_filter):
            return CommitResult(
                diff=ConfigDiff(),
                errors=[f"Invalid service filter: {service_filter!r}. "
                        f"Valid options: {', '.join(sorted(valid_filters))}, php-X.Y"],
            )

        # Acquire exclusive lock to prevent concurrent commits
        self.config_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.config_dir / LOCK_FILE_NAME
        lock_fd = None
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            if lock_fd:
                lock_fd.close()
            return CommitResult(
                diff=ConfigDiff(),
                errors=["Another commit is in progress. Remove "
                        f"{lock_path} if this is stale."],
            )
        try:
            return self._run_inner(dry_run, service_filter)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _run_inner(self, dry_run: bool = False, service_filter: str | None = None) -> CommitResult:
        """Internal commit workflow (called under lock)."""

        # 1. Load desired and committed state
        desired = load_config(self.config_dir)
        committed = load_committed(self.config_dir)

        # 2. Diff
        diff = diff_configs(desired, committed)

        if diff.is_empty:
            return CommitResult(diff=diff, dry_run=dry_run)

        if dry_run:
            return CommitResult(diff=diff, dry_run=True)

        # Set up SQL executor if not provided and MariaDB has a root password
        sql_executor = self.sql
        if not sql_executor and desired.services.mariadb.root_password:
            from nopanel.services.database import RealSQLExecutor
            sql_executor = RealSQLExecutor(
                root_password=desired.services.mariadb.root_password
            )

        errors: list[str] = []
        generated_files: dict[str, str] = {}
        sql_executed: list[str] = []
        services_restarted: list[str] = []

        # 3. Clean up stale configs for deleted entities
        try:
            self._cleanup_stale_configs(diff, committed, desired)
        except Exception as e:
            errors.append(f"Stale config cleanup failed: {e}")

        # 3b. Generate self-signed SSL certificates for SELF mode domains
        try:
            self._generate_self_signed_certs(desired, committed)
        except Exception as e:
            errors.append(f"Self-signed cert generation failed: {e}")

        # 3c. Apply host user changes (or queue pending commands)
        host_commands: list[str] = []
        if not service_filter or service_filter == "users":
            pending_file = self.config_dir / "pending-host-cmds.sh"
            # Warn if previous host commands are still pending (only relevant
            # for the pending-commands backend)
            if not self.host_ops.can_manage_host and pending_file.exists():
                errors.append(
                    f"Pending host commands in {pending_file} have not been "
                    f"executed yet. Run 'nopanel host-commands --run' on the host first."
                )
            host_results = self._apply_host_user_changes(diff, desired, committed)
            for r in host_results:
                if not r.success:
                    errors.append(f"Host operation failed: {r.message or r.stderr}")
                if not r.executed and r.commands:
                    host_commands.extend(r.commands)

        # 4. Generate configs (skip irrelevant sections when service_filter is set)
        config_errors = False
        try:
            generated_files.update(self._generate_configs(desired, service_filter))
        except Exception as e:
            errors.append(f"Config generation failed: {e}")
            config_errors = True

        # 4b. Build PHP-FPM images if needed (only when PHP services or modules changed)
        php_changed = any(
            c.name.startswith("php-") for c in diff.services.added + diff.services.modified
        )
        php_modules_changed = (
            desired.nopanel.php.additional_modules
            != committed.nopanel.php.additional_modules
        )
        if self.docker and desired.services.php and (php_changed or php_modules_changed):
            if not config_errors:
                try:
                    self._build_php_images(desired)
                except Exception as e:
                    errors.append(f"PHP image build failed: {e}")

        # 5. Apply changes
        # Databases
        if not service_filter or service_filter == "databases":
            try:
                sql_executed = self._apply_database_changes(diff, desired, committed, sql_executor)
            except Exception as e:
                errors.append(f"Database changes failed: {e}")

        # 6. Reload services (skip if config generation failed)
        if not config_errors:
            if not service_filter or service_filter in ("web", "apache"):
                if diff.domains.total_changes > 0 or diff.settings_changed:
                    services_restarted.append("apache")
                    if self.docker:
                        self.docker.compose_restart(["apache"])

            if not service_filter or service_filter.startswith("php"):
                if diff.domains.total_changes > 0:
                    # Determine which PHP versions actually have pool changes
                    changed_versions: set[str] = set()
                    for change in diff.domains.added + diff.domains.modified:
                        new_php = (change.new or {}).get("php_version")
                        if new_php:
                            changed_versions.add(new_php)
                        old_php = (change.old or {}).get("php_version")
                        if old_php:
                            changed_versions.add(old_php)
                    for change in diff.domains.deleted:
                        old_php = (change.old or {}).get("php_version")
                        if old_php:
                            changed_versions.add(old_php)
                    # If service_filter specifies a single version, narrow to that
                    if service_filter and service_filter != "php":
                        changed_versions = {
                            v for v in changed_versions if f"php-{v}" == service_filter
                        }
                    for version in sorted(changed_versions):
                        services_restarted.append(f"php-{version}")
                    if self.docker and changed_versions:
                        self.docker.compose_restart(
                            [f"php-{v}" for v in sorted(changed_versions)]
                        )

            if not service_filter or service_filter == "services":
                if diff.services.total_changes > 0 or diff.settings_changed:
                    # Regenerate compose and restart affected services
                    try:
                        self._regenerate_compose(desired)
                    except Exception as e:
                        errors.append(f"Compose regeneration failed: {e}")

                    if self.docker:
                        # Full restart only when network mode changes; other settings
                        # changes (e.g. PHP modules) are handled by PHP image rebuild.
                        network_changed = (
                            desired.nopanel.settings.network_mode
                            != committed.nopanel.settings.network_mode
                        )
                        if network_changed:
                            self.docker.compose_down()
                            self.docker.compose_up()
                            services_restarted.append("(all — network mode change)")
                        else:
                            # Map diff service names to compose service names.
                            # The services diff has top-level keys (web, php, mariadb,
                            # valkey) but compose services are named apache, php-X.Y,
                            # mariadb, valkey. Expand "php" to per-version names.
                            changed = _to_compose_names(
                                [c.name for c in diff.services.modified], desired
                            )
                            added = _to_compose_names(
                                [c.name for c in diff.services.added], desired
                            )
                            deleted = _to_compose_names(
                                [c.name for c in diff.services.deleted], desired
                            )
                            if changed:
                                self.docker.compose_restart(changed)
                            if added:
                                self.docker.compose_up(added)
                            # Stop and remove deleted service containers
                            if deleted:
                                self.docker.compose_stop(deleted)
                                self.docker.compose_down(deleted)
                            services_restarted.extend(changed + added)

        # 7. Snapshot (only if no errors — failed changes should remain pending)
        if not errors:
            try:
                save_committed(desired, self.config_dir)
            except Exception as e:
                errors.append(f"Snapshot failed: {e}")

        return CommitResult(
            diff=diff,
            generated_files=generated_files,
            sql_executed=sql_executed,
            services_restarted=services_restarted,
            host_commands=host_commands,
            errors=errors,
        )

    def _apply_host_user_changes(
        self, diff: ConfigDiff, desired: FullConfig, committed: FullConfig
    ) -> list[HostOpResult]:
        """Apply system user changes via the pluggable HostOps backend.

        For backends that can manage the host directly (e.g. nsenter),
        operations are executed immediately. For queue-based backends
        (e.g. pending-commands), commands are written to a file for
        later execution by the host wrapper.

        Returns a list of HostOpResult, one per operation.
        """
        results: list[HostOpResult] = []

        # Create new users
        for change in diff.users.added:
            username = change.name
            user_data = change.new or {}
            login = LoginType(user_data.get("login", "sftp"))
            shell = LOGIN_SHELLS.get(login, "/sbin/nologin")
            password = user_data.get("password") or None
            results.append(
                self.host_ops.create_user(username, shell, password)
            )

        # Modify existing users (password or login type changes)
        for change in diff.users.modified:
            username = change.name
            old_data = change.old or {}
            new_data = change.new or {}
            # Update password if it changed
            if new_data.get("password") and new_data["password"] != old_data.get("password"):
                results.append(
                    self.host_ops.set_user_password(username, new_data["password"])
                )
            # Update shell if login type changed
            old_login = LoginType(old_data.get("login", "sftp"))
            new_login = LoginType(new_data.get("login", "sftp"))
            if old_login != new_login:
                new_shell = LOGIN_SHELLS.get(new_login, "/sbin/nologin")
                results.append(
                    self.host_ops.set_user_shell(username, new_shell)
                )

        # Delete removed users
        for change in diff.users.deleted:
            username = change.name
            results.append(
                self.host_ops.delete_user(username, remove_home=True)
            )

        return results

    def _generate_configs(self, config: FullConfig, service_filter: str | None = None) -> dict[str, str]:
        """Generate all config files from desired state.

        When service_filter is set, only generate configs relevant to that service
        to avoid writing unrelated files that won't be applied.
        """
        files: dict[str, str] = {}

        # Determine which sections to generate
        gen_web = not service_filter or service_filter in ("web", "apache")
        gen_php = not service_filter or service_filter.startswith("php")
        gen_compose = not service_filter or service_filter in ("web", "apache", "services")

        # Apache vhosts
        if gen_web:
            files.update(generate_vhost_configs(config))

        # PHP-FPM pools
        if gen_php:
            files.update(generate_pool_configs(config))

        # PHP Dockerfiles
        if gen_php:
            files.update(generate_dockerfiles(config))

        # docker-compose.yml
        if gen_compose:
            compose_content = render_compose(
                services=config.services.model_dump(mode="json"),
                network_mode=config.nopanel.settings.network_mode.value,
                php_versions=sorted(config.services.php.keys()),
            )
            files["docker-compose.yml"] = compose_content

        # MariaDB env file (keeps root password out of compose file)
        if gen_compose:
            files["mariadb.env"] = (
                f"MARIADB_ROOT_PASSWORD={config.services.mariadb.root_password}\n"
            )

        # Write all generated files
        for rel_path, content in files.items():
            self.file_writer.write(rel_path, content)

        return files

    def _build_php_images(self, config: FullConfig) -> None:
        """Build custom PHP-FPM Docker images from generated Dockerfiles."""
        from nopanel.services.base import GENERATED_DIR

        for version in sorted(config.services.php):
            dockerfile_dir = GENERATED_DIR / f"docker/php-{version}"
            tag = f"nopanel/php-{version}:latest"
            self.docker.build_image(dockerfile_dir=dockerfile_dir, tag=tag)

    def _generate_self_signed_certs(
        self, desired: FullConfig, committed: FullConfig
    ) -> None:
        """Generate self-signed SSL certificates for domains with ssl=SELF.

        Only generates certs for domains that don't already have one.
        Certificates are stored in /etc/nopanel/pki/self/{domain}.{crt,key}.
        """
        self_domains = [
            name for name, domain in desired.domains.domains.items()
            if domain.ssl == SSLMode.SELF
        ]
        if not self_domains:
            return

        SELF_SIGNED_DIR.mkdir(parents=True, exist_ok=True)

        for domain_name in self_domains:

            cert_path = SELF_SIGNED_DIR / f"{domain_name}.crt"
            key_path = SELF_SIGNED_DIR / f"{domain_name}.key"

            if cert_path.exists() and key_path.exists():
                continue

            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-keyout", str(key_path),
                    "-out", str(cert_path),
                    "-days", "365",
                    "-nodes",
                    "-subj", f"/CN={domain_name}",
                ],
                capture_output=True,
                check=True,
            )
            cert_path.chmod(0o644)
            key_path.chmod(0o600)

    def _cleanup_stale_configs(
        self, diff: ConfigDiff, committed: FullConfig, desired: FullConfig
    ) -> None:
        """Remove generated config files for deleted or changed domains."""
        remover = getattr(self.file_writer, "remove", None)
        if remover is None:
            return

        for change in diff.domains.deleted:
            domain_name = change.name
            remover(f"apache/domains/{domain_name}.http.conf")
            remover(f"apache/domains/{domain_name}.https.conf")

            # Clean up PHP-FPM pool config using the old domain's PHP version
            old_data = change.old or {}
            php_version = old_data.get("php_version")
            if php_version:
                version_nodot = php_version.replace(".", "")
                remover(f"php-fpm/php{version_nodot}/{domain_name}.conf")

            # Clean up self-signed SSL certs for deleted domains
            old_ssl = old_data.get("ssl")
            if old_ssl == SSLMode.SELF.value:
                cert_file = SELF_SIGNED_DIR / f"{domain_name}.crt"
                key_file = SELF_SIGNED_DIR / f"{domain_name}.key"
                for f in (cert_file, key_file):
                    if f.exists():
                        f.unlink()

        # Clean up stale PHP-FPM pool configs when a domain's PHP version changes
        for change in diff.domains.modified:
            old_data = change.old or {}
            new_data = change.new or {}
            old_php = old_data.get("php_version")
            new_php = new_data.get("php_version")
            if old_php and old_php != new_php:
                version_nodot = old_php.replace(".", "")
                remover(f"php-fpm/php{version_nodot}/{change.name}.conf")

            # Clean up HTTPS vhost when SSL mode changes to none
            old_ssl = old_data.get("ssl")
            new_ssl = new_data.get("ssl")
            if old_ssl in (SSLMode.AUTO.value, SSLMode.SELF.value) and new_ssl == SSLMode.NONE.value:
                remover(f"apache/domains/{change.name}.https.conf")

            # Clean up self-signed certs when SSL mode changes from SELF to non-SELF
            if old_ssl == SSLMode.SELF.value and new_ssl != SSLMode.SELF.value:
                cert_file = SELF_SIGNED_DIR / f"{change.name}.crt"
                key_file = SELF_SIGNED_DIR / f"{change.name}.key"
                for f in (cert_file, key_file):
                    if f.exists():
                        f.unlink()

        # Remove stale mod_md.conf if no auto-SSL domains remain in desired config
        desired_has_auto = any(
            d.ssl == SSLMode.AUTO for d in desired.domains.domains.values()
        )
        if not desired_has_auto:
            remover("apache/mod_md.conf")

        # Clean up stale PHP Dockerfiles for removed PHP versions
        committed_php = set(committed.services.php.keys())
        desired_php = set(desired.services.php.keys())
        for removed_version in committed_php - desired_php:
            remover(f"docker/php-{removed_version}/Dockerfile")

    def _regenerate_compose(self, config: FullConfig) -> None:
        """Regenerate docker-compose.yml only."""
        compose_content = render_compose(
            services=config.services.model_dump(mode="json"),
            network_mode=config.nopanel.settings.network_mode.value,
            php_versions=sorted(config.services.php.keys()),
        )
        self.file_writer.write("docker-compose.yml", compose_content)

    def _apply_database_changes(
        self,
        diff: ConfigDiff,
        desired: FullConfig,
        committed: FullConfig,
        sql_executor: SQLExecutor | None = None,
    ) -> list[str]:
        """Apply database create/modify/drop operations via SQL."""
        if not sql_executor:
            logger.warning("No SQL executor configured, skipping database changes")
            return []

        added_dbs: list[Database] = []
        modified_dbs: list[tuple[Database, Database]] = []
        deleted_dbs: list[Database] = []
        db_names: list[str] = []

        for change in diff.databases.added:
            db_data = change.new or {}
            db = Database(
                user=db_data.get("user", ""),
                dbuser=db_data.get("dbuser", ""),
                password=db_data.get("password", ""),
            )
            added_dbs.append(db)
            db_names.append(change.name)

        for change in diff.databases.modified:
            old_data = change.old or {}
            new_data = change.new or {}
            old_db = Database(
                user=old_data.get("user", ""),
                dbuser=old_data.get("dbuser", ""),
                password=old_data.get("password", ""),
            )
            new_db = Database(
                user=new_data.get("user", ""),
                dbuser=new_data.get("dbuser", ""),
                password=new_data.get("password", ""),
            )
            modified_dbs.append((old_db, new_db))
            db_names.append(change.name)

        for change in diff.databases.deleted:
            db_data = change.old or {}
            db = Database(
                user=db_data.get("user", ""),
                dbuser=db_data.get("dbuser", ""),
                password=db_data.get("password", ""),
            )
            deleted_dbs.append(db)
            db_names.append(change.name)

        return apply_database_changes(
            added=added_dbs,
            modified=modified_dbs,
            deleted=deleted_dbs,
            db_names=db_names,
            executor=sql_executor,
        )
