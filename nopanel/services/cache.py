"""Valkey cache service — simplest service, no config generation needed."""

from __future__ import annotations

from typing import Any

from nopanel.models import FullConfig


class CacheService:
    """Valkey cache container service manager."""

    def __init__(self, docker_manager: Any = None) -> None:
        self._docker = docker_manager

    @property
    def name(self) -> str:
        return "valkey"

    def generate_config(self, config: FullConfig) -> dict[str, str]:
        """Valkey uses defaults — no config files to generate."""
        return {}

    def start(self) -> Any:
        if self._docker:
            return self._docker.compose_up(["valkey"])
        return None

    def stop(self) -> Any:
        if self._docker:
            return self._docker.compose_stop(["valkey"])
        return None

    def restart(self) -> Any:
        if self._docker:
            return self._docker.compose_restart(["valkey"])
        return None

    def status(self) -> dict[str, Any]:
        if self._docker:
            return self._docker.get_container_status("valkey") or {}
        return {}
