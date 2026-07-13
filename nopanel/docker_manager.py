"""Docker interaction layer — wraps Docker SDK for compose operations.

The DockerManager class accepts a Docker client instance (injectable for tests).
All compose operations run via `docker compose` CLI commands for reliability.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_COMPOSE_FILE = Path("/etc/nopanel/generated/docker-compose.yml")


# ---------------------------------------------------------------------------
# Protocols for dependency injection
# ---------------------------------------------------------------------------


class CommandRunner(Protocol):
    """Protocol for running shell commands (injectable for testing)."""

    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult: ...


@dataclass(frozen=True)
class CommandResult:
    """Result of a shell command execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# Default command runner (uses subprocess)
# ---------------------------------------------------------------------------


class SubprocessRunner:
    """Default command runner using subprocess."""

    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        logger.debug("Running: %s (cwd=%s)", " ".join(args), cwd)
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


# ---------------------------------------------------------------------------
# Docker Manager
# ---------------------------------------------------------------------------


class DockerManager:
    """Manages Docker Compose operations for noPanel services.

    All operations use `docker compose` CLI commands against a generated
    docker-compose.yml file.
    """

    def __init__(
        self,
        compose_file: Path = DEFAULT_COMPOSE_FILE,
        runner: CommandRunner | None = None,
    ) -> None:
        self.compose_file = compose_file
        self.runner = runner or SubprocessRunner()

    def _compose_cmd(self, *args: str) -> list[str]:
        """Build a docker compose command."""
        return ["docker", "compose", "-f", str(self.compose_file), *args]

    def compose_up(self, services: list[str] | None = None, detach: bool = True) -> CommandResult:
        """Start services (docker compose up)."""
        cmd = self._compose_cmd("up")
        if detach:
            cmd.append("-d")
        if services:
            cmd.extend(services)
        return self.runner.run(cmd)

    def compose_down(self, services: list[str] | None = None) -> CommandResult:
        """Stop and remove containers.

        When services is specified, uses stop+rm instead of 'down' with service
        names, since 'docker compose down [SERVICE...]' has inconsistent support
        across Docker Compose versions.
        """
        if services:
            # Stop the specific services first
            stop_result = self.compose_stop(services)
            if not stop_result.success:
                return stop_result
            # Remove the stopped containers
            cmd = self._compose_cmd("rm", "-f")
            cmd.extend(services)
            return self.runner.run(cmd)
        else:
            cmd = self._compose_cmd("down")
            return self.runner.run(cmd)

    def compose_stop(self, services: list[str] | None = None) -> CommandResult:
        """Stop specific services or all."""
        cmd = self._compose_cmd("stop")
        if services:
            cmd.extend(services)
        return self.runner.run(cmd)

    def compose_restart(self, services: list[str] | None = None) -> CommandResult:
        """Restart specific services or all."""
        cmd = self._compose_cmd("restart")
        if services:
            cmd.extend(services)
        return self.runner.run(cmd)

    def compose_pull(self, services: list[str] | None = None) -> CommandResult:
        """Pull latest images for services."""
        cmd = self._compose_cmd("pull")
        if services:
            cmd.extend(services)
        return self.runner.run(cmd)

    def compose_ps(self) -> CommandResult:
        """List running containers (docker compose ps)."""
        return self.runner.run(self._compose_cmd("ps", "--format", "json"))

    def build_image(
        self,
        dockerfile_dir: Path,
        tag: str,
        dockerfile: str = "Dockerfile",
    ) -> CommandResult:
        """Build a custom Docker image."""
        return self.runner.run(
            [
                "docker",
                "build",
                "-t",
                tag,
                "-f",
                str(dockerfile_dir / dockerfile),
                str(dockerfile_dir),
            ]
        )

    def get_container_status(self, service: str) -> dict[str, Any] | None:
        """Get status of a specific service container.

        Returns a dict with container info, or None if not running.
        """
        result = self.compose_ps()
        if not result.success:
            return None
        # Parse JSON output from docker compose ps
        try:
            containers = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return None

        if isinstance(containers, list):
            for container in containers:
                if container.get("Service") == service:
                    return container
        return None

    def is_service_running(self, service: str) -> bool:
        """Check if a specific service container is running."""
        status = self.get_container_status(service)
        return status is not None and status.get("State") == "running"

    def list_running_services(self) -> list[str]:
        """List all running service names."""
        result = self.compose_ps()
        if not result.success:
            return []

        try:
            containers = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return []

        if isinstance(containers, list):
            return [c.get("Service", "") for c in containers if c.get("State") == "running"]
        return []
