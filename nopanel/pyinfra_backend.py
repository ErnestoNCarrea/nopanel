"""pyInfra-based host operations — strategy layer.

Uses pyInfra's programmatic API (v3.x) to execute host operations
declaratively and idempotently.  The transport (how commands reach
the host) is injected via :class:`~nopanel.host_ops.HostTransport`:

- ``LocalTransport``: pyInfra ``@local`` connector (nopanel on host).
- ``NsenterTransport``: custom pyInfra ``@nsenter`` connector that
  prefixes every command with ``nsenter -t 1 -m -u -i -n --``
  (privileged container with ``--pid=host``).

This module implements the **strategy** axis (pyInfra operations).
The **transport** axis is defined in :mod:`nopanel.host_ops`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nopanel.config import DEFAULT_CONFIG_DIR
from nopanel.host_ops import HostOpResult, HostOps, HostTransport, LocalTransport

logger = logging.getLogger(__name__)


def _require_pyinfra() -> None:
    """Import pyInfra modules, raising a helpful error if not installed."""
    try:
        import pyinfra  # noqa: F401
    except ImportError:
        raise ImportError(
            "pyInfra backend requires the 'pyinfra' package. "
            "Install it with: pip install pyinfra>=3.10"
        ) from None


# ---------------------------------------------------------------------------
# NsenterConnector — pyInfra connector for nsenter transport
# ---------------------------------------------------------------------------


def _create_nsenter_connector_class() -> type:
    """Create a pyInfra connector class that wraps commands with nsenter.

    Subclasses ``LocalConnector`` and overrides ``run_shell_command``,
    ``put_file``, and ``get_file`` to prefix commands with nsenter.
    """
    from pyinfra.connectors.local import LocalConnector

    class NsenterConnector(LocalConnector):
        """pyInfra connector that executes commands via nsenter.

        All commands are prefixed with ``nsenter -t 1 -m -u -i -n --``
        to run in the host's namespaces from a privileged container.
        """

        handles_execution = True
        NSENTER_PREFIX = "nsenter -t 1 -m -u -i -n -- "

        @override
        @staticmethod
        def make_names_data(name=None):
            if name is not None:
                from pyinfra.api.exceptions import InventoryError

                raise InventoryError("Cannot have more than one @nsenter")
            yield "@nsenter", {}, ["@nsenter"]

        @override
        def run_shell_command(
            self,
            command: Any,
            print_output: bool = False,
            print_input: bool = False,
            **arguments: Any,
        ) -> tuple[bool, Any]:
            from pyinfra.connectors.local import (
                execute_command_with_sudo_retry,
                run_local_process,
            )
            from pyinfra.connectors.util import make_unix_command_for_host

            arguments.pop("_get_pty", False)
            _timeout = arguments.pop("_timeout", None)
            _stdin = arguments.pop("_stdin", None)
            _success_exit_codes = arguments.pop("_success_exit_codes", None)

            unix_command = make_unix_command_for_host(
                self.state, self.host, command, **arguments
            )
            raw = unix_command.get_raw_value()
            actual_command = f"{self.NSENTER_PREFIX}{raw}"

            logger.debug("--> Running command via nsenter: %s", actual_command)

            if print_input:
                from click import echo

                echo(f"{self.host.print_prefix}>>> {actual_command}", err=True)

            def execute_command() -> tuple[int, Any]:
                return run_local_process(
                    actual_command,
                    stdin=_stdin,
                    timeout=_timeout,
                    print_output=print_output,
                    print_prefix=self.host.print_prefix,
                )

            return_code, combined_output = execute_command_with_sudo_retry(
                self.host,
                arguments,
                execute_command,
            )

            if _success_exit_codes:
                status = return_code in _success_exit_codes
            else:
                status = return_code == 0

            return status, combined_output

        @override
        def put_file(
            self,
            filename_or_io: Any,
            remote_filename: str,
            remote_temp_filename: str | None = None,
            print_output: bool = False,
            print_input: bool = False,
            **arguments: Any,
        ) -> bool:
            import os
            import shutil
            import tempfile

            _, temp_filename = tempfile.mkstemp()
            try:
                if isinstance(filename_or_io, str):
                    shutil.copy(filename_or_io, temp_filename)
                else:
                    with open(temp_filename, "wb") as f:
                        shutil.copyfileobj(filename_or_io, f)

                cmd = f"cp {temp_filename} {remote_filename}"
                status, _ = self.run_shell_command(
                    cmd, print_output=print_output, print_input=print_input
                )
                return status
            finally:
                os.unlink(temp_filename)

        @override
        def get_file(
            self,
            remote_filename: str,
            filename_or_io: Any,
            remote_temp_filename: str | None = None,
            print_output: bool = False,
            print_input: bool = False,
            **arguments: Any,
        ) -> bool:
            import os
            import shutil
            import tempfile

            _, temp_filename = tempfile.mkstemp()
            try:
                cmd = f"cp {remote_filename} {temp_filename}"
                status, _ = self.run_shell_command(
                    cmd, print_output=print_output, print_input=print_input
                )
                if not status:
                    return False

                if isinstance(filename_or_io, str):
                    shutil.copy(temp_filename, filename_or_io)
                else:
                    with open(temp_filename, "rb") as f:
                        shutil.copyfileobj(f, filename_or_io)
                return True
            finally:
                os.unlink(temp_filename)

    return NsenterConnector


def _register_nsenter_connector() -> None:
    """Register the @nsenter connector in pyInfra's connector registry."""
    from pyinfra.api.inventory import get_all_connectors, get_execution_connectors

    connector_cls = _create_nsenter_connector_class()

    all_connectors = get_all_connectors()
    all_connectors["nsenter"] = connector_cls

    exec_connectors = get_execution_connectors()
    exec_connectors["nsenter"] = connector_cls


# ---------------------------------------------------------------------------
# PyInfraHostOps — the strategy implementation
# ---------------------------------------------------------------------------


class PyInfraHostOps:
    """Host operations via pyInfra — declarative, idempotent.

    Combines the pyInfra strategy with a :class:`HostTransport`:

    - ``LocalTransport`` → pyInfra ``@local`` connector.
    - ``NsenterTransport`` → custom ``@nsenter`` connector.

    Each operation creates a fresh pyInfra state, schedules the relevant
    operations, executes them, and returns a :class:`HostOpResult`.

    All operations run with ``SUDO=True`` since host management
    requires root privileges.
    """

    def __init__(
        self,
        transport: HostTransport | None = None,
        config_dir: Path = DEFAULT_CONFIG_DIR,
        sudo: bool = True,
    ) -> None:
        _require_pyinfra()
        self.transport = transport or LocalTransport()
        self.config_dir = config_dir
        self.sudo = sudo

    @property
    def _target(self) -> str:
        """pyInfra inventory target string for the configured transport."""
        if self.transport.name == "nsenter":
            _register_nsenter_connector()
            return "@nsenter"
        return "@local"

    @property
    def can_manage_host(self) -> bool:
        return True

    # -- pyInfra state management -----------------------------------------

    def _build_state(self) -> tuple[Any, Any]:
        """Create a pyInfra State + Inventory for a single operation."""
        from pyinfra.api import Config, Inventory, State
        from pyinfra.api.connect import connect_all

        target = self._target
        inventory = Inventory(([target], {}))
        config = Config(SUDO=self.sudo)
        state = State(inventory=inventory, config=config)
        connect_all(state)
        return state, inventory

    def _run_ops(self, state: Any, inventory: Any) -> HostOpResult:
        """Execute scheduled operations and build a HostOpResult."""
        from pyinfra.api.operations import run_ops

        run_ops(state)

        host = inventory.get_host(self._target)
        results = state.get_results_for_host(host)

        success = results.error_ops == 0
        stdout = ""
        stderr = ""

        return HostOpResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            message="OK" if success else "Failed",
        )

    def _run_single_op(self, op_func: Any, *args: Any, **kwargs: Any) -> HostOpResult:
        """Schedule and execute a single pyInfra operation."""
        from pyinfra.api.operation import add_op

        try:
            state, inventory = self._build_state()
            add_op(state, op_func, *args, **kwargs)
            return self._run_ops(state, inventory)
        except Exception as e:
            return HostOpResult(success=False, stderr=str(e), message=str(e))

    def _get_fact(self, fact_class: Any, *args: Any) -> Any:
        """Execute a pyInfra fact query and return the result."""
        from pyinfra.api.facts import get_facts

        state, inventory = self._build_state()
        result = get_facts(state, fact_class, *args)
        host = inventory.get_host(self._target)
        return result.get(host)

    # -- User management --------------------------------------------------

    def create_user(
        self, username: str, shell: str, password: str | None = None
    ) -> HostOpResult:
        from pyinfra.operations import server

        result = self._run_single_op(
            server.user,
            name=f"Create user {username}",
            user=username,
            shell=shell,
            home=f"/home/{username}",
            create_home=True,
            present=True,
        )
        if not result.success:
            return result
        if password:
            return self.set_user_password(username, password)
        return result

    def set_user_password(self, username: str, password: str) -> HostOpResult:
        from pyinfra.operations import server

        # Use shell to run chpasswd, since pyInfra's password param
        # expects a pre-encrypted hash.
        return self._run_single_op(
            server.shell,
            name=f"Set password for {username}",
            commands=[f"echo '{username}:{password}' | chpasswd"],
        )

    def set_user_shell(self, username: str, shell: str) -> HostOpResult:
        from pyinfra.operations import server

        return self._run_single_op(
            server.user,
            name=f"Set shell for {username}",
            user=username,
            shell=shell,
            present=True,
        )

    def delete_user(self, username: str, remove_home: bool = True) -> HostOpResult:
        from pyinfra.operations import server

        result = self._run_single_op(
            server.user,
            name=f"Delete user {username}",
            user=username,
            present=False,
        )
        if not result.success or not remove_home:
            return result
        # Remove home directory separately
        return self._run_single_op(
            server.shell,
            name=f"Remove home for {username}",
            commands=[f"rm -rf /home/{username}"],
        )

    # -- Service management -----------------------------------------------

    def stop_service(self, service: str) -> HostOpResult:
        from pyinfra.operations import systemd

        return self._run_single_op(
            systemd.service,
            name=f"Stop {service}",
            service=service,
            running=False,
        )

    def start_service(self, service: str) -> HostOpResult:
        from pyinfra.operations import systemd

        return self._run_single_op(
            systemd.service,
            name=f"Start {service}",
            service=service,
            running=True,
        )

    def disable_service(self, service: str) -> HostOpResult:
        from pyinfra.operations import systemd

        return self._run_single_op(
            systemd.service,
            name=f"Disable {service}",
            service=service,
            enabled=False,
        )

    # -- Host introspection -----------------------------------------------

    def detect_os(self) -> str:
        from pyinfra.facts.server import Os

        try:
            os_id = self._get_fact(Os)
            return str(os_id) if os_id else "unknown"
        except Exception:
            return "unknown"

    def query_package_version(self, package: str) -> str | None:
        from pyinfra.facts.rpm import RpmPackage

        try:
            info = self._get_fact(RpmPackage, package)
            if info and isinstance(info, dict):
                ver = info.get("version", "")
                if ver and ver[0].isdigit():
                    return ver.split("-")[0]
        except Exception:
            pass
        return None

    def query_packages(self, pattern: str) -> list[str]:
        from pyinfra.facts.rpm import RpmPackages

        try:
            packages = self._get_fact(RpmPackages)
            if packages and isinstance(packages, dict):
                return [
                    name for name in packages
                    if _matches_pattern(name, pattern)
                ]
        except Exception:
            pass
        return []


def _matches_pattern(name: str, pattern: str) -> bool:
    """Simple glob match for package names against a pattern like 'php*-php-fpm'."""
    import fnmatch

    return fnmatch.fnmatch(name, pattern)


# ---------------------------------------------------------------------------
# PyInfraSystemOps — adapts PyInfraHostOps to the SystemOps protocol
# ---------------------------------------------------------------------------


class PyInfraSystemOps:
    """Adapter that makes :class:`PyInfraHostOps` satisfy the
    ``SystemOps`` protocol used by :class:`~nopanel.migrate.MigrationEngine`.

    This allows v1→v2 migration to run via pyInfra with any transport
    (local or nsenter) instead of direct subprocess calls.
    """

    def __init__(
        self,
        host_ops: PyInfraHostOps | None = None,
        config_dir: Path = DEFAULT_CONFIG_DIR,
    ) -> None:
        self.host_ops = host_ops or PyInfraHostOps(config_dir=config_dir)
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
        import subprocess

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

        # 4. Host RPM query via pyInfra
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
