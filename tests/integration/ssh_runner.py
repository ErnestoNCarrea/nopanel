"""SSH command execution and file transfer via paramiko."""

from __future__ import annotations

import logging
import shlex
import time
from pathlib import Path

import paramiko

logger = logging.getLogger(__name__)


class SSHRunner:
    """Execute commands on a remote host via SSH and transfer files via SCP."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "root",
        key_filename: str | None = None,
        password: str | None = None,
        connect_timeout: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.key_filename = key_filename
        self.password = password
        self.connect_timeout = connect_timeout
        self._client: paramiko.SSHClient | None = None

    # -- Connection management --------------------------------------------

    def connect(self, retries: int = 30, delay: int = 5) -> None:
        """Connect with retries — VM may take time to boot and start sshd."""
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    key_filename=self.key_filename,
                    password=self.password,
                    timeout=self.connect_timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
                self._client = client
                logger.info("SSH connected to %s:%s as %s", self.host, self.port, self.username)
                return
            except Exception as e:
                last_err = e
                logger.debug("SSH attempt %d/%d failed: %s", attempt, retries, e)
                time.sleep(delay)
        raise ConnectionError(f"Failed to SSH to {self.host}:{self.port} after {retries} attempts: {last_err}")

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> SSHRunner:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    # -- Command execution ------------------------------------------------

    def run(self, command: str, timeout: int = 120) -> CommandOutput:
        """Execute a command and return stdout/stderr/exit_code."""
        if not self._client:
            raise RuntimeError("SSH not connected — call connect() first")
        # Use login shell so PATH includes /root/.local/bin, /usr/local/bin, etc.
        full_cmd = f"bash -l -c {shlex.quote(command)}"
        stdin, stdout, stderr = self._client.exec_command(full_cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return CommandOutput(exit_code=exit_code, stdout=out, stderr=err)

    def run_check(self, command: str, timeout: int = 120) -> str:
        """Execute a command, raise on failure, return stdout."""
        result = self.run(command, timeout=timeout)
        if result.exit_code != 0:
            raise RuntimeError(
                f"Command failed (exit {result.exit_code}): {command}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result.stdout.strip()

    def put_file(self, local_path: str | Path, remote_path: str) -> None:
        """Upload a file via SFTP."""
        if not self._client:
            raise RuntimeError("SSH not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()

    def put_content(self, content: str, remote_path: str) -> None:
        """Write string content to a remote file via SFTP."""
        if not self._client:
            raise RuntimeError("SSH not connected")
        sftp = self._client.open_sftp()
        try:
            import io

            sftp.putfo(io.BytesIO(content.encode()), remote_path)
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str | Path) -> None:
        """Download a file via SFTP."""
        if not self._client:
            raise RuntimeError("SSH not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, str(local_path))
        finally:
            sftp.close()

    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the remote host."""
        result = self.run(f"test -f {remote_path} && echo yes || echo no")
        return "yes" in result.stdout


class CommandOutput:
    """Result of an SSH command execution."""

    __slots__ = ("exit_code", "stdout", "stderr")

    def __init__(self, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def __repr__(self) -> str:
        return f"CommandOutput(exit_code={self.exit_code}, stdout={self.stdout!r}, stderr={self.stderr!r})"
