"""pyInfra inventory builder — creates inventory from nopanel config.

Uses :func:`~nopanel.host_ops.detect_transport` to determine the
pyInfra target (``@local`` or ``@nsenter``), then builds a pyInfra
``Inventory`` + ``Config`` object.

Usage::

    from nopanel.orchestrator import build_inventory
    inventory, config = build_inventory(config_dir=Path("/etc/nopanel"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nopanel.config import DEFAULT_CONFIG_DIR, load_config
from nopanel.host_ops import detect_transport

logger = logging.getLogger(__name__)


def build_inventory(
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[Any, Any]:
    """Build a pyInfra Inventory + Config from nopanel configuration.

    Uses auto-detected transport to determine the pyInfra target:
    - ``NsenterTransport`` → ``@nsenter`` (privileged container)
    - ``LocalTransport`` → ``@local`` (nopanel on host)
    - ``None`` → raises RuntimeError (no transport available)

    Returns:
        (inventory, config) — pyInfra Inventory and Config objects.
    """
    try:
        from pyinfra.api import Config, Inventory
    except ImportError:
        raise ImportError(
            "pyInfra is required for the orchestrator. "
            "Install with: pip install pyinfra>=3.10"
        ) from None

    config_data = load_config(config_dir)
    nopanel_cfg = config_data.nopanel
    sudo = getattr(nopanel_cfg, "sudo", True)

    transport = detect_transport()
    if transport is None:
        raise RuntimeError(
            "No transport detected — cannot build pyInfra inventory. "
            "Ensure nsenter is available or nopanel runs on the host."
        )

    if transport.name == "nsenter":
        # Register the @nsenter connector
        from nopanel.pyinfra_backend import _register_nsenter_connector

        _register_nsenter_connector()
        target = "@nsenter"
    else:
        target = "@local"

    logger.info("pyInfra inventory: target %s (transport=%s)", target, transport.name)

    inventory = Inventory(([target], {}))
    config = Config(SUDO=sudo)
    return inventory, config
