"""Pluggable host operations backend.

Provides a Protocol for host system operations (user management,
service management, host introspection) with multiple implementations:

- PendingCommandsHostOps: queues user commands to a file for later
  execution by the host wrapper script (current/legacy behavior).
- NsenterHostOps: direct execution via ``nsenter -t 1 -m -u -i -n --``
  (requires ``--privileged`` and ``--pid=host`` on the container).
- NoOpHostOps: no-op for dry-run or when host management is disabled.

The backend is selected at runtime via :func:`auto_detect_host_ops`
or explicitly injected into ``CommitEngine`` / ``MigrationEngine``.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from nopanel.config import DEFAULT_CONFIG_DIR
from nopanel.docker_manager import CommandResult
from nopanel.models import LoginType

logger = logging.getLogger(__name__)

LOGIN_SHELLS: dict[LoginType, str] = {
    LoginType.SSH: "/bin/bash",
    LoginType.SFTP: "/sbin/nologin",
    LoginType.NO: "/sbin/nologin",
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostOpResult:
    """Result of a single host operation."""

    success: bool
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    executed: bool = True
    commands: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner protocol (supports stdin, unlike docker_manager.CommandRunner)
# ---------------------------------------------------------------------------


class HostRunner(Protocol):
    """Protocol for running host commands (injectable for testing)."""

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult: ...


class SubprocessHostRunner:
    """Default runner using subprocess with stdin support."""

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult:
        proc = subprocess.run(args, capture_output=True, text=True, input=stdin)
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


# ---------------------------------------------------------------------------
# HostOps protocol
# ---------------------------------------------------------------------------


class HostOps(Protocol):
    """Pluggable backend for host system operations.

    Implementations differ in *how* they reach the host:
    pending-file queue, nsenter, SSH, etc.  Callers (CommitEngine,
    MigrationEngine) interact only with this protocol.
    """

    @property
    def can_manage_host(self) -> bool:
        """True when operations are executed immediately on the host."""
        ...

    # -- User management --------------------------------------------------

    def create_user(
        self, username: str, shell: str, password: str | None = None
    ) -> HostOpResult: ...

    def set_user_password(self, username: str, password: str) -> HostOpResult: ...

    def set_user_shell(self, username: str, shell: str) -> HostOpResult: ...

    def delete_user(
        self, username: str, remove_home: bool = True
    ) -> HostOpResult: ...

    # -- Service management (migration) -----------------------------------

    def stop_service(self, service: str) -> HostOpResult: ...

    def start_service(self, service: str) -> HostOpResult: ...

    def disable_service(self, service: str) -> HostOpResult: ...

    # -- Host introspection -----------------------------------------------

    def detect_os(self) -> str: ...

    def query_package_version(self, package: str) -> str | None: ...

    def query_packages(self, pattern: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# NoOpHostOps — dry-run / disabled
# ---------------------------------------------------------------------------


class NoOpHostOps:
    """No-op host operations — for dry-run or when host management is disabled."""

    @property
    def can_manage_host(self) -> bool:
        return False

    def create_user(
        self, username: str, shell: str, password: str | None = None
    ) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def set_user_password(self, username: str, password: str) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def set_user_shell(self, username: str, shell: str) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def delete_user(self, username: str, remove_home: bool = True) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def stop_service(self, service: str) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def start_service(self, service: str) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def disable_service(self, service: str) -> HostOpResult:
        return HostOpResult(success=True, message="Skipped (no-op)", executed=False)

    def detect_os(self) -> str:
        return "unknown"

    def query_package_version(self, package: str) -> str | None:
        return None

    def query_packages(self, pattern: str) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# PendingCommandsHostOps — current/legacy behavior
# ---------------------------------------------------------------------------


class PendingCommandsHostOps:
    """Queues user commands to ``pending-host-cmds.sh`` for later execution.

    Service management and introspection use direct ``subprocess`` calls,
    which works when nopanel runs directly on the host (e.g. during
    v1→v2 migration before containerization).
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        self.config_dir = config_dir

    @property
    def can_manage_host(self) -> bool:
        return False

    def _pending_file(self) -> Path:
        return self.config_dir / "pending-host-cmds.sh"

    def _append_pending(self, commands: list[str]) -> None:
        path = self._pending_file()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        batch = f"# batch: {timestamp}\n" + "\n".join(commands) + "\n"
        with open(path, "a") as f:
            f.write(batch)
        path.chmod(0o600)

    # -- User management (queued) -----------------------------------------

    def create_user(
        self, username: str, shell: str, password: str | None = None
    ) -> HostOpResult:
        cmds = [f"useradd -m -s {shlex.quote(shell)} {shlex.quote(username)}"]
        if password:
            cmds.append(
                f"echo {shlex.quote(f'{username}:{password}')} | chpasswd"
            )
        self._append_pending(cmds)
        return HostOpResult(success=True, message="Queued", executed=False, commands=cmds)

    def set_user_password(self, username: str, password: str) -> HostOpResult:
        cmd = f"echo {shlex.quote(f'{username}:{password}')} | chpasswd"
        self._append_pending([cmd])
        return HostOpResult(success=True, message="Queued", executed=False, commands=[cmd])

    def set_user_shell(self, username: str, shell: str) -> HostOpResult:
        cmd = f"chsh -s {shlex.quote(shell)} {shlex.quote(username)}"
        self._append_pending([cmd])
        return HostOpResult(success=True, message="Queued", executed=False, commands=[cmd])

    def delete_user(self, username: str, remove_home: bool = True) -> HostOpResult:
        flag = "-r " if remove_home else ""
        cmd = f"userdel {flag}{shlex.quote(username)}".strip()
        self._append_pending([cmd])
        return HostOpResult(success=True, message="Queued", executed=False, commands=[cmd])

    # -- Service management (direct subprocess) ---------------------------

    def stop_service(self, service: str) -> HostOpResult:
        result = subprocess.run(
            ["systemctl", "stop", service], capture_output=True, text=True
        )
        return HostOpResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def start_service(self, service: str) -> HostOpResult:
        result = subprocess.run(
            ["systemctl", "start", service], capture_output=True, text=True
        )
        return HostOpResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def disable_service(self, service: str) -> HostOpResult:
        result = subprocess.run(
            ["systemctl", "disable", service], capture_output=True, text=True
        )
        return HostOpResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    # -- Host introspection (direct) --------------------------------------

    def detect_os(self) -> str:
        try:
            content = Path("/etc/os-release").read_text()
            for line in content.splitlines():
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip('"').strip("'")
        except FileNotFoundError:
            pass
        return "unknown"

    def query_package_version(self, package: str) -> str | None:
        try:
            result = subprocess.run(
                ["rpm", "-q", "--qf", "%{VERSION}", package],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                ver = result.stdout.strip().split("-")[0]
                if ver and ver[0].isdigit():
                    return ver
        except FileNotFoundError:
            pass
        return None

    def query_packages(self, pattern: str) -> list[str]:
        try:
            result = subprocess.run(
                ["rpm", "-qa", pattern], capture_output=True, text=True
            )
            return result.stdout.splitlines()
        except FileNotFoundError:
            return []


# ---------------------------------------------------------------------------
# NsenterHostOps — direct execution via nsenter
# ---------------------------------------------------------------------------


class NsenterHostOps:
    """Host operations via ``nsenter`` — requires ``--privileged`` and ``--pid=host``.

    All commands are executed in the host's mount, UTS, IPC, and network
    namespaces via::

        nsenter -t 1 -m -u -i -n -- <command>

    This gives the container direct access to the host's filesystem,
    systemd, and package manager without SSH or a host-side agent.
    """

    NSENTER_PREFIX = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n"]

    def __init__(self, runner: HostRunner | None = None) -> None:
        self.runner = runner or SubprocessHostRunner()

    @property
    def can_manage_host(self) -> bool:
        return True

    def _run(self, args: list[str], stdin: str | None = None) -> HostOpResult:
        result = self.runner.run(self.NSENTER_PREFIX + args, stdin=stdin)
        return HostOpResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    # -- User management (direct execution) -------------------------------

    def create_user(
        self, username: str, shell: str, password: str | None = None
    ) -> HostOpResult:
        result = self._run(["useradd", "-m", "-s", shell, username])
        if not result.success:
            return result
        if password:
            pwd_result = self.set_user_password(username, password)
            if not pwd_result.success:
                return pwd_result
        return result

    def set_user_password(self, username: str, password: str) -> HostOpResult:
        return self._run(["chpasswd"], stdin=f"{username}:{password}\n")

    def set_user_shell(self, username: str, shell: str) -> HostOpResult:
        return self._run(["chsh", "-s", shell, username])

    def delete_user(self, username: str, remove_home: bool = True) -> HostOpResult:
        args = ["userdel"]
        if remove_home:
            args.append("-r")
        args.append(username)
        return self._run(args)

    # -- Service management (direct via nsenter) --------------------------

    def stop_service(self, service: str) -> HostOpResult:
        return self._run(["systemctl", "stop", service])

    def start_service(self, service: str) -> HostOpResult:
        return self._run(["systemctl", "start", service])

    def disable_service(self, service: str) -> HostOpResult:
        return self._run(["systemctl", "disable", service])

    # -- Host introspection (via nsenter) ---------------------------------

    def detect_os(self) -> str:
        result = self._run(["cat", "/etc/os-release"])
        if result.success:
            for line in result.stdout.splitlines():
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip('"').strip("'")
        return "unknown"

    def query_package_version(self, package: str) -> str | None:
        result = self._run(["rpm", "-q", "--qf", "%{VERSION}", package])
        if result.success and result.stdout.strip():
            ver = result.stdout.strip().split("-")[0]
            if ver and ver[0].isdigit():
                return ver
        return None

    def query_packages(self, pattern: str) -> list[str]:
        result = self._run(["rpm", "-qa", pattern])
        if result.success:
            return result.stdout.splitlines()
        return []


# ---------------------------------------------------------------------------
# NsenterSystemOps — adapts NsenterHostOps to the SystemOps protocol
# ---------------------------------------------------------------------------


class NsenterSystemOps:
    """Adapter that makes :class:`NsenterHostOps` satisfy the
    ``SystemOps`` protocol used by :class:`~nopanel.migrate.MigrationEngine`.

    This allows v1→v2 migration to run from inside a privileged container
    with ``--pid=host`` instead of requiring nopanel to run directly on
    the host.
    """

    def __init__(
        self,
        host_ops: NsenterHostOps | None = None,
        config_dir: Path = DEFAULT_CONFIG_DIR,
    ) -> None:
        self.host_ops = host_ops or NsenterHostOps()
        self.config_dir = config_dir

    def detect_os(self) -> str:
        return self.host_ops.detect_os()

    def stop_service(self, service: str) -> bool:
        return self.host_ops.stop_service(service).success

    def start_service(self, service: str) -> bool:
        return self.host_ops.start_service(service).success

    def disable_service(self, service: str) -> bool:
        return self.host_ops.disable_service(service).success

    def get_mariadb_version(self) -> str | None:
        from nopanel.migrate import (
            _parse_version_from_image_tag,
            _version_from_compose_file,
            _version_from_image_file,
        )

        # 1. v2 services config
        services_yml = self.config_dir / "services.yml"
        ver = _version_from_image_file(services_yml, "mariadb")
        if ver:
            return ver

        # 2. Generated docker-compose.yml
        compose_yml = self.config_dir / "generated" / "docker-compose.yml"
        ver = _version_from_compose_file(compose_yml, "mariadb")
        if ver:
            return ver

        # 3. docker inspect (container-local, no host access needed)
        try:
            result = subprocess.run(
                ["docker", "inspect", "nopanel-mariadb",
                 "--format", "{{.Config.Image}}"],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                ver = _parse_version_from_image_tag(result.stdout.strip())
                if ver:
                    return ver
        except FileNotFoundError:
            pass

        # 4. Host RPM query via nsenter
        for pkg in ("MariaDB-server", "mariadb-server"):
            ver = self.host_ops.query_package_version(pkg)
            if ver:
                return ver

        return None

    def get_installed_php_versions(self) -> list[str]:
        versions: list[str] = []
        packages = self.host_ops.query_packages("php*-php-fpm")
        for line in packages:
            if "-php-fpm" in line and line.startswith("php"):
                parts = line.split("-")
                if parts[0].startswith("php") and len(parts[0]) > 3:
                    ver_str = parts[0][3:]
                    if len(ver_str) >= 2:
                        version = f"{ver_str[0]}.{ver_str[1:]}"
                        if version not in versions:
                            versions.append(version)
        return sorted(versions)

    def get_v1_user_list(self) -> list[str]:
        from nopanel.config import read_v1_users

        v1_users = read_v1_users(self.config_dir)
        return list(v1_users.keys())


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def auto_detect_host_ops(config_dir: Path = DEFAULT_CONFIG_DIR) -> HostOps:
    """Auto-detect the best available host operations backend.

    Tries nsenter first (if running in a privileged container with
    ``--pid=host``), falls back to pending-commands mode.
    """
    try:
        result = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "true"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.info("Host operations: using nsenter backend")
            return NsenterHostOps()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    logger.info("Host operations: using pending-commands backend")
    return PendingCommandsHostOps(config_dir=config_dir)
