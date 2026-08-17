"""Pluggable host operations — transport + strategy architecture.

**Transport** determines how commands reach the host:

- ``LocalTransport``: direct subprocess (nopanel on host).
- ``NsenterTransport``: ``nsenter -t 1 -m -u -i -n --`` (privileged container).

**Strategy** determines how operations are expressed:

- ``PyInfraHostOps``: declarative, idempotent via pyInfra (only strategy implemented).

**Special cases** (not transport/strategy based):

- ``PendingCommandsHostOps``: queues commands to a file (no host access).
- ``NoOpHostOps``: no-op for dry-run or ``--no-host``.

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
# Transport protocol — how commands reach the host
# ---------------------------------------------------------------------------


class HostTransport(Protocol):
    """Transport for executing commands on the host.

    Implementations determine the mechanism by which a command
    reaches the host OS: direct subprocess, nsenter, SSH, etc.
    """

    @property
    def name(self) -> str: ...

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult: ...


class LocalTransport:
    """Direct subprocess execution — nopanel runs on the host."""

    @property
    def name(self) -> str:
        return "local"

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult:
        proc = subprocess.run(args, capture_output=True, text=True, input=stdin)
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


class NsenterTransport:
    """nsenter transport — requires ``--privileged`` and ``--pid=host``.

    All commands are executed in the host's mount, UTS, IPC, and network
    namespaces via::

        nsenter -t 1 -m -u -i -n -- <command>
    """

    PREFIX = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n"]

    @property
    def name(self) -> str:
        return "nsenter"

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult:
        proc = subprocess.run(
            self.PREFIX + args, capture_output=True, text=True, input=stdin
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def detect_transport() -> HostTransport | None:
    """Auto-detect the best available transport.

    Returns ``NsenterTransport`` if nsenter to PID 1 succeeds,
    otherwise ``LocalTransport`` if running directly on the host,
    otherwise ``None`` (no direct host access).
    """
    try:
        result = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "true"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.info("Transport: nsenter detected")
            return NsenterTransport()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check if we're on the host (not in a container)
    try:
        Path("/etc/os-release").read_text()
        logger.info("Transport: local detected")
        return LocalTransport()
    except (FileNotFoundError, PermissionError):
        pass

    return None


# ---------------------------------------------------------------------------
# HostOps protocol
# ---------------------------------------------------------------------------


class HostOps(Protocol):
    """Pluggable backend for host system operations.

    Implementations combine a transport (how to reach the host) with a
    strategy (how to express operations).  Callers (CommitEngine,
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
# Auto-detection
# ---------------------------------------------------------------------------


def auto_detect_host_ops(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    prefer_pyinfra: bool = False,
) -> HostOps:
    """Auto-detect the best available host operations backend.

    Detection combines transport auto-detection with strategy selection:

    1. If ``prefer_pyinfra=True``: detect transport (nsenter or local),
       then create ``PyInfraHostOps`` with that transport.
    2. Otherwise: fall back to ``PendingCommandsHostOps`` (queues commands
       to a file, no direct host access).

    pyInfra is not tried by default because ``@local`` transport requires
    sudo, which may prompt for credentials in non-interactive contexts.
    Use ``prefer_pyinfra=True`` or inject ``PyInfraHostOps`` directly.

    Args:
        config_dir: Path to nopanel config directory.
        prefer_pyinfra: If True, try pyInfra with auto-detected transport.
    """
    if prefer_pyinfra:
        ops = _try_pyinfra(config_dir)
        if ops:
            return ops

    logger.info("Host operations: using pending-commands backend")
    return PendingCommandsHostOps(config_dir=config_dir)


def _try_pyinfra(config_dir: Path) -> HostOps | None:
    """Try to create a PyInfraHostOps with auto-detected transport."""
    try:
        from nopanel.pyinfra_backend import PyInfraHostOps

        transport = detect_transport()
        if transport is None:
            logger.warning("No transport detected, cannot use pyInfra backend")
            return None

        ops = PyInfraHostOps(transport=transport, config_dir=config_dir)
        logger.info("Host operations: using pyInfra backend (transport=%s)", transport.name)
        return ops
    except ImportError:
        return None
