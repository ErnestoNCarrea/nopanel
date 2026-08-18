"""Cloud-init seed ISO generation for VM provisioning.

Generates cloud-init user-data and meta-data, then creates a seed ISO
using ``mkisofs`` (no cloud-localds required).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_cloud_init(
    hostname: str,
    ssh_public_key: str,
    output_dir: Path,
    packages: list[str] | None = None,
    runcmd: list[str] | None = None,
    write_files: list[dict] | None = None,
) -> Path:
    """Generate a cloud-init seed ISO.

    Args:
        hostname: VM hostname.
        ssh_public_key: SSH public key to inject for root login.
        output_dir: Where to write the seed ISO.
        packages: Additional packages to install via dnf.
        runcmd: Additional commands to run after boot.
        write_files: Files to write (cloud-init write_files format).

    Returns:
        Path to the generated seed.iso.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- user-data --------------------------------------------------------
    user_data_lines = [
        "#cloud-config",
        f"hostname: {hostname}",
        "disable_root: false",
        "ssh_pwauth: true",
        "chpasswd:",
        "  list: |",
        "    root:nopanel123",
        "  expire: false",
        "ssh_authorized_keys:",
        f"  - {ssh_public_key}",
    ]

    if packages:
        user_data_lines.append("packages:")
        for pkg in packages:
            user_data_lines.append(f"  - {pkg}")

    if write_files:
        user_data_lines.append("write_files:")
        for wf in write_files:
            user_data_lines.append(f"  - path: {wf['path']}")
            user_data_lines.append(f"    content: |")
            for line in wf["content"].splitlines():
                user_data_lines.append(f"      {line}")
            if wf.get("permissions"):
                user_data_lines.append(f"    permissions: '{wf['permissions']}'")

    # No runcmd — all package installation done via SSH after connection
    # (cloud-init dnf operations fail when base image repos are stale)

    if runcmd:
        for cmd in runcmd:
            user_data_lines.append(f"  - {cmd}")

    user_data = "\n".join(user_data_lines) + "\n"

    # -- meta-data --------------------------------------------------------
    meta_data = (
        f"instance-id: {hostname}\n"
        f"local-hostname: {hostname}\n"
    )

    # -- Write files and create ISO ---------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "user-data").write_text(user_data)
        (tmp / "meta-data").write_text(meta_data)

        seed_iso = output_dir / "seed.iso"
        result = subprocess.run(
            [
                "mkisofs",
                "-output", str(seed_iso),
                "-volid", "cidata",
                "-joliet", "-rock",
                str(tmp / "user-data"),
                str(tmp / "meta-data"),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mkisofs failed: {result.stderr}")

        logger.info("Generated cloud-init seed ISO: %s", seed_iso)
        return seed_iso
