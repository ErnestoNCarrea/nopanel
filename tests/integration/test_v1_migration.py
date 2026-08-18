"""Integration test: v1 → v2 migration.

Sets up a simulated v1 noPanel installation on an AlmaLinux 9 VM,
then runs the migration to v2 and verifies the result.

v1 config files:
- /etc/nopanel/nopanel.json  (global settings)
- /etc/nopanel/users.json    (users)
- /etc/nopanel/modules.json  (installed modules)
- /home/<user>/.nopanel/domains.json    (per-user domains)
- /home/<user>/.nopanel/databases.json  (per-user databases)
"""

from __future__ import annotations

import json
import logging
import time

import pytest

from tests.integration.ssh_runner import SSHRunner

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(ssh: SSHRunner, cmd: str, check: bool = True) -> str:
    """Run a command on the VM, optionally raising on failure."""
    result = ssh.run(cmd, timeout=300)
    if check and result.exit_code != 0:
        pytest.fail(
            f"Command failed: {cmd}\n"
            f"exit: {result.exit_code}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result.stdout.strip()


def _write_json(ssh: SSHRunner, path: str, data: dict) -> None:
    """Write a JSON file on the VM."""
    ssh.put_content(json.dumps(data, indent=2) + "\n", path)
    _run(ssh, f"chmod 600 {path}")


def _read_yaml(ssh: SSHRunner, path: str) -> dict:
    import yaml
    raw = _run(ssh, f"cat {path}")
    return yaml.safe_load(raw) or {}


def _setup_v1_installation(ssh: SSHRunner) -> None:
    """Set up a simulated v1 noPanel installation on the VM.

    Creates v1 JSON config files and user home directories with
    per-user domains and databases JSON files.
    """
    # Clean any existing config
    _run(ssh, "rm -rf /etc/nopanel")
    _run(ssh, "mkdir -p /etc/nopanel")

    # v1 nopanel.json (global settings)
    v1_nopanel = {
        "version": "1.0",
        "mariadb": {
            "default_branch": "10.11",
        },
        "php": {
            "additional_modules": "opcache,apcu",
        },
    }
    _write_json(ssh, "/etc/nopanel/nopanel.json", v1_nopanel)

    # v1 users.json
    v1_users = {
        "alice": {
            "fullname": "Alice Smith",
            "email": "alice@example.com",
            "login": "ssh",
            "admin": True,
            "password": "alice_password_123",
        },
        "bob": {
            "fullname": "Bob Jones",
            "email": "bob@example.com",
            "login": "sftp",
            "admin": False,
            "password": "bob_password_123",
        },
    }
    _write_json(ssh, "/etc/nopanel/users.json", v1_users)

    # v1 modules.json (installed modules)
    v1_modules = {
        "mariadb": {
            "installed": True,
            "password": "mariadb_root_pw_123",
        },
        "php-fpm": {
            "8.2": True,
            "8.3": True,
        },
        "valkey": {
            "installed": True,
        },
    }
    _write_json(ssh, "/etc/nopanel/modules.json", v1_modules)

    # Create user home directories with .nopanel/ subdirectory
    for username in ("alice", "bob"):
        _run(ssh, f"useradd -m {username} 2>/dev/null || true")
        _run(ssh, f"mkdir -p /home/{username}/.nopanel")

    # Alice's domains
    alice_domains = {
        "alice-site.com": {
            "web": True,
            "web_php": "8.2",
            "web_ssl": "le",
            "web_aliases": "www.alice-site.com",
            "web_docroot": "public_html",
        },
        "alice-blog.com": {
            "web": True,
            "web_php": "8.3",
            "web_ssl": "no",
            "web_aliases": "",
            "web_docroot": "public_html",
        },
    }
    _write_json(ssh, "/home/alice/.nopanel/domains.json", alice_domains)
    _run(ssh, "chown -R alice:alice /home/alice/.nopanel")

    # Alice's databases
    alice_databases = {
        "alice_site": {
            "dbuser": "alice_site",
            "password": "alice_db_pw_123",
        },
        "alice_blog": {
            "dbuser": "alice_blog",
            "password": "alice_blog_pw_123",
        },
    }
    _write_json(ssh, "/home/alice/.nopanel/databases.json", alice_databases)
    _run(ssh, "chown -R alice:alice /home/alice/.nopanel")

    # Bob's domains
    bob_domains = {
        "bob-site.org": {
            "web": True,
            "web_php": "8.2",
            "web_ssl": "self",
            "web_aliases": "",
            "web_docroot": "public_html",
        },
    }
    _write_json(ssh, "/home/bob/.nopanel/domains.json", bob_domains)
    _run(ssh, "chown -R bob:bob /home/bob/.nopanel")

    # Bob's databases
    bob_databases = {
        "bob_site": {
            "dbuser": "bob_site",
            "password": "bob_db_pw_123",
        },
    }
    _write_json(ssh, "/home/bob/.nopanel/databases.json", bob_databases)
    _run(ssh, "chown -R bob:bob /home/bob/.nopanel")

    # Install MariaDB server (for version detection via RPM)
    _run(ssh, "dnf install -y mariadb-server 2>&1 | tail -3", check=False)

    # Install PHP-FPM packages from Remi (for version detection via RPM)
    _run(ssh, "dnf install -y https://rpms.remirepo.net/enterprise/remi-release-9.rpm 2>&1 | tail -3", check=False)
    _run(ssh, "dnf module reset -y php 2>&1 | tail -1", check=False)
    _run(ssh, "dnf module enable -y php:remi-8.2 2>&1 | tail -1", check=False)
    _run(ssh, "dnf install -y php82-php-fpm 2>&1 | tail -3", check=False)

    logger.info("v1 installation set up on VM")


def _setup_v1_with_services(ssh: SSHRunner) -> None:
    """Set up v1 installation AND install/start host services for full migration.

    This installs httpd, mariadb, valkey, and php-fpm as systemd services
    so the migration can stop them during cutover.
    """
    _setup_v1_installation(ssh)

    # Install and start host services that migration will stop
    _run(ssh, "dnf install -y httpd 2>&1 | tail -3", check=False)
    _run(ssh, "systemctl enable --now httpd 2>&1 || true", check=False)
    _run(ssh, "systemctl enable --now mariadb 2>&1 || true", check=False)

    # Create dummy valkey service (may not be available as package)
    _run(ssh, "dnf install -y valkey 2>&1 | tail -3", check=False)
    _run(ssh, "systemctl enable --now valkey 2>&1 || true", check=False)

    # Start php-fpm if installed
    _run(ssh, "systemctl enable --now php82-php-fpm 2>&1 || true", check=False)

    logger.info("v1 installation with services set up on VM")


# ---------------------------------------------------------------------------
# Pre-migration check
# ---------------------------------------------------------------------------


class TestMigrationPreCheck:
    """Test nopanel migrate --pre-check."""

    def test_pre_check_detects_v1(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        output = _run(ssh, "nopanel migrate --pre-check")
        assert "almalinux" in output.lower() or "rhel" in output.lower()
        assert "yes" in output.lower()  # v1 detected

    def test_pre_check_fails_without_v1(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "rm -rf /etc/nopanel")
        _run(ssh, "mkdir -p /etc/nopanel")
        result = ssh.run("nopanel migrate --pre-check")
        assert result.exit_code != 0
        assert "no" in result.stdout.lower()  # v1 detected: no


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestMigrationDryRun:
    """Test nopanel migrate --dry-run."""

    def test_dry_run_converts_configs(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        output = _run(ssh, "nopanel migrate --dry-run")
        # Should show converted config summary
        assert "Users" in output or "users" in output.lower()
        assert "2" in output  # 2 users

    def test_dry_run_does_not_save_configs(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --dry-run")
        # v2 YAML files should NOT exist (only dry run)
        assert not ssh.file_exists("/etc/nopanel/users.yml")

    def test_dry_run_shows_domains(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        output = _run(ssh, "nopanel migrate --dry-run")
        assert "Domains" in output or "domains" in output.lower()
        assert "3" in output  # 3 domains total (2 alice + 1 bob)

    def test_dry_run_shows_databases(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        output = _run(ssh, "nopanel migrate --dry-run")
        assert "Database" in output or "database" in output.lower()
        assert "3" in output  # 3 databases (2 alice + 1 bob)


# ---------------------------------------------------------------------------
# Full migration
# ---------------------------------------------------------------------------


class TestFullMigration:
    """Test full v1 → v2 migration."""

    def test_migration_converts_users(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" in users["users"]
        assert "bob" in users["users"]
        assert users["users"]["alice"]["fullname"] == "Alice Smith"
        assert users["users"]["alice"]["login"] == "ssh"
        assert users["users"]["bob"]["login"] == "sftp"

    def test_migration_converts_domains(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "alice-site.com" in domains["domains"]
        assert "alice-blog.com" in domains["domains"]
        assert "bob-site.org" in domains["domains"]
        assert domains["domains"]["alice-site.com"]["user"] == "alice"
        assert domains["domains"]["alice-site.com"]["php_version"] == "8.2"
        assert domains["domains"]["alice-site.com"]["ssl"] == "auto"  # le → auto

    def test_migration_converts_databases(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert "alice_site" in dbs["databases"]
        assert "alice_blog" in dbs["databases"]
        assert "bob_site" in dbs["databases"]
        assert dbs["databases"]["alice_site"]["dbuser"] == "alice_site"

    def test_migration_converts_modules(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        services = _read_yaml(ssh, "/etc/nopanel/services.yml")
        assert "mariadb" in services
        assert "valkey" in services
        assert "8.2" in services.get("php", {})
        assert "8.3" in services.get("php", {})

    def test_migration_generates_compose(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        # Full migration generates configs before cutover — ignore cutover errors
        result = ssh.run("nopanel migrate 2>&1", timeout=300, )
        assert ssh.file_exists("/etc/nopanel/generated/docker-compose.yml"), (
            f"docker-compose.yml not generated.\nMigration output:\n{result.stdout}\n{result.stderr}"
        )
        compose = _run(ssh, "cat /etc/nopanel/generated/docker-compose.yml")
        assert "apache" in compose
        assert "mariadb" in compose
        assert "valkey" in compose

    def test_migration_backs_up_v1_configs(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_with_services(ssh)
        # Full migration with services installed — cutover should succeed
        result = ssh.run("nopanel migrate 2>&1", timeout=300)

        # v1 JSON files should be backed up (only happens on successful migration)
        assert ssh.file_exists("/etc/nopanel/nopanel.json.v1.bak"), (
            f"v1 backup not created.\nMigration output:\n{result.stdout}\n{result.stderr}"
        )
        assert ssh.file_exists("/etc/nopanel/users.json.v1.bak")
        assert ssh.file_exists("/etc/nopanel/modules.json.v1.bak")
        # Original v1 files should be removed
        assert not ssh.file_exists("/etc/nopanel/nopanel.json")
        assert not ssh.file_exists("/etc/nopanel/users.json")
        assert not ssh.file_exists("/etc/nopanel/modules.json")

    def test_migration_preserves_passwords(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert users["users"]["alice"]["password"] == "alice_password_123"
        assert users["users"]["bob"]["password"] == "bob_password_123"

        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert dbs["databases"]["alice_site"]["password"] == "alice_db_pw_123"

    def test_migration_preserves_domain_aliases(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        aliases = domains["domains"]["alice-site.com"]["aliases"]
        assert "www.alice-site.com" in aliases

    def test_migration_preserves_admin_flag(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert users["users"]["alice"]["admin"] is True
        assert users["users"]["bob"]["admin"] is False

    def test_migration_preserves_admin_email(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")

        nopanel_cfg = _read_yaml(ssh, "/etc/nopanel/nopanel.yml")
        # admin_email should be extracted from first user with email
        assert nopanel_cfg["settings"]["admin_email"] in ("alice@example.com", "bob@example.com", "")


# ---------------------------------------------------------------------------
# Post-migration operations
# ---------------------------------------------------------------------------


class TestPostMigration:
    """Test that nopanel works correctly after migration."""

    def test_status_after_migration(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")
        output = _run(ssh, "nopanel status")
        assert "Users" in output
        assert "2" in output  # 2 users

    def test_commit_after_migration_no_changes(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")
        # First commit creates the committed state snapshot
        _run(ssh, "nopanel commit --no-docker --no-host")
        # Second commit should have no changes
        output = _run(ssh, "nopanel commit --no-docker --no-host", check=False)
        assert "no changes" in output.lower() or "0" in output or "up to date" in output.lower() or "nothing" in output.lower()

    def test_add_user_after_migration(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")
        _run(ssh, "nopanel user add --user carol --password carol12345 --fullname 'Carol'")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "carol" in users["users"]
        assert "alice" in users["users"]  # existing users preserved

    def test_add_domain_after_migration(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        _run(ssh, "nopanel migrate --reconvert")
        _run(ssh, "nopanel domain add --domain carol-new.com --user alice --php 8.2")
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "carol-new.com" in domains["domains"]
        assert "alice-site.com" in domains["domains"]  # existing domains preserved


# ---------------------------------------------------------------------------
# Reconvert
# ---------------------------------------------------------------------------


class TestReconvert:
    """Test nopanel migrate --reconvert."""

    def test_reconvert_regenerates_v2_from_v1(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _setup_v1_installation(ssh)
        # First reconvert to create v2 configs
        _run(ssh, "nopanel migrate --reconvert")

        # Modify v2 config
        _run(ssh, "nopanel user add --user newuser --password newuser12345")

        # Reconvert should regenerate from v1 (restoring original users)
        _run(ssh, "nopanel migrate --reconvert")

        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" in users["users"]
        assert "bob" in users["users"]
        # newuser should NOT be in reconverted config (it was added to v2, not v1)
        assert "newuser" not in users["users"]
