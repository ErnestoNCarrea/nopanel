"""Tests for nopanel.host_ops — transports, pending-commands, no-op."""

from __future__ import annotations

from pathlib import Path

import pytest

from nopanel.docker_manager import CommandResult
from nopanel.host_ops import (
    LOGIN_SHELLS,
    HostOpResult,
    HostTransport,
    LocalTransport,
    NoOpHostOps,
    NsenterTransport,
    PendingCommandsHostOps,
)
from nopanel.models import LoginType


# ---------------------------------------------------------------------------
# Mock transport for testing
# ---------------------------------------------------------------------------


class MockTransport:
    """Records all calls and returns configurable results."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[tuple[list[str], str | None]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    @property
    def name(self) -> str:
        return "mock"

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
# LocalTransport
# ---------------------------------------------------------------------------


class TestLocalTransport:
    def test_name(self):
        t = LocalTransport()
        assert t.name == "local"

    def test_run_success(self):
        t = LocalTransport()
        result = t.run(["true"])
        assert result.returncode == 0

    def test_run_failure(self):
        t = LocalTransport()
        result = t.run(["false"])
        assert result.returncode != 0

    def test_run_with_stdout(self):
        t = LocalTransport()
        result = t.run(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_run_with_stdin(self):
        t = LocalTransport()
        result = t.run(["cat"], stdin="test input\n")
        assert result.returncode == 0
        assert "test input" in result.stdout


# ---------------------------------------------------------------------------
# NsenterTransport
# ---------------------------------------------------------------------------


class TestNsenterTransport:
    def test_name(self):
        t = NsenterTransport()
        assert t.name == "nsenter"

    def test_prefix_format(self):
        assert NsenterTransport.PREFIX == ["nsenter", "-t", "1", "-m", "-u", "-i", "-n"]

    def test_run_prefixes_command(self):
        """Verify that NsenterTransport prefixes args with nsenter."""
        import subprocess
        from unittest.mock import patch

        t = NsenterTransport()
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            t.run(["systemctl", "stop", "httpd"])
            call_args = mock_run.call_args[0][0]
            assert call_args[:7] == ["nsenter", "-t", "1", "-m", "-u", "-i", "-n"]
            assert call_args[7:] == ["systemctl", "stop", "httpd"]


# ---------------------------------------------------------------------------
# HostTransport protocol
# ---------------------------------------------------------------------------


class TestHostTransportProtocol:
    def test_mock_transport_satisfies_protocol(self):
        t = MockTransport()
        assert hasattr(t, "name")
        assert hasattr(t, "run")
        assert t.name == "mock"

    def test_local_transport_satisfies_protocol(self):
        t = LocalTransport()
        assert hasattr(t, "name")
        assert hasattr(t, "run")
        assert t.name == "local"

    def test_nsenter_transport_satisfies_protocol(self):
        t = NsenterTransport()
        assert hasattr(t, "name")
        assert hasattr(t, "run")
        assert t.name == "nsenter"


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
