"""Pytest fixtures and configuration for integration tests.

Integration tests boot real AlmaLinux 9 VMs via KVM/libvirt and run
nopanel commands over SSH. They are opt-in via ``-m integration``.

Usage::

    pytest -m integration --tb=short -v
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.integration.cloudinit import generate_cloud_init
from tests.integration.ssh_runner import SSHRunner
from tests.integration.vm_manager import VMManager

logger = logging.getLogger(__name__)

# SSH key pair for VM access (generated once per session)
_SSH_KEY_DIR: Path | None = None
_SSH_PRIVATE_KEY: Path | None = None
_SSH_PUBLIC_KEY: str | None = None


def _generate_ssh_keypair() -> tuple[Path, str]:
    """Generate an ephemeral SSH keypair for VM access."""
    global _SSH_KEY_DIR, _SSH_PRIVATE_KEY, _SSH_PUBLIC_KEY
    if _SSH_PRIVATE_KEY and _SSH_PUBLIC_KEY:
        return _SSH_PRIVATE_KEY, _SSH_PUBLIC_KEY

    _SSH_KEY_DIR = Path(tempfile.mkdtemp(prefix="nopanel-int-ssh-"))
    _SSH_PRIVATE_KEY = _SSH_KEY_DIR / "id_ed25519"
    result = subprocess.run(
        [
            "ssh-keygen", "-t", "ed25519",
            "-f", str(_SSH_PRIVATE_KEY),
            "-N", "",  # no passphrase
            "-C", "nopanel-integration",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {result.stderr}")
    _SSH_PUBLIC_KEY = (_SSH_KEY_DIR / "id_ed25519.pub").read_text().strip()
    return _SSH_PRIVATE_KEY, _SSH_PUBLIC_KEY


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: end-to-end tests requiring KVM VMs (opt-in via -m integration)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests unless -m integration is used."""
    if "integration" not in (config.getoption("-m") or ""):
        skip_integration = pytest.mark.skip(reason="Use -m integration to run integration tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ssh_keypair() -> tuple[Path, str]:
    """Generate (or return cached) SSH keypair for VM access."""
    return _generate_ssh_keypair()


@pytest.fixture(scope="session")
def vm_manager(ssh_keypair: tuple[Path, str]) -> VMManager:
    """Create a VMManager instance (session-scoped)."""
    manager = VMManager(name="nopanel-test")
    yield manager
    manager.cleanup()
    # Clean up SSH keys
    global _SSH_KEY_DIR
    if _SSH_KEY_DIR and _SSH_KEY_DIR.exists():
        import shutil
        shutil.rmtree(_SSH_KEY_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def almalinux_vm(vm_manager: VMManager, ssh_keypair: tuple[Path, str]) -> tuple[VMManager, SSHRunner]:
    """Boot an AlmaLinux 9 VM with Docker pre-installed.

    Returns (vm_manager, ssh_runner) for use throughout the session.
    The VM is booted once, and a snapshot is taken after Docker is ready.
    """
    private_key, public_key = ssh_keypair

    # Generate cloud-init seed
    seed_dir = vm_manager.work_dir
    seed_iso = generate_cloud_init(
        hostname="nopanel-test",
        ssh_public_key=public_key,
        output_dir=seed_dir,
    )

    # Boot the VM
    ip = vm_manager.start(seed_iso)

    # Create SSH runner
    runner = SSHRunner(
        host=ip,
        username="root",
        key_filename=str(private_key),
    )

    # Wait for SSH to be available
    runner.connect(retries=60, delay=5)

    # Fix stale dnf repos (base image may point to old version-specific mirrors)
    logger.info("Fixing dnf repos on VM...")
    runner.run("dnf clean all 2>&1 | tail -1", timeout=60)
    runner.run("rm -f /etc/yum.repos.d/almalinux*.repo", timeout=10)
    runner.run(
        "cat > /etc/yum.repos.d/almalinux.repo << 'REPO'\n"
        "[baseos]\nname=AlmaLinux 9 - BaseOS\nbaseurl=https://repo.almalinux.org/almalinux/9/BaseOS/$basearch/os/\nenabled=1\ngpgcheck=1\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-AlmaLinux-9\n\n"
        "[appstream]\nname=AlmaLinux 9 - AppStream\nbaseurl=https://repo.almalinux.org/almalinux/9/AppStream/$basearch/os/\nenabled=1\ngpgcheck=1\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-AlmaLinux-9\nREPO",
        timeout=10,
    )
    runner.run("dnf makecache 2>&1 | tail -3", timeout=120)

    # Install Docker via SSH
    logger.info("Installing Docker on VM via SSH...")
    docker_install_cmds = [
        "dnf install -y dnf-plugins-core 2>&1 | tail -1",
        "dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>&1 | tail -1",
        "dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>&1 | tail -3",
        "systemctl enable --now docker",
        "firewall-cmd --permanent --zone=trusted --add-interface=docker0 2>&1 || true",
        "firewall-cmd --reload 2>&1 || true",
    ]
    for cmd in docker_install_cmds:
        result = runner.run(cmd, timeout=300)
        logger.info("  [%s] exit=%d", cmd.split()[0], result.exit_code)
        if result.exit_code != 0 and "docker-ce" not in cmd:
            logger.warning("  stderr: %s", result.stderr.strip()[:200])

    # Verify Docker is ready
    logger.info("Verifying Docker is ready on VM...")
    for attempt in range(30):
        result = runner.run("docker info 2>/dev/null && echo READY || echo WAITING")
        if "READY" in result.stdout:
            logger.info("Docker is ready on VM")
            break
        import time
        time.sleep(5)
    else:
        debug = runner.run("systemctl status docker 2>&1 | head -10; docker --version 2>&1")
        raise RuntimeError(f"Docker did not become ready on VM within 150s\nDebug:\n{debug.stdout}")

    # Install Python 3.11 and pip (AlmaLinux 9 defaults to 3.9, nopanel needs >=3.11)
    logger.info("Installing Python 3.11 on VM...")
    runner.run("dnf install -y python3.11 python3.11-pip 2>&1 | tail -3", timeout=120)

    # Install nopanel on the VM
    _install_nopanel_on_vm(runner)

    # Create snapshot for fast revert
    try:
        vm_manager.create_snapshot("clean")
        logger.info("Snapshot 'clean' created")
    except Exception as e:
        logger.warning("Failed to create snapshot: %s", e)

    yield vm_manager, runner

    runner.disconnect()


def _install_nopanel_on_vm(runner: SSHRunner) -> None:
    """Install nopanel on the VM from the local source tree."""
    logger.info("Installing nopanel on VM...")

    # Create a tarball of the nopanel source (excluding .git, tests, docs)
    import tarfile

    source_dir = Path(__file__).parent.parent.parent
    tarball_path = Path("/tmp/nopanel-src.tar.gz")

    exclude_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", ".ruff_cache"}
    with tarfile.open(tarball_path, "w:gz") as tar:
        for item in source_dir.iterdir():
            if item.name.startswith(".") and item.name not in {".python-version"}:
                continue
            if item.name in exclude_dirs:
                continue
            if item.is_dir():
                def filter_fn(tinfo):
                    parts = Path(tinfo.name).parts
                    if any(p in exclude_dirs for p in parts):
                        return None
                    if "__pycache__" in tinfo.name:
                        return None
                    return tinfo
                tar.add(item, arcname=item.name, filter=filter_fn)
            else:
                tar.add(item, arcname=item.name)

    # Upload tarball
    runner.put_file(str(tarball_path), "/tmp/nopanel-src.tar.gz")
    tarball_path.unlink(missing_ok=True)

    # Extract and install
    runner.run_check("rm -rf /opt/nopanel-src && mkdir -p /opt/nopanel-src && tar xzf /tmp/nopanel-src.tar.gz -C /opt/nopanel-src")
    pip_result = runner.run("cd /opt/nopanel-src && pip3.11 install -e '.[dev]' 2>&1", timeout=300)
    if pip_result.exit_code != 0:
        raise RuntimeError(f"pip install failed (exit {pip_result.exit_code}):\n{pip_result.stdout}\n{pip_result.stderr}")
    logger.info("pip install output: %s", pip_result.stdout[-500:])
    # Verify nopanel is actually installed
    result = runner.run("which nopanel 2>/dev/null && nopanel --version 2>&1")
    if result.exit_code != 0:
        raise RuntimeError(f"nopanel installation failed: {result.stdout}\n{result.stderr}")

    logger.info("nopanel installed on VM")


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vm_ssh(almalinux_vm: tuple[VMManager, SSHRunner]) -> SSHRunner:
    """Provide SSH access to the VM for a single test.

    Reverts to the 'clean' snapshot before each test for isolation.
    """
    manager, runner = almalinux_vm

    # Revert to clean snapshot for test isolation
    try:
        manager.revert_snapshot("clean")
        # Update runner's host IP (may change after revert)
        runner.host = manager.ip
        # Reconnect SSH after revert
        runner.disconnect()
        runner.connect(retries=30, delay=3)
    except Exception as e:
        logger.warning("Snapshot revert failed, continuing: %s", e)

    yield runner


@pytest.fixture
def nopanel_on_vm(vm_ssh: SSHRunner) -> SSHRunner:
    """Ensure nopanel is installed and return SSH runner.

    nopanel is installed during the session-scoped VM boot, but after
    snapshot revert we may need to re-install if the snapshot was taken
    before installation.
    """
    # Check if nopanel is available
    result = vm_ssh.run("which nopanel 2>/dev/null && echo FOUND || echo MISSING")
    if "MISSING" in result.stdout:
        _install_nopanel_on_vm(vm_ssh)
    return vm_ssh
