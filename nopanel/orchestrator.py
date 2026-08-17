"""pyInfra inventory builder — creates inventory from nopanel config.

Reads nopanel's ``nopanel.yml`` to determine the target host and
SSH credentials, then builds a pyInfra ``Inventory`` object.

Usage::

    from nopanel.orchestrator import build_inventory
    inventory, config = build_inventory(config_dir=Path("/etc/nopanel"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nopanel.config import DEFAULT_CONFIG_DIR, load_config

logger = logging.getLogger(__name__)


def build_inventory(
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[Any, Any]:
    """Build a pyInfra Inventory + Config from nopanel configuration.

    Reads ``nopanel.yml`` for SSH target and sudo settings.
    Falls back to ``@local`` if no SSH target is configured.

    Returns:
        (inventory, config) — pyInfra Inventory and Config objects.
    """
    try:
        from pyinfra.api import Config, Inventory
    except ImportError:
        raise ImportError(
            "pyInfra is required for the orchestrator. "
            "Install with: pip install nopanel[pyinfra]"
        ) from None

    config_data = load_config(config_dir)
    nopanel_cfg = config_data.nopanel

    # Determine target: use SSH host from config, or @local
    ssh_host = getattr(nopanel_cfg, "ssh_host", None)
    ssh_user = getattr(nopanel_cfg, "ssh_user", None)
    ssh_port = getattr(nopanel_cfg, "ssh_port", 22)
    sudo = getattr(nopanel_cfg, "sudo", True)

    if ssh_host:
        target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
        target = f"{target}:{ssh_port}" if ssh_port != 22 else target
        logger.info("pyInfra inventory: SSH target %s", target)
    else:
        target = "@local"
        logger.info("pyInfra inventory: @local (no SSH host configured)")

    inventory = Inventory(([target], {}))
    config = Config(SUDO=sudo)
    return inventory, config
