"""State management — committed state snapshots and config diffing.

The commit workflow relies on comparing desired state (YAML configs)
against committed state (snapshots in .committed/). This module provides
pure functions for loading/saving committed state and computing diffs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nopanel.config import (
    DEFAULT_CONFIG_DIR,
    load_config,
    save_config,
)
from nopanel.models import FullConfig

COMMITTED_DIR = ".committed"


# ---------------------------------------------------------------------------
# Committed state I/O
# ---------------------------------------------------------------------------


def get_committed_dir(base: Path | None = None) -> Path:
    """Return the path to the .committed/ directory."""
    base = base or DEFAULT_CONFIG_DIR
    return base / COMMITTED_DIR


def load_committed(base: Path | None = None) -> FullConfig:
    """Load committed state from .committed/ directory.

    If no committed state exists, returns an empty config (everything is "new").
    """
    base = base or DEFAULT_CONFIG_DIR
    committed_dir = get_committed_dir(base)
    if not committed_dir.exists():
        return FullConfig()
    return load_config(committed_dir)


def save_committed(config: FullConfig, base: Path | None = None) -> None:
    """Save current config as committed state snapshot."""
    base = base or DEFAULT_CONFIG_DIR
    committed_dir = get_committed_dir(base)
    committed_dir.mkdir(parents=True, exist_ok=True)
    save_config(config, committed_dir)


# ---------------------------------------------------------------------------
# Diff data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityChange:
    """A change to a single entity (user, domain, database)."""

    name: str
    old: dict[str, Any] | None  # None for added entities
    new: dict[str, Any] | None  # None for deleted entities


@dataclass(frozen=True)
class SectionDiff:
    """Diff for a config section (users, domains, databases, etc.)."""

    added: list[EntityChange] = field(default_factory=list)
    modified: list[EntityChange] = field(default_factory=list)
    deleted: list[EntityChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)


@dataclass(frozen=True)
class ConfigDiff:
    """Full diff between desired and committed config."""

    users: SectionDiff = field(default_factory=SectionDiff)
    domains: SectionDiff = field(default_factory=SectionDiff)
    databases: SectionDiff = field(default_factory=SectionDiff)
    services: SectionDiff = field(default_factory=SectionDiff)
    settings_changed: bool = False
    settings_old: dict[str, Any] = field(default_factory=dict)
    settings_new: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return (
            self.users.is_empty
            and self.domains.is_empty
            and self.databases.is_empty
            and self.services.is_empty
            and not self.settings_changed
        )

    @property
    def total_changes(self) -> int:
        return (
            self.users.total_changes
            + self.domains.total_changes
            + self.databases.total_changes
            + self.services.total_changes
            + (1 if self.settings_changed else 0)
        )


# ---------------------------------------------------------------------------
# Diff computation (pure functions)
# ---------------------------------------------------------------------------


def _diff_dict_section(
    desired: dict[str, Any],
    committed: dict[str, Any],
) -> SectionDiff:
    """Diff a dict-based config section (users, domains, databases).

    Each key maps to a dict of properties. Detects added, modified, deleted.
    """
    added: list[EntityChange] = []
    modified: list[EntityChange] = []
    deleted: list[EntityChange] = []

    desired_keys = set(desired.keys())
    committed_keys = set(committed.keys())

    # Added: in desired but not in committed
    for key in sorted(desired_keys - committed_keys):
        added.append(EntityChange(name=key, old=None, new=desired[key]))

    # Deleted: in committed but not in desired
    for key in sorted(committed_keys - desired_keys):
        deleted.append(EntityChange(name=key, old=committed[key], new=None))

    # Modified: in both but different
    for key in sorted(desired_keys & committed_keys):
        if desired[key] != committed[key]:
            modified.append(EntityChange(name=key, old=committed[key], new=desired[key]))

    return SectionDiff(added=added, modified=modified, deleted=deleted)


def _diff_services(
    desired_services: dict[str, Any],
    committed_services: dict[str, Any],
) -> SectionDiff:
    """Diff services config. Services is a flat dict of service configs.

    The 'php' key is a nested dict of per-version configs. We flatten it
    into individual 'php-X.Y' keys so per-version changes are detected
    independently rather than as a single 'php' modification.
    """

    def _flatten(services: dict[str, Any]) -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for key, val in services.items():
            if key == "php" and isinstance(val, dict):
                for ver, svc in val.items():
                    flat[f"php-{ver}"] = svc
            else:
                flat[key] = val
        return flat

    return _diff_dict_section(_flatten(desired_services), _flatten(committed_services))


def diff_configs(desired: FullConfig, committed: FullConfig) -> ConfigDiff:
    """Compute the diff between desired and committed config.

    Pure function — no side effects.
    """
    desired_dump = desired.model_dump(mode="json")
    committed_dump = committed.model_dump(mode="json")

    # Diff users
    users_diff = _diff_dict_section(
        desired_dump.get("users", {}).get("users", {}),
        committed_dump.get("users", {}).get("users", {}),
    )

    # Diff domains
    domains_diff = _diff_dict_section(
        desired_dump.get("domains", {}).get("domains", {}),
        committed_dump.get("domains", {}).get("domains", {}),
    )

    # Diff databases
    databases_diff = _diff_dict_section(
        desired_dump.get("databases", {}).get("databases", {}),
        committed_dump.get("databases", {}).get("databases", {}),
    )

    # Diff services (flat dict)
    services_diff = _diff_services(
        desired_dump.get("services", {}),
        committed_dump.get("services", {}),
    )

    # Diff settings (entire nopanel section except version)
    desired_nopanel = desired_dump.get("nopanel", {})
    committed_nopanel = committed_dump.get("nopanel", {})
    desired_settings = desired_nopanel.get("settings", {})
    committed_settings = committed_nopanel.get("settings", {})
    desired_mariadb = desired_nopanel.get("mariadb", {})
    committed_mariadb = committed_nopanel.get("mariadb", {})
    desired_php = desired_nopanel.get("php", {})
    committed_php = committed_nopanel.get("php", {})

    settings_changed = (
        desired_settings != committed_settings
        or desired_mariadb != committed_mariadb
        or desired_php != committed_php
    )

    # Merge all changed nopanel settings for reporting
    if settings_changed:
        all_old = {**committed_settings, **committed_mariadb, **committed_php}
        all_new = {**desired_settings, **desired_mariadb, **desired_php}
    else:
        all_old = {}
        all_new = {}

    return ConfigDiff(
        users=users_diff,
        domains=domains_diff,
        databases=databases_diff,
        services=services_diff,
        settings_changed=settings_changed,
        settings_old=all_old,
        settings_new=all_new,
    )


# ---------------------------------------------------------------------------
# Diff formatting (for CLI output)
# ---------------------------------------------------------------------------


def format_diff(diff: ConfigDiff) -> str:
    """Format a ConfigDiff as human-readable text for CLI output."""
    lines: list[str] = []

    if diff.is_empty:
        return "No changes to commit."

    if diff.settings_changed:
        lines.append("Settings:")
        for key in sorted(set(list(diff.settings_old.keys()) + list(diff.settings_new.keys()))):
            old_val = diff.settings_old.get(key, "(none)")
            new_val = diff.settings_new.get(key, "(none)")
            if old_val != new_val:
                lines.append(f"  ~ {key}: {old_val} → {new_val}")

    for section_name, section_diff in [
        ("Users", diff.users),
        ("Domains", diff.domains),
        ("Databases", diff.databases),
        ("Services", diff.services),
    ]:
        if section_diff.is_empty:
            continue
        lines.append(f"{section_name}:")
        for change in section_diff.added:
            lines.append(f"  + {change.name} (new)")
        for change in section_diff.modified:
            lines.append(f"  ~ {change.name} (modified)")
        for change in section_diff.deleted:
            lines.append(f"  - {change.name} (deleted)")

    return "\n".join(lines)
