"""VM lifecycle management via libvirt/virt-install.

Manages AlmaLinux 9 cloud-image VMs for integration testing:
- Downloads and caches qcow2 base images
- Creates COW overlays per test run
- Boots VMs via virt-install
- Provides IP address for SSH access
- Destroys VMs and cleans up overlays
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# AlmaLinux 9 cloud image URL (x86_64, qcow2)
ALMALINUX9_URL = (
    "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/"
    "AlmaLinux-9-GenericCloud-latest.x86_64.qcow2"
)

# Default VM resources — kept minimal for dev notebooks (see A/B/E in DRIFT/AGENTS)
DEFAULT_VCPUS = 2
DEFAULT_MEMORY_MB = 3072
DEFAULT_DISK_GB = 16

# Where to cache base images
IMAGE_CACHE_DIR = Path.home() / ".cache" / "nopanel-integration" / "images"
# Work dir holds the qcow2 overlay + base image copy. Must NOT be on tmpfs
# (RAM-backed) — the overlay grows as the VM writes and would consume host RAM.
# Override with NOPANEL_INT_WORK_DIR env var if needed.
WORK_DIR = Path(
    os.environ.get(
        "NOPANEL_INT_WORK_DIR",
        str(Path.home() / ".cache" / "nopanel-integration" / "work"),
    )
)


class VMManager:
    """Manages a single VM lifecycle for integration testing."""

    def __init__(
        self,
        name: str = "nopanel-test",
        base_image_url: str = ALMALINUX9_URL,
        vcpus: int = DEFAULT_VCPUS,
        memory_mb: int = DEFAULT_MEMORY_MB,
        disk_gb: int = DEFAULT_DISK_GB,
    ) -> None:
        self.name = name
        self.base_image_url = base_image_url
        self.vcpus = vcpus
        self.memory_mb = memory_mb
        self.disk_gb = disk_gb

        self.work_dir = WORK_DIR / name
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.base_image_path = IMAGE_CACHE_DIR / Path(base_image_url).name
        self.overlay_path = self.work_dir / f"{name}-overlay.qcow2"
        self.seed_iso_path = self.work_dir / "seed.iso"

        self._ip: str | None = None

    # -- Base image management --------------------------------------------

    def ensure_base_image(self) -> Path:
        """Download the base image if not cached. Returns path to cached image."""
        if self.base_image_path.exists():
            logger.info("Base image cached: %s", self.base_image_path)
            return self.base_image_path

        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading base image: %s", self.base_image_url)
        result = subprocess.run(
            ["curl", "-fL", "-o", str(self.base_image_path), self.base_image_url],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to download base image: {result.stderr}")
        logger.info("Downloaded base image: %s (%d bytes)",
                     self.base_image_path, self.base_image_path.stat().st_size)
        return self.base_image_path

    # -- Overlay management -----------------------------------------------

    def _ensure_qemu_access(self, path: Path) -> None:
        """Grant the qemu user traverse+read access to a path.

        WORK_DIR lives under ~/.cache (drwx------), so the qemu process
        (uid 107) can't traverse the directory chain to reach qcow2/iso
        files. We use ACLs to grant qemu search (x) on each parent dir
        and read (r) on files — narrower than chmod o+x which would open
        the path to all users.
        """
        import stat as stat_mod

        # Walk the ENTIRE chain from the target up to /, collecting every
        # directory that lacks o+x. We can't break early at the first dir
        # with o+x because a parent further up may still be closed (e.g.
        # work_dir is 0o755 but ~/.cache is 0o700).
        dirs_to_fix: list[Path] = []
        current = path if path.is_dir() else path.parent
        while current != current.parent:
            try:
                st = current.stat()
                if not (st.st_mode & stat_mod.S_IXOTH):
                    dirs_to_fix.append(current)
            except PermissionError:
                dirs_to_fix.append(current)
            current = current.parent

        # Apply ACLs root-to-leaf so traversal works at every level.
        # setfacl on dirs we don't own (e.g. /, /home) will fail silently —
        # those already have o+x so they don't need fixing.
        for d in reversed(dirs_to_fix):
            subprocess.run(
                ["setfacl", "-m", "u:qemu:x", str(d)],
                capture_output=True, text=True,
            )

        # Grant read access on the file itself (if it's a file)
        if path.is_file():
            subprocess.run(
                ["setfacl", "-m", "u:qemu:r", str(path)],
                capture_output=True, text=True,
            )

    def create_overlay(self) -> Path:
        """Create a COW overlay on top of the cached base image.

        The base image is copied into the work directory (which is in a
        libvirt storage pool) so that qemu can access it.
        """
        base = self.ensure_base_image()

        # Copy base image into work_dir so qemu (uid 107) can access it
        local_base = self.work_dir / "base.qcow2"
        if not local_base.exists() or local_base.stat().st_size != base.stat().st_size:
            logger.info("Copying base image to work dir: %s", local_base)
            shutil.copy2(base, local_base)
            os.chmod(local_base, 0o644)

        if self.overlay_path.exists():
            self.overlay_path.unlink()
        result = subprocess.run(
            [
                "qemu-img", "create", "-f", "qcow2",
                "-b", str(local_base),
                "-F", "qcow2",
                str(self.overlay_path),
                f"{self.disk_gb}G",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create overlay: {result.stderr}")
        # Ensure libvirt (qemu user) can access the files
        os.chmod(self.overlay_path, 0o644)
        os.chmod(self.work_dir, 0o755)
        # Grant qemu traverse access on the directory chain (WORK_DIR may
        # be under ~/.cache which is drwx------)
        self._ensure_qemu_access(self.overlay_path)
        self._ensure_qemu_access(local_base)
        logger.info("Created overlay: %s", self.overlay_path)
        return self.overlay_path

    def _ensure_storage_pool(self) -> None:
        """Ensure a libvirt dir storage pool exists for the work directory.

        If a pool with the same name exists but points at a stale path
        (e.g. WORK_DIR moved), it is destroyed and redefined.
        """
        pool_name = self.name
        # Check if pool already exists
        result = subprocess.run(
            ["sudo", "virsh", "pool-info", pool_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            # Pool exists — verify its target path matches the current work_dir
            xml_result = subprocess.run(
                ["sudo", "virsh", "pool-dumpxml", pool_name],
                capture_output=True, text=True,
            )
            current_path = self.work_dir.resolve()
            if xml_result.returncode == 0 and str(current_path) in xml_result.stdout:
                # Path matches — just start and refresh
                subprocess.run(["sudo", "virsh", "pool-start", pool_name],
                               capture_output=True, text=True)
                subprocess.run(["sudo", "virsh", "pool-refresh", pool_name],
                               capture_output=True, text=True)
                return
            # Path mismatch — destroy and redefine below
            logger.info(
                "Storage pool '%s' points at stale path, redefining to %s",
                pool_name, current_path,
            )
            self._destroy_storage_pool()

        # Create the pool
        pool_xml = (
            f"<pool type='dir'>\n"
            f"  <name>{pool_name}</name>\n"
            f"  <target>\n"
            f"    <path>{self.work_dir}</path>\n"
            f"  </target>\n"
            f"</pool>\n"
        )
        result = subprocess.run(
            ["sudo", "virsh", "pool-define", "/dev/stdin"],
            input=pool_xml, capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("Failed to define storage pool: %s", result.stderr)
            return
        subprocess.run(["sudo", "virsh", "pool-start", pool_name],
                       capture_output=True, text=True)
        subprocess.run(["sudo", "virsh", "pool-autostart", pool_name],
                       capture_output=True, text=True)
        logger.info("Created storage pool: %s", pool_name)

    def _destroy_storage_pool(self) -> None:
        """Destroy and undefine the storage pool."""
        pool_name = self.name
        subprocess.run(["sudo", "virsh", "pool-destroy", pool_name],
                       capture_output=True, text=True)
        subprocess.run(["sudo", "virsh", "pool-undefine", pool_name],
                       capture_output=True, text=True)

    def _ensure_nat_rules(self) -> None:
        """Ensure iptables NAT and FORWARD rules exist for 192.168.122.0/24.

        On hosts where firewalld manages the firewall, libvirt's own NAT rules
        may not be applied. This adds them explicitly.
        """
        # Check if MASQUERADE rule already exists
        result = subprocess.run(
            ["sudo", "iptables", "-t", "nat", "-C", "POSTROUTING",
             "-s", "192.168.122.0/24", "-j", "MASQUERADE"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
                 "-s", "192.168.122.0/24", "-j", "MASQUERADE"],
                capture_output=True, text=True,
            )
            logger.info("Added MASQUERADE rule for 192.168.122.0/24")

        # Allow forwarding from VM network
        for rule in [
            ["-s", "192.168.122.0/24", "-j", "ACCEPT"],
            ["-d", "192.168.122.0/24", "-j", "ACCEPT"],
        ]:
            check = subprocess.run(
                ["sudo", "iptables", "-C", "FORWARD"] + rule,
                capture_output=True, text=True,
            )
            if check.returncode != 0:
                subprocess.run(
                    ["sudo", "iptables", "-I", "FORWARD"] + rule,
                    capture_output=True, text=True,
                )

    # -- VM lifecycle -----------------------------------------------------

    def start(self, seed_iso: Path) -> str:
        """Boot the VM with virt-install. Returns the VM IP address.

        Args:
            seed_iso: Path to cloud-init seed ISO.
        """
        self.seed_iso_path = seed_iso

        # Ensure NAT rules are in place for VM network
        self._ensure_nat_rules()

        # Destroy any existing VM with the same name (VM only, not pool)
        self._destroy_vm_only()

        self.create_overlay()
        self._ensure_storage_pool()
        # Ensure qemu can read the seed ISO (may be under ~/.cache/...)
        self._ensure_qemu_access(seed_iso)

        pool_name = self.name
        cmd = [
            "sudo", "virt-install",
            "--name", self.name,
            "--memory", str(self.memory_mb),
            "--vcpus", str(self.vcpus),
            "--disk", f"vol={pool_name}/{self.overlay_path.name},format=qcow2,bus=virtio",
            "--disk", f"path={seed_iso},device=cdrom",
            "--import",
            "--os-variant", "almalinux9",
            "--network", "network=default",
            "--graphics", "none",
            "--noautoconsole",
            "--console", "pty",
        ]
        logger.info("Starting VM: %s", self.name)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"virt-install failed: {result.stderr}")

        # Wait for VM to get an IP via DHCP
        self._ip = self._wait_for_ip(timeout=180)
        logger.info("VM %s IP: %s", self.name, self._ip)
        return self._ip

    def _wait_for_ip(self, timeout: int = 180) -> str:
        """Poll for the VM's IP address.

        Uses domifaddr first, then falls back to matching the VM's MAC
        address against DHCP leases (not hostname, which can match stale entries).
        """
        # Get the VM's MAC address
        mac = None
        deadline = time.time() + 10
        while time.time() < deadline:
            result = subprocess.run(
                ["sudo", "virsh", "domiflist", self.name],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    for part in parts:
                        if ":" in part and len(part) == 17 and part.count(":") == 5:
                            mac = part
                            break
                    if mac:
                        break
            if mac:
                break
            time.sleep(2)

        if not mac:
            raise RuntimeError(f"Could not find MAC address for VM {self.name}")

        logger.info("VM %s MAC: %s", self.name, mac)

        deadline = time.time() + timeout
        while time.time() < deadline:
            # Use domifaddr — most reliable way to get a running VM's IP
            result = subprocess.run(
                ["sudo", "virsh", "domifaddr", self.name],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and "ipv4" in parts[2].lower():
                        addr = parts[3]
                        if "/" in addr:
                            addr = addr.split("/")[0]
                        if addr.count(".") == 3:
                            return addr

            # Fallback: match MAC address against DHCP leases
            result = subprocess.run(
                ["sudo", "virsh", "net-dhcp-leases", "default"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if mac in line:
                        parts = line.split()
                        for part in parts:
                            if "/" in part and part.count(".") == 3:
                                return part.split("/")[0]
            time.sleep(5)
        raise TimeoutError(f"VM {self.name} (MAC {mac}) did not get an IP within {timeout}s")

    @property
    def ip(self) -> str:
        if self._ip is None:
            raise RuntimeError("VM not started — call start() first")
        return self._ip

    def _destroy_vm_only(self) -> None:
        """Destroy and undefine the VM only (no pool/overlay cleanup)."""
        subprocess.run(
            ["sudo", "virsh", "destroy", self.name],
            capture_output=True, text=True, timeout=30,
        )
        # Delete all snapshots before undefine (undefine fails if snapshots exist)
        snap_result = subprocess.run(
            ["sudo", "virsh", "snapshot-list", self.name, "--name"],
            capture_output=True, text=True, timeout=10,
        )
        if snap_result.returncode == 0:
            for snap_name in snap_result.stdout.strip().splitlines():
                snap_name = snap_name.strip()
                if snap_name:
                    subprocess.run(
                        ["sudo", "virsh", "snapshot-delete", self.name, snap_name],
                        capture_output=True, text=True, timeout=10,
                    )
        subprocess.run(
            ["sudo", "virsh", "undefine", self.name],
            capture_output=True, text=True, timeout=30,
        )

    def destroy(self) -> None:
        """Destroy and undefine the VM, remove overlay and storage pool."""
        self._destroy_vm_only()
        if self.overlay_path.exists():
            self.overlay_path.unlink()
        self._destroy_storage_pool()
        logger.info("VM %s destroyed", self.name)

    def is_running(self) -> bool:
        result = subprocess.run(
            ["sudo", "virsh", "domstate", self.name],
            capture_output=True, text=True,
        )
        return "running" in result.stdout

    def shutdown(self) -> None:
        """Gracefully shutdown the VM."""
        subprocess.run(
            ["sudo", "virsh", "shutdown", self.name],
            capture_output=True, text=True, timeout=30,
        )
        # Wait for shutdown
        for _ in range(30):
            if not self.is_running():
                break
            time.sleep(2)

    # -- Snapshot management ----------------------------------------------

    def create_snapshot(self, name: str = "clean") -> None:
        """Create a libvirt snapshot."""
        subprocess.run(
            ["sudo", "virsh", "snapshot-create-as", self.name, name],
            capture_output=True, text=True, timeout=30,
        )
        logger.info("Created snapshot '%s' for VM %s", name, self.name)

    def revert_snapshot(self, name: str = "clean") -> None:
        """Revert to a libvirt snapshot."""
        subprocess.run(
            ["sudo", "virsh", "snapshot-revert", self.name, name, "--running"],
            capture_output=True, text=True, timeout=120,
        )
        logger.info("Reverted to snapshot '%s' for VM %s", name, self.name)
        # Re-detect IP after revert. The VM usually keeps its DHCP lease, so
        # check the cached IP first via domifaddr before falling back to a
        # short poll (was 120s — far too long for the common case).
        if self._ip:
            result = subprocess.run(
                ["sudo", "virsh", "domifaddr", self.name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and self._ip in result.stdout:
                logger.debug("VM %s kept cached IP %s after revert", self.name, self._ip)
                return
        self._ip = self._wait_for_ip(timeout=30)

    def delete_snapshot(self, name: str = "clean") -> None:
        subprocess.run(
            ["sudo", "virsh", "snapshot-delete", self.name, name],
            capture_output=True, text=True, timeout=30,
        )

    # -- Cleanup ----------------------------------------------------------

    def cleanup(self) -> None:
        """Full cleanup: destroy VM, remove overlay, remove work directory."""
        self.destroy()
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)
