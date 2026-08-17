"""Tests for nopanel.pyinfra_backend — pyInfra host operations backend.

Tests are designed to work without pyInfra installed by mocking the
pyInfra API at the module level. Tests that require real pyInfra
are marked with ``@pytest.mark.pyinfra`` and skip if not installed.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nopanel.host_ops import HostOpResult, LocalTransport


# ---------------------------------------------------------------------------
# Mock pyInfra module — installed into sys.modules for tests
# ---------------------------------------------------------------------------


def _install_mock_pyinfra():
    """Install a mock pyInfra package into sys.modules."""
    pyinfra_mod = types.ModuleType("pyinfra")
    api_mod = types.ModuleType("pyinfra.api")
    config_mod = types.ModuleType("pyinfra.api.config")
    inventory_mod = types.ModuleType("pyinfra.api.inventory")
    state_mod = types.ModuleType("pyinfra.api.state")
    connect_mod = types.ModuleType("pyinfra.api.connect")
    operation_mod = types.ModuleType("pyinfra.api.operation")
    operations_mod = types.ModuleType("pyinfra.api.operations")
    facts_mod = types.ModuleType("pyinfra.api.facts")

    # Operations submodules
    server_mod = types.ModuleType("pyinfra.operations.server")
    systemd_mod = types.ModuleType("pyinfra.operations.systemd")

    # Facts submodules
    server_facts_mod = types.ModuleType("pyinfra.facts.server")
    rpm_facts_mod = types.ModuleType("pyinfra.facts.rpm")

    # Wire up the package hierarchy
    pyinfra_mod.api = api_mod
    api_mod.config = config_mod
    api_mod.inventory = inventory_mod
    api_mod.state = state_mod
    api_mod.connect = connect_mod
    api_mod.operation = operation_mod
    api_mod.operations = operations_mod
    api_mod.facts = facts_mod

    operations_mod.server = server_mod
    operations_mod.systemd = systemd_mod

    # Mock operation functions — they return MagicMock (OperationMeta-like)
    server_mod.user = MagicMock()
    server_mod.shell = MagicMock()
    systemd_mod.service = MagicMock()

    # Mock Config, Inventory, State — accessible from pyinfra.api directly
    # Configure so that State() returns a mock state with proper results
    mock_host = MagicMock(name="host")

    mock_results = MagicMock(name="results")
    mock_results.error_ops = 0

    mock_state = MagicMock(name="state")
    mock_state.get_results_for_host.return_value = mock_results
    mock_state.get_op_order.return_value = []

    config_mod.Config = MagicMock()
    inventory_mod.Inventory = MagicMock()
    state_mod.State = MagicMock(return_value=mock_state)
    api_mod.Config = config_mod.Config
    api_mod.Inventory = inventory_mod.Inventory
    api_mod.State = state_mod.State

    # Inventory() returns a mock inventory where get_host returns mock_host
    mock_inventory = MagicMock(name="inventory")
    mock_inventory.get_host.return_value = mock_host
    inventory_mod.Inventory.return_value = mock_inventory

    # Mock connect_all
    connect_mod.connect_all = MagicMock()

    # Mock add_op — returns dict {host: OperationMeta}
    operation_mod.add_op = MagicMock(return_value={})

    # Mock run_ops
    operations_mod.run_ops = MagicMock()

    # Mock get_facts — returns dict {host: value}
    facts_mod.get_facts = MagicMock(return_value={})

    # Mock fact classes
    server_facts_mod.Os = MagicMock()
    rpm_facts_mod.RpmPackage = MagicMock()
    rpm_facts_mod.RpmPackages = MagicMock()

    # Install all modules
    sys.modules["pyinfra"] = pyinfra_mod
    sys.modules["pyinfra.api"] = api_mod
    sys.modules["pyinfra.api.config"] = config_mod
    sys.modules["pyinfra.api.inventory"] = inventory_mod
    sys.modules["pyinfra.api.state"] = state_mod
    sys.modules["pyinfra.api.connect"] = connect_mod
    sys.modules["pyinfra.api.operation"] = operation_mod
    sys.modules["pyinfra.api.operations"] = operations_mod
    sys.modules["pyinfra.api.facts"] = facts_mod
    sys.modules["pyinfra.operations"] = operations_mod
    sys.modules["pyinfra.operations.server"] = server_mod
    sys.modules["pyinfra.operations.systemd"] = systemd_mod
    sys.modules["pyinfra.facts"] = facts_mod
    sys.modules["pyinfra.facts.server"] = server_facts_mod
    sys.modules["pyinfra.facts.rpm"] = rpm_facts_mod

    return {
        "server": server_mod,
        "systemd": systemd_mod,
        "Config": config_mod.Config,
        "Inventory": inventory_mod.Inventory,
        "State": state_mod.State,
        "connect_all": connect_mod.connect_all,
        "add_op": operation_mod.add_op,
        "run_ops": operations_mod.run_ops,
        "get_facts": facts_mod.get_facts,
        "Os": server_facts_mod.Os,
        "RpmPackage": rpm_facts_mod.RpmPackage,
        "RpmPackages": rpm_facts_mod.RpmPackages,
        "host": mock_host,
        "inventory": mock_inventory,
    }


@pytest.fixture
def mock_pyinfra():
    """Install mock pyInfra and yield the mock components."""
    mocks = _install_mock_pyinfra()
    yield mocks
    # Clean up — remove pyInfra modules so other tests aren't affected
    for key in list(sys.modules.keys()):
        if key.startswith("pyinfra"):
            del sys.modules[key]


@pytest.fixture
def pyinfra_ops(mock_pyinfra, tmp_path: Path):
    """Create a PyInfraHostOps with mocked pyInfra."""
    # Also need to remove the already-imported module so it re-imports
    # with our mock
    if "nopanel.pyinfra_backend" in sys.modules:
        del sys.modules["nopanel.pyinfra_backend"]
    from nopanel.pyinfra_backend import PyInfraHostOps

    ops = PyInfraHostOps(transport=LocalTransport(), config_dir=tmp_path)
    return ops, mock_pyinfra


# ---------------------------------------------------------------------------
# Import / availability tests
# ---------------------------------------------------------------------------


class TestPyInfraAvailability:
    def test_import_error_without_pyinfra(self):
        """PyInfraHostOps raises ImportError if pyInfra can't be imported."""
        # Simulate pyInfra not being importable by hiding it
        saved = {}
        for key in list(sys.modules.keys()):
            if key.startswith("pyinfra"):
                saved[key] = sys.modules.pop(key)
        if "nopanel.pyinfra_backend" in sys.modules:
            saved["nopanel.pyinfra_backend"] = sys.modules.pop("nopanel.pyinfra_backend")

        # Block re-import of pyInfra
        import builtins

        real_import = builtins.__import__

        def _block_pyinfra(name, *args, **kwargs):
            if name == "pyinfra":
                raise ImportError("No module named 'pyinfra'")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = _block_pyinfra
        try:
            from nopanel.pyinfra_backend import PyInfraHostOps

            with pytest.raises(ImportError, match="pyInfra backend requires"):
                PyInfraHostOps()
        finally:
            builtins.__import__ = real_import
            sys.modules.update(saved)


# ---------------------------------------------------------------------------
# PyInfraHostOps — user management
# ---------------------------------------------------------------------------


class TestPyInfraUserManagement:
    def test_can_manage_host_true(self, pyinfra_ops):
        ops, _ = pyinfra_ops
        assert ops.can_manage_host is True

    def test_create_user_no_password(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.create_user("alice", "/sbin/nologin")

        assert result.success is True
        m["add_op"].assert_called_once()
        # Verify server.user was the operation used
        args, kwargs = m["add_op"].call_args
        assert kwargs.get("user") == "alice"
        assert kwargs.get("shell") == "/sbin/nologin"

    def test_create_user_with_password(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.create_user("alice", "/bin/bash", "secret123")

        assert result.success is True
        # Two operations: useradd + chpasswd via shell
        assert m["add_op"].call_count == 2

    def test_set_user_password(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.set_user_password("alice", "newpass")

        assert result.success is True
        m["add_op"].assert_called_once()
        args, kwargs = m["add_op"].call_args
        # Should use server.shell with chpasswd
        assert "chpasswd" in str(kwargs.get("commands", []))

    def test_set_user_shell(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.set_user_shell("alice", "/bin/bash")

        assert result.success is True
        m["add_op"].assert_called_once()
        args, kwargs = m["add_op"].call_args
        assert kwargs.get("user") == "alice"
        assert kwargs.get("shell") == "/bin/bash"

    def test_delete_user_with_home(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.delete_user("alice", remove_home=True)

        assert result.success is True
        # Two operations: user delete + rm home
        assert m["add_op"].call_count == 2

    def test_delete_user_without_home(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.delete_user("alice", remove_home=False)

        assert result.success is True
        assert m["add_op"].call_count == 1

    def test_create_user_failure(self, pyinfra_ops):
        ops, m = pyinfra_ops
        # Make run_ops raise to simulate failure
        m["run_ops"].side_effect = Exception("Connection failed")

        result = ops.create_user("alice", "/sbin/nologin")
        assert result.success is False
        assert "Connection failed" in result.stderr


# ---------------------------------------------------------------------------
# PyInfraHostOps — service management
# ---------------------------------------------------------------------------


class TestPyInfraServiceManagement:
    def test_stop_service(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.stop_service("httpd")

        assert result.success is True
        m["add_op"].assert_called_once()
        args, kwargs = m["add_op"].call_args
        assert kwargs.get("service") == "httpd"
        assert kwargs.get("running") is False

    def test_start_service(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.start_service("mariadb")

        assert result.success is True
        args, kwargs = m["add_op"].call_args
        assert kwargs.get("running") is True

    def test_disable_service(self, pyinfra_ops):
        ops, m = pyinfra_ops
        result = ops.disable_service("httpd")

        assert result.success is True
        args, kwargs = m["add_op"].call_args
        assert kwargs.get("enabled") is False


# ---------------------------------------------------------------------------
# PyInfraHostOps — host introspection
# ---------------------------------------------------------------------------


class TestPyInfraIntrospection:
    def test_detect_os(self, pyinfra_ops):
        ops, m = pyinfra_ops
        # Mock get_facts to return an OS ID keyed by the same host mock
        m["get_facts"].return_value = {m["host"]: "almalinux"}

        os_id = ops.detect_os()
        assert os_id == "almalinux"

    def test_detect_os_failure(self, pyinfra_ops):
        ops, m = pyinfra_ops
        m["get_facts"].side_effect = Exception("SSH failed")

        assert ops.detect_os() == "unknown"

    def test_query_package_version(self, pyinfra_ops):
        ops, m = pyinfra_ops
        m["get_facts"].return_value = {
            m["host"]: {"version": "10.11.8-1.el9", "name": "MariaDB-server"}
        }

        ver = ops.query_package_version("MariaDB-server")
        assert ver == "10.11.8"

    def test_query_package_version_not_found(self, pyinfra_ops):
        ops, m = pyinfra_ops
        m["get_facts"].return_value = {m["host"]: None}

        assert ops.query_package_version("nonexistent") is None

    def test_query_packages(self, pyinfra_ops):
        ops, m = pyinfra_ops
        m["get_facts"].return_value = {
            m["host"]: {
                "php82-php-fpm": ["8.2.15"],
                "php83-php-fpm": ["8.3.2"],
                "httpd": ["2.4.57"],
            }
        }

        packages = ops.query_packages("php*-php-fpm")
        assert "php82-php-fpm" in packages
        assert "php83-php-fpm" in packages
        assert "httpd" not in packages

    def test_query_packages_failure(self, pyinfra_ops):
        ops, m = pyinfra_ops
        m["get_facts"].side_effect = Exception("Connection lost")

        assert ops.query_packages("php*") == []


# ---------------------------------------------------------------------------
# PyInfraSystemOps — adapter for MigrationEngine
# ---------------------------------------------------------------------------


class TestPyInfraSystemOps:
    @pytest.fixture
    def sysops(self, pyinfra_ops, tmp_path: Path):
        ops, m = pyinfra_ops
        from nopanel.pyinfra_backend import PyInfraSystemOps

        return PyInfraSystemOps(host_ops=ops, config_dir=tmp_path), m

    def test_detect_os(self, sysops):
        sops, m = sysops
        m["get_facts"].return_value = {m["host"]: "rocky"}
        assert sops.detect_os() == "rocky"

    def test_stop_service(self, sysops):
        sops, _ = sysops
        assert sops.stop_service("httpd") is True

    def test_start_service(self, sysops):
        sops, _ = sysops
        assert sops.start_service("mariadb") is True

    def test_disable_service(self, sysops):
        sops, _ = sysops
        assert sops.disable_service("httpd") is True

    def test_get_installed_php_versions(self, sysops):
        sops, m = sysops
        m["get_facts"].return_value = {
            m["host"]: {
                "php82-php-fpm": ["8.2.15"],
                "php83-php-fpm": ["8.3.2"],
            }
        }
        versions = sops.get_installed_php_versions()
        assert "8.2" in versions
        assert "8.3" in versions

    def test_get_installed_php_versions_empty(self, sysops):
        sops, m = sysops
        m["get_facts"].return_value = {m["host"]: {}}
        assert sops.get_installed_php_versions() == []


# ---------------------------------------------------------------------------
# auto_detect_host_ops — pyInfra branch
# ---------------------------------------------------------------------------


class TestAutoDetectPyInfra:
    def test_prefer_pyinfra_returns_pyinfra(self, mock_pyinfra, tmp_path: Path):
        if "nopanel.pyinfra_backend" in sys.modules:
            del sys.modules["nopanel.pyinfra_backend"]
        from nopanel.host_ops import auto_detect_host_ops

        ops = auto_detect_host_ops(config_dir=tmp_path, prefer_pyinfra=True)
        assert ops.can_manage_host is True

    def test_falls_back_to_pending_without_pyinfra(self, tmp_path: Path):
        # Without prefer_pyinfra, auto_detect should never try pyInfra,
        # so it falls back to pending-commands (nsenter not available).
        from nopanel.host_ops import auto_detect_host_ops

        ops = auto_detect_host_ops(config_dir=tmp_path)
        assert ops.can_manage_host is False  # PendingCommandsHostOps


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestOrchestrator:
    def test_build_inventory_local(self, mock_pyinfra, tmp_path: Path):
        from nopanel.orchestrator import build_inventory

        # Create minimal config
        from nopanel.config import create_default_config, save_config

        config = create_default_config()
        save_config(config, tmp_path)

        inventory, config_obj = build_inventory(config_dir=tmp_path)
        assert inventory is not None
        assert config_obj is not None
