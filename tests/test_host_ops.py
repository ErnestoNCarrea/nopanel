"""Tests for nopanel.host_ops — pluggable host operations backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from nopanel.docker_manager import CommandResult
from nopanel.host_ops import (
    LOGIN_SHELLS,
    HostOpResult,
    NoOpHostOps,
    NsenterHostOps,
    NsenterSystemOps,
    PendingCommandsHostOps,
)
from nopanel.models import LoginType


# ---------------------------------------------------------------------------
# Mock runner for NsenterHostOps
# ---------------------------------------------------------------------------


class MockHostRunner:
    """Records all calls and returns configurable results."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[tuple[list[str], str | None]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def run(self, args: list[str], stdin: str | None = None) -> CommandResult:
        self.calls.append((list(args), stdin))
        return CommandResult(
            returncode=self._returncode,
            stdout=self._stdout,
            stderr=self._stderr,
        )


# ---------------------------------------------------------------------------
# NoOpHostOps
# ---------------------------------------------------------------------------


class TestNoOpHostOps:
    def test_can_manage_host_false(self):
        ops = NoOpHostOps()
        assert ops.can_manage_host is False

    def test_create_user_skipped(self):
        ops = NoOpHostOps()
        result = ops.create_user("alice", "/bin/bash", "password")
        assert result.success is True
        assert result.executed is False

    def test_delete_user_skipped(self):
        ops = NoOpHostOps()
        result = ops.delete_user("alice")
        assert result.success is True
        assert result.executed is False

    def test_service_ops_skipped(self):
        ops = NoOpHostOps()
        assert ops.stop_service("httpd").success is True
        assert ops.start_service("httpd").success is True
        assert ops.disable_service("httpd").success is True

    def test_detect_os_unknown(self):
        ops = NoOpHostOps()
        assert ops.detect_os() == "unknown"

    def test_query_package_version_none(self):
        ops = NoOpHostOps()
        assert ops.query_package_version("mariadb-server") is None

    def test_query_packages_empty(self):
        ops = NoOpHostOps()
        assert ops.query_packages("php*") == []


# ---------------------------------------------------------------------------
# PendingCommandsHostOps
# ---------------------------------------------------------------------------


class TestPendingCommandsHostOps:
    def test_can_manage_host_false(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        assert ops.can_manage_host is False

    def test_create_user_queues_commands(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.create_user("alice", "/sbin/nologin", "secret123")

        assert result.success is True
        assert result.executed is False
        assert len(result.commands) == 2
        assert "useradd" in result.commands[0]
        assert "alice" in result.commands[0]
        assert "chpasswd" in result.commands[1]

        pending = tmp_path / "pending-host-cmds.sh"
        assert pending.exists()
        content = pending.read_text()
        assert "useradd" in content
        assert "chpasswd" in content

    def test_create_user_no_password(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.create_user("bob", "/bin/bash")

        assert result.success is True
        assert len(result.commands) == 1
        assert "useradd" in result.commands[0]

    def test_set_user_password(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.set_user_password("alice", "newpass456")

        assert result.success is True
        assert len(result.commands) == 1
        assert "chpasswd" in result.commands[0]

    def test_set_user_shell(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.set_user_shell("alice", "/bin/bash")

        assert result.success is True
        assert len(result.commands) == 1
        assert "chsh" in result.commands[0]

    def test_delete_user_with_home(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.delete_user("alice", remove_home=True)

        assert result.success is True
        assert "userdel -r" in result.commands[0]

    def test_delete_user_without_home(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        result = ops.delete_user("alice", remove_home=False)

        assert result.success is True
        assert "userdel" in result.commands[0]
        assert "-r" not in result.commands[0]

    def test_multiple_ops_append_to_same_file(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        ops.create_user("alice", "/sbin/nologin", "pass12345")
        ops.delete_user("bob")

        pending = tmp_path / "pending-host-cmds.sh"
        content = pending.read_text()
        assert "useradd" in content
        assert "userdel" in content
        # Two batch headers
        assert content.count("# batch:") == 2

    def test_pending_file_permissions(self, tmp_path: Path):
        ops = PendingCommandsHostOps(config_dir=tmp_path)
        ops.create_user("alice", "/sbin/nologin")

        pending = tmp_path / "pending-host-cmds.sh"
        # File should be chmod 600
        assert oct(pending.stat().st_mode)[-3:] == "600"


# ---------------------------------------------------------------------------
# NsenterHostOps
# ---------------------------------------------------------------------------


class TestNsenterHostOps:
    def test_can_manage_host_true(self):
        ops = NsenterHostOps(runner=MockHostRunner())
        assert ops.can_manage_host is True

    def test_nsenter_prefix_in_all_calls(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        ops.stop_service("httpd")

        assert len(runner.calls) == 1
        args = runner.calls[0][0]
        assert args[:5] == ["nsenter", "-t", "1", "-m", "-u", "-i", "-n"][:5]
        assert args[0] == "nsenter"
        assert "-t" in args
        assert "1" in args

    def test_create_user(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.create_user("alice", "/sbin/nologin", "pass12345")

        assert result.success is True
        # Two calls: useradd + chpasswd
        assert len(runner.calls) == 2
        assert "useradd" in runner.calls[0][0]
        assert "-m" in runner.calls[0][0]
        assert "-s" in runner.calls[0][0]
        assert runner.calls[1][1] == "alice:pass12345\n"  # stdin for chpasswd

    def test_create_user_no_password(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.create_user("alice", "/sbin/nologin")

        assert result.success is True
        assert len(runner.calls) == 1

    def test_create_user_failure(self):
        runner = MockHostRunner(returncode=1, stderr="user already exists")
        ops = NsenterHostOps(runner=runner)
        result = ops.create_user("alice", "/sbin/nologin")

        assert result.success is False
        assert "user already exists" in result.stderr

    def test_set_user_password(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.set_user_password("alice", "newpass")

        assert result.success is True
        assert len(runner.calls) == 1
        assert runner.calls[0][1] == "alice:newpass\n"

    def test_set_user_shell(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.set_user_shell("alice", "/bin/bash")

        assert result.success is True
        args = runner.calls[0][0]
        assert "chsh" in args
        assert "/bin/bash" in args

    def test_delete_user_with_home(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.delete_user("alice", remove_home=True)

        assert result.success is True
        args = runner.calls[0][0]
        assert "userdel" in args
        assert "-r" in args

    def test_delete_user_without_home(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.delete_user("alice", remove_home=False)

        assert result.success is True
        args = runner.calls[0][0]
        assert "userdel" in args
        assert "-r" not in args

    def test_stop_service(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.stop_service("httpd")

        assert result.success is True
        args = runner.calls[0][0]
        assert "systemctl" in args
        assert "stop" in args
        assert "httpd" in args

    def test_start_service(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.start_service("mariadb")

        assert result.success is True
        args = runner.calls[0][0]
        assert "start" in args

    def test_disable_service(self):
        runner = MockHostRunner()
        ops = NsenterHostOps(runner=runner)
        result = ops.disable_service("httpd")

        assert result.success is True
        args = runner.calls[0][0]
        assert "disable" in args

    def test_detect_os(self):
        runner = MockHostRunner(
            stdout='ID="almalinux"\nVERSION="9.4"\n'
        )
        ops = NsenterHostOps(runner=runner)
        os_id = ops.detect_os()
        assert os_id == "almalinux"

    def test_detect_os_failure(self):
        runner = MockHostRunner(returncode=1)
        ops = NsenterHostOps(runner=runner)
        assert ops.detect_os() == "unknown"

    def test_query_package_version(self):
        runner = MockHostRunner(stdout="10.11.8")
        ops = NsenterHostOps(runner=runner)
        ver = ops.query_package_version("MariaDB-server")
        assert ver == "10.11.8"

    def test_query_package_version_not_found(self):
        runner = MockHostRunner(returncode=1, stderr="not installed")
        ops = NsenterHostOps(runner=runner)
        assert ops.query_package_version("nonexistent") is None

    def test_query_packages(self):
        runner = MockHostRunner(
            stdout="php82-php-fpm-8.2.15-1.el9.x86_64\nphp83-php-fpm-8.3.2-1.el9.x86_64\n"
        )
        ops = NsenterHostOps(runner=runner)
        packages = ops.query_packages("php*-php-fpm")
        assert len(packages) == 2
        assert "php82-php-fpm" in packages[0]

    def test_query_packages_failure(self):
        runner = MockHostRunner(returncode=1)
        ops = NsenterHostOps(runner=runner)
        assert ops.query_packages("php*") == []


# ---------------------------------------------------------------------------
# NsenterSystemOps (adapter for MigrationEngine)
# ---------------------------------------------------------------------------


class TestNsenterSystemOps:
    def test_detect_os(self):
        host_ops = NsenterHostOps(runner=MockHostRunner(stdout='ID="rocky"\n'))
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.detect_os() == "rocky"

    def test_stop_service(self):
        host_ops = NsenterHostOps(runner=MockHostRunner())
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.stop_service("httpd") is True

    def test_stop_service_failure(self):
        host_ops = NsenterHostOps(runner=MockHostRunner(returncode=1))
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.stop_service("httpd") is False

    def test_start_service(self):
        host_ops = NsenterHostOps(runner=MockHostRunner())
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.start_service("mariadb") is True

    def test_disable_service(self):
        host_ops = NsenterHostOps(runner=MockHostRunner())
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.disable_service("httpd") is True

    def test_get_installed_php_versions(self):
        runner = MockHostRunner(
            stdout="php82-php-fpm-8.2.15-1.el9.x86_64\nphp83-php-fpm-8.3.2-1.el9.x86_64\n"
        )
        host_ops = NsenterHostOps(runner=runner)
        sysops = NsenterSystemOps(host_ops=host_ops)
        versions = sysops.get_installed_php_versions()
        assert "8.2" in versions
        assert "8.3" in versions

    def test_get_installed_php_versions_empty(self):
        host_ops = NsenterHostOps(runner=MockHostRunner(returncode=1))
        sysops = NsenterSystemOps(host_ops=host_ops)
        assert sysops.get_installed_php_versions() == []


# ---------------------------------------------------------------------------
# LOGIN_SHELLS constant
# ---------------------------------------------------------------------------


class TestLoginShells:
    def test_ssh_shell(self):
        assert LOGIN_SHELLS[LoginType.SSH] == "/bin/bash"

    def test_sftp_shell(self):
        assert LOGIN_SHELLS[LoginType.SFTP] == "/sbin/nologin"

    def test_no_login_shell(self):
        assert LOGIN_SHELLS[LoginType.NO] == "/sbin/nologin"


# ---------------------------------------------------------------------------
# HostOpResult
# ---------------------------------------------------------------------------


class TestHostOpResult:
    def test_success_default(self):
        r = HostOpResult(success=True)
        assert r.success is True
        assert r.message == ""
        assert r.executed is True
        assert r.commands == []

    def test_with_commands(self):
        r = HostOpResult(success=True, commands=["useradd alice"], executed=False)
        assert r.executed is False
        assert len(r.commands) == 1
