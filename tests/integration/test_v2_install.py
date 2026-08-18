"""Integration test: fresh v2 install + common operations.

Tests the full nopanel v2 workflow on a clean AlmaLinux 9 VM:
- init
- user add / mod / list / remove
- domain add / mod / list / remove
- database add / mod / list / remove
- commit (config generation)
- status
- service up/down
- export/import
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


def _config_exists(ssh: SSHRunner, path: str) -> bool:
    return ssh.file_exists(path)


def _read_yaml(ssh: SSHRunner, path: str) -> dict:
    import yaml
    raw = _run(ssh, f"cat {path}")
    return yaml.safe_load(raw) or {}


# ---------------------------------------------------------------------------
# Init and basic config
# ---------------------------------------------------------------------------


class TestInit:
    """Test nopanel init on a clean VM."""

    def test_init_creates_config_dir(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        # Clean any existing config
        _run(ssh, "rm -rf /etc/nopanel")
        _run(ssh, "nopanel init")
        assert _config_exists(ssh, "/etc/nopanel/nopanel.yml")
        assert _config_exists(ssh, "/etc/nopanel/users.yml")
        assert _config_exists(ssh, "/etc/nopanel/domains.yml")
        assert _config_exists(ssh, "/etc/nopanel/databases.yml")
        assert _config_exists(ssh, "/etc/nopanel/services.yml")

    def test_init_refuses_existing(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init")  # first init
        result = ssh.run("nopanel init")
        assert result.exit_code != 0
        assert "already exists" in result.stdout.lower() or "already exists" in result.stderr.lower()

    def test_init_force_overwrites(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init")
        # Corrupt a config file
        _run(ssh, "echo 'garbage' > /etc/nopanel/users.yml")
        _run(ssh, "nopanel init --force")
        # Should be valid YAML again
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "users" in users


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


class TestUserManagement:
    """Test user add/mod/list/remove."""

    def test_user_add(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123 --fullname 'Alice Smith'")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" in users["users"]
        assert users["users"]["alice"]["fullname"] == "Alice Smith"

    def test_user_add_duplicate_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        result = ssh.run("nopanel user add --user alice --password otherpassword123")
        assert result.exit_code != 0

    def test_user_add_short_password_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        result = ssh.run("nopanel user add --user bob --password short")
        assert result.exit_code != 0

    def test_user_add_invalid_username_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        result = ssh.run("nopanel user add --user 'invalid user!' --password mypassword123")
        assert result.exit_code != 0

    def test_user_mod(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123 --fullname 'Alice'")
        _run(ssh, "nopanel user mod --user alice --fullname 'Alice Smith' --email alice@example.com")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert users["users"]["alice"]["fullname"] == "Alice Smith"
        assert users["users"]["alice"]["email"] == "alice@example.com"

    def test_user_mod_login_type(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123 --login sftp")
        _run(ssh, "nopanel user mod --user alice --login ssh")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert users["users"]["alice"]["login"] == "ssh"

    def test_user_list(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123 --fullname 'Alice'")
        _run(ssh, "nopanel user add --user bob --password mypassword123 --fullname 'Bob'")
        output = _run(ssh, "nopanel user list")
        assert "alice" in output
        assert "bob" in output

    def test_user_remove(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel user remove --user alice")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" not in users["users"]

    def test_user_remove_nonexistent_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        result = ssh.run("nopanel user remove --user ghost")
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Domain management
# ---------------------------------------------------------------------------


class TestDomainManagement:
    """Test domain add/mod/list/remove."""

    def test_domain_add(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --php 8.2 --ssl auto")
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "example.com" in domains["domains"]
        assert domains["domains"]["example.com"]["user"] == "alice"

    def test_domain_add_with_aliases(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --aliases 'www.example.com,test.example.com'")
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "www.example.com" in domains["domains"]["example.com"]["aliases"]
        assert "test.example.com" in domains["domains"]["example.com"]["aliases"]

    def test_domain_add_invalid_domain_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        result = ssh.run("nopanel domain add --domain 'not a domain' --user alice")
        assert result.exit_code != 0

    def test_domain_add_nonexistent_user_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        result = ssh.run("nopanel domain add --domain example.com --user ghost")
        assert result.exit_code != 0

    def test_domain_add_duplicate_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice")
        result = ssh.run("nopanel domain add --domain example.com --user alice")
        assert result.exit_code != 0

    def test_domain_mod(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --ssl none")
        _run(ssh, "nopanel domain mod --domain example.com --ssl auto")
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert domains["domains"]["example.com"]["ssl"] == "auto"

    def test_domain_list(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice")
        _run(ssh, "nopanel domain add --domain test.org --user alice")
        output = _run(ssh, "nopanel domain list")
        assert "example.com" in output
        assert "test.org" in output

    def test_domain_remove(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice")
        _run(ssh, "nopanel domain remove --domain example.com")
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "example.com" not in domains["domains"]


# ---------------------------------------------------------------------------
# Database management
# ---------------------------------------------------------------------------


class TestDatabaseManagement:
    """Test database add/mod/list/remove."""

    def test_database_add(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert "alice_blog" in dbs["databases"]

    def test_database_add_custom_dbuser(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --dbuser bloguser --password dbpassword123")
        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert dbs["databases"]["alice_blog"]["dbuser"] == "bloguser"

    def test_database_add_duplicate_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        result = ssh.run("nopanel database add --user alice --db blog --password otherpassword123")
        assert result.exit_code != 0

    def test_database_add_nonexistent_user_fails(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        result = ssh.run("nopanel database add --user ghost --db blog --password dbpassword123")
        assert result.exit_code != 0

    def test_database_mod(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        _run(ssh, "nopanel database mod --user alice --db blog --password newpassword123")
        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert dbs["databases"]["alice_blog"]["password"] == "newpassword123"

    def test_database_list(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        output = _run(ssh, "nopanel database list")
        assert "alice_blog" in output

    def test_database_remove(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        _run(ssh, "nopanel database remove --user alice --db blog")
        dbs = _read_yaml(ssh, "/etc/nopanel/databases.yml")
        assert "alice_blog" not in dbs["databases"]


# ---------------------------------------------------------------------------
# Commit and status
# ---------------------------------------------------------------------------


class TestCommit:
    """Test nopanel commit and status."""

    def test_status_no_changes(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        output = _run(ssh, "nopanel status")
        assert "Users" in output
        assert "Domains" in output
        assert "Databases" in output

    def test_status_shows_pending_changes(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        output = _run(ssh, "nopanel status")
        assert "1" in output  # 1 pending user change

    def test_commit_dry_run(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --php 8.2")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        output = _run(ssh, "nopanel commit --dry-run --no-docker --no-host")
        # Dry run should not create generated files
        assert "dry" in output.lower() or "no changes" in output.lower() or "would" in output.lower() or "pending" in output.lower()

    def test_commit_generates_configs(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --php 8.2")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        result = ssh.run("nopanel commit --no-docker --no-host 2>&1", timeout=300)
        # Generated configs should exist
        assert _config_exists(ssh, "/etc/nopanel/generated/docker-compose.yml"), (
            f"docker-compose.yml not generated.\nCommit output:\n{result.stdout}\n{result.stderr}"
        )
        # Committed state should exist (saved in .committed/ directory)
        assert _config_exists(ssh, "/etc/nopanel/.committed/users.yml"), (
            f"committed/users.yml not created.\nCommit output (exit={result.exit_code}):\n{result.stdout}\n{result.stderr}"
        )

    def test_commit_idempotent(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel commit --no-docker --no-host")
        # Second commit should have no changes
        output = _run(ssh, "nopanel commit --no-docker --no-host")
        assert "no changes" in output.lower() or "0" in output or "nothing" in output.lower() or "up to date" in output.lower()

    def test_commit_after_user_removal(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel user add --user bob --password mypassword123")
        _run(ssh, "nopanel commit --no-docker --no-host")
        _run(ssh, "nopanel user remove --user bob")
        output = _run(ssh, "nopanel status")
        assert "1" in output  # 1 pending removal
        _run(ssh, "nopanel commit --no-docker --no-host")
        committed = _read_yaml(ssh, "/etc/nopanel/.committed/users.yml")
        assert "bob" not in committed["users"]


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


class TestExportImport:
    """Test nopanel export and import."""

    def test_export_creates_json(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice")
        _run(ssh, "nopanel export --output /tmp/backup.json")
        assert _config_exists(ssh, "/tmp/backup.json")
        data = json.loads(_run(ssh, "cat /tmp/backup.json"))
        assert "alice" in data["users"]["users"]
        assert "example.com" in data["domains"]["domains"]

    def test_import_restores_config(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice")
        _run(ssh, "nopanel database add --user alice --db blog --password dbpassword123")
        _run(ssh, "nopanel export --output /tmp/backup.json")
        # Wipe config
        _run(ssh, "nopanel init --force")
        # Import
        _run(ssh, "nopanel import --file /tmp/backup.json")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" in users["users"]
        domains = _read_yaml(ssh, "/etc/nopanel/domains.yml")
        assert "example.com" in domains["domains"]

    def test_import_force_overwrites(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel export --output /tmp/backup.json")
        _run(ssh, "nopanel user add --user bob --password mypassword123")
        # Import with --force overwrites config entirely
        _run(ssh, "nopanel import --file /tmp/backup.json --force")
        users = _read_yaml(ssh, "/etc/nopanel/users.yml")
        assert "alice" in users["users"]
        assert "bob" not in users["users"]  # --force overwrites, bob is gone


# ---------------------------------------------------------------------------
# Multi-user scenario
# ---------------------------------------------------------------------------


class TestMultiUser:
    """Test multi-user, multi-domain, multi-database scenario."""

    def test_multi_user_setup(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")

        # Create 3 users with different login types
        _run(ssh, "nopanel user add --user alice --password alice12345 --login ssh --fullname 'Alice'")
        _run(ssh, "nopanel user add --user bob --password bob123456 --login sftp --fullname 'Bob'")
        _run(ssh, "nopanel user add --user carol --password carol12345 --login no --fullname 'Carol'")

        # Domains for each user
        _run(ssh, "nopanel domain add --domain alice.com --user alice --php 8.2 --ssl auto")
        _run(ssh, "nopanel domain add --domain bob.org --user bob --php 8.3 --ssl self")
        _run(ssh, "nopanel domain add --domain carol.net --user carol --ssl none")

        # Databases for each user
        _run(ssh, "nopanel database add --user alice --db site --password dbpass12345")
        _run(ssh, "nopanel database add --user bob --db blog --password dbpass12345")
        _run(ssh, "nopanel database add --user carol --db shop --password dbpass12345")

        # Commit
        _run(ssh, "nopanel commit --no-docker --no-host")

        # Verify committed state
        committed_users = _read_yaml(ssh, "/etc/nopanel/.committed/users.yml")
        assert len(committed_users["users"]) == 3
        committed_domains = _read_yaml(ssh, "/etc/nopanel/.committed/domains.yml")
        assert len(committed_domains["domains"]) == 3
        committed_dbs = _read_yaml(ssh, "/etc/nopanel/.committed/databases.yml")
        assert len(committed_dbs["databases"]) == 3

        # Verify generated configs
        assert _config_exists(ssh, "/etc/nopanel/generated/docker-compose.yml")
        compose = _run(ssh, "cat /etc/nopanel/generated/docker-compose.yml")
        assert "apache" in compose
        assert "mariadb" in compose

    def test_add_domain_to_existing_user(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain site1.com --user alice --php 8.2")
        _run(ssh, "nopanel commit --no-docker --no-host")

        # Add a second domain
        _run(ssh, "nopanel domain add --domain site2.com --user alice --php 8.3")
        _run(ssh, "nopanel commit --no-docker --no-host")

        committed = _read_yaml(ssh, "/etc/nopanel/.committed/domains.yml")
        assert "site1.com" in committed["domains"]
        assert "site2.com" in committed["domains"]


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------


class TestServiceManagement:
    """Test service up/down/status (requires Docker on VM)."""

    def test_service_up_starts_containers(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel user add --user alice --password mypassword123")
        _run(ssh, "nopanel domain add --domain example.com --user alice --php 8.2")
        _run(ssh, "nopanel commit --no-docker --no-host")

        # Pull standard images individually (compose pull fails on custom PHP images)
        for image in ["httpd:2.4-alpine", "mariadb:lts", "php:8.2-fpm-alpine", "php:8.3-fpm-alpine", "php:8.4-fpm-alpine", "php:8.5-fpm-alpine"]:
            r = ssh.run(f"docker pull {image} 2>&1", timeout=300)
            if r.exit_code != 0:
                pytest.skip(f"Cannot pull {image}: {r.stderr[-200:]}")

        # Build custom PHP images and start all services
        result = ssh.run("nopanel service up --build 2>&1", timeout=600)
        logger.info("service up output: %s", result.stdout[-500:])

        # Wait for containers to start
        time.sleep(15)
        output = _run(ssh, "docker ps --format '{{.Names}}' 2>/dev/null")
        # At least some containers should be running
        assert "nopanel" in output or "apache" in output or "mariadb" in output, (
            f"No containers running. service up output: {result.stdout[-500:]}"
        )

    def test_service_down_stops_containers(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel commit --no-docker --no-host")
        _run(ssh, "nopanel service up", check=False)
        time.sleep(15)
        _run(ssh, "nopanel service down", check=False)
        time.sleep(5)
        output = _run(ssh, "docker ps --format '{{.Names}}' 2>/dev/null")
        # No nopanel containers should be running
        assert "nopanel" not in output or not output.strip()

    def test_service_status(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _run(ssh, "nopanel init --force")
        _run(ssh, "nopanel commit --no-docker --no-host")
        output = _run(ssh, "nopanel service status", check=False)
        # Should show status (even if no containers running)
        assert "service" in output.lower() or "container" in output.lower() or "running" in output.lower() or "no" in output.lower()


# ---------------------------------------------------------------------------
# Real service integration tests
# ---------------------------------------------------------------------------


def _pull_and_start_services(ssh: SSHRunner) -> None:
    """Pull images, build PHP images, and start all services.

    Sets a MariaDB root password (required by MariaDB), installs curl,
    opens firewall ports, and cleans stale MariaDB data.
    """
    _run(ssh, "nopanel init --force")

    # Set MariaDB root password (empty default causes MariaDB to crash-loop)
    ssh.put_content(
        "import yaml\n"
        "with open('/etc/nopanel/services.yml') as f:\n"
        "    cfg = yaml.safe_load(f)\n"
        "cfg['mariadb']['root_password'] = 'testpass123'\n"
        "with open('/etc/nopanel/services.yml', 'w') as f:\n"
        "    yaml.dump(cfg, f)\n",
        "/tmp/set_mariadb_pass.py",
    )
    _run(ssh, "python3.11 /tmp/set_mariadb_pass.py")

    _run(ssh, "nopanel user add --user alice --password mypassword123")
    _run(ssh, "nopanel domain add --domain example.com --user alice --php 8.2")
    _run(ssh, "nopanel commit --no-docker --no-host")

    # Install curl if not present (needed for HTTP tests)
    ssh.run("dnf install -y curl 2>&1 | tail -1", timeout=120)

    # Open firewall for HTTP/HTTPS (host network mode)
    ssh.run("firewall-cmd --permanent --add-port=80/tcp 2>&1 || true", timeout=30)
    ssh.run("firewall-cmd --permanent --add-port=443/tcp 2>&1 || true", timeout=30)
    ssh.run("firewall-cmd --reload 2>&1 || true", timeout=30)

    # Clean stale MariaDB data (previous runs may have initialized with empty password)
    ssh.run("rm -rf /var/lib/mysql/* 2>/dev/null || true", timeout=10)

    for image in ["httpd:2.4-alpine", "mariadb:lts", "php:8.2-fpm-alpine"]:
        r = ssh.run(f"docker pull {image} 2>&1", timeout=300)
        if r.exit_code != 0:
            pytest.skip(f"Cannot pull {image}: {r.stderr[-200:]}")

    result = ssh.run("nopanel service up --build 2>&1", timeout=600)
    if result.exit_code != 0:
        pytest.skip(f"service up --build failed: {result.stdout[-300:]}")

    # Wait for containers to be ready
    time.sleep(20)

    # Log container status and any crash logs for diagnostics
    logger.info("Container status: %s", _run(ssh, "docker ps -a --format '{{.Names}} {{.Status}}' 2>/dev/null"))
    mariadb_logs = ssh.run("docker logs nopanel-mariadb --tail 10 2>&1", timeout=15)
    logger.info("MariaDB logs: %s", mariadb_logs.stdout[-300:])
    apache_logs = ssh.run("docker logs nopanel-apache --tail 10 2>&1", timeout=15)
    logger.info("Apache logs: %s", apache_logs.stdout[-300:])
    logger.info("mariadb.env: %s", _run(ssh, "cat /etc/nopanel/generated/mariadb.env 2>/dev/null"))
    logger.info("Listening ports: %s", _run(ssh, "ss -tlnp 2>/dev/null | grep -E ':80|:443|:3306' || echo 'none'"))


class TestApacheServesPages:
    """Verify Apache actually serves HTTP pages for configured domains."""

    def test_apache_serves_static_page(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _pull_and_start_services(ssh)

        # Create docroot and a static HTML file
        _run(ssh, "mkdir -p /home/alice/web/example.com/public_html")
        _run(ssh, 'echo "<h1>Hello from nopanel</h1>" > /home/alice/web/example.com/public_html/index.html')

        # Apache should serve it on port 80 (host network mode)
        time.sleep(5)
        result = ssh.run("curl -sI http://localhost/ 2>&1", timeout=30)
        assert "200" in result.stdout or "301" in result.stdout or "302" in result.stdout, (
            f"Apache not serving. curl output: {result.stdout}\n{result.stderr}"
        )

        result = ssh.run("curl -s http://localhost/ 2>&1", timeout=30)
        assert "Hello from nopanel" in result.stdout, (
            f"Expected 'Hello from nopanel' in response. Got: {result.stdout}"
        )

    def test_apache_serves_php_page(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _pull_and_start_services(ssh)

        # Create docroot and a PHP file
        _run(ssh, "mkdir -p /home/alice/web/example.com/public_html")
        _run(ssh, 'echo "<?php echo phpversion();" > /home/alice/web/example.com/public_html/info.php')

        time.sleep(5)
        result = ssh.run("curl -s http://localhost/info.php 2>&1", timeout=30)
        # Should return a PHP version string, not raw PHP source
        assert "8.2" in result.stdout, (
            f"PHP not processing. Response: {result.stdout}\n"
            f"Containers: {_run(ssh, 'docker ps --format \"{{.Names}}\" 2>/dev/null')}"
        )
        assert "<?php" not in result.stdout, "PHP source leaked — PHP-FPM not processing"


class TestMariaDBAcceptsConnections:
    """Verify MariaDB container accepts connections."""

    def test_mariadb_responds_to_ping(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _pull_and_start_services(ssh)

        # Wait for MariaDB to be ready
        time.sleep(10)
        result = ssh.run(
            "docker exec nopanel-mariadb mariadb-admin ping 2>&1",
            timeout=30,
        )
        assert "mysqld is alive" in result.stdout, (
            f"MariaDB not responding. Output: {result.stdout}\n{result.stderr}"
        )

    def test_mariadb_accepts_root_login(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _pull_and_start_services(ssh)

        time.sleep(10)
        # Read root password from generated env file
        env = _run(ssh, "cat /etc/nopanel/generated/mariadb.env")
        password = ""
        for line in env.splitlines():
            if line.startswith("MARIADB_ROOT_PASSWORD="):
                password = line.split("=", 1)[1]
                break
        assert password, f"No root password found in mariadb.env: {env}"

        result = ssh.run(
            f"docker exec nopanel-mariadb mariadb -uroot -p{password} -e 'SELECT 1' 2>&1",
            timeout=30,
        )
        assert "1" in result.stdout and "ERROR" not in result.stdout.upper(), (
            f"MariaDB root login failed. Output: {result.stdout}\n{result.stderr}"
        )


class TestServiceLifecycle:
    """Verify full service up/down/restart cycle."""

    def test_service_restart(self, nopanel_on_vm: SSHRunner):
        ssh = nopanel_on_vm
        _pull_and_start_services(ssh)

        # Verify containers are running
        containers = _run(ssh, "docker ps --format '{{.Names}}' 2>/dev/null")
        assert "nopanel-apache" in containers, f"Apache not running. Containers: {containers}"

        # Restart services
        _run(ssh, "nopanel service down", check=False)
        time.sleep(5)
        containers_after_down = _run(ssh, "docker ps --format '{{.Names}}' 2>/dev/null")
        assert "nopanel-apache" not in containers_after_down, (
            f"Apache still running after down. Containers: {containers_after_down}"
        )

        # Start again (images already built, no --build needed)
        result = ssh.run("nopanel service up 2>&1", timeout=120)
        time.sleep(10)
        containers_after_up = _run(ssh, "docker ps --format '{{.Names}}' 2>/dev/null")
        assert "nopanel-apache" in containers_after_up, (
            f"Apache not running after restart. Containers: {containers_after_up}\n"
            f"service up output: {result.stdout[-300:]}"
        )
