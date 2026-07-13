"""Tests for nopanel.config — YAML load/save, v1 JSON reading, conversion."""

import json
from pathlib import Path

import pytest

from nopanel.config import (
    convert_v1_databases,
    convert_v1_domains,
    convert_v1_modules,
    convert_v1_nopanel,
    convert_v1_users,
    create_default_config,
    init_config_dir,
    load_config,
    save_config,
)
from nopanel.models import FullConfig, LoginType, SSLMode, User


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory."""
    d = tmp_path / "nopanel"
    d.mkdir()
    return d


class TestSaveLoadYAML:
    def test_save_and_load_roundtrip(self, tmp_config_dir: Path):
        config = FullConfig(
            nopanel=create_default_config().nopanel,
            users=create_default_config().users,
        )
        config.users.users["alice"] = User(
            fullname="Alice", email="alice@test.com"
        )
        save_config(config, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        assert "alice" in loaded.users.users
        assert loaded.users.users["alice"].fullname == "Alice"

    def test_load_empty_dir(self, tmp_config_dir: Path):
        config = load_config(tmp_config_dir)
        assert len(config.users.users) == 0
        assert len(config.domains.domains) == 0

    def test_init_config_dir(self, tmp_path: Path):
        d = tmp_path / "nopanel"
        init_config_dir(d)
        assert (d / "nopanel.yml").exists()
        assert (d / "users.yml").exists()
        assert (d / "domains.yml").exists()
        assert (d / "databases.yml").exists()
        assert (d / "services.yml").exists()

    def test_save_sets_file_permissions_0600(self, tmp_config_dir: Path):
        """Config files with passwords must be chmod 0o600 (fix #7)."""
        import os

        config = FullConfig(
            nopanel=create_default_config().nopanel,
            users=create_default_config().users,
        )
        config.users.users["alice"] = User(
            fullname="Alice", password="secret12345"
        )
        save_config(config, tmp_config_dir)
        users_file = tmp_config_dir / "users.yml"
        mode = os.stat(users_file).st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_create_default_config_includes_php_8_5(self):
        config = create_default_config()
        assert "8.2" in config.services.php
        assert "8.3" in config.services.php
        assert "8.4" in config.services.php
        assert "8.5" in config.services.php
        assert "8.4" in config.nopanel.php.versions
        assert "8.5" in config.nopanel.php.versions


class TestV1Conversion:
    def test_convert_v1_users(self):
        v1_data = {
            "alice": {
                "name": "alice",
                "fullname": "Alice Smith",
                "email": "alice@example.com",
                "login": "ssh",
                "admin": "true",
                "password": "secret123",
            },
            "bob": {
                "name": "bob",
                "fullname": "Bob Jones",
                "email": "",
                "login": "sftp",
                "admin": "false",
                "password": "",
            },
        }
        result = convert_v1_users(v1_data)
        assert "alice" in result.users
        assert result.users["alice"].fullname == "Alice Smith"
        assert result.users["alice"].email == "alice@example.com"
        assert result.users["alice"].login == LoginType.SSH
        assert result.users["alice"].admin is True
        assert result.users["bob"].login == LoginType.SFTP
        assert result.users["bob"].admin is False

    def test_convert_v1_domains(self):
        v1_data = {
            "alice": {
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                    "web_ssl": "le",
                    "web_aliases": "www.example.com,test.example.com",
                },
                "inactive.com": {
                    "name": "inactive.com",
                    "user": "alice",
                    "web": "false",
                },
            }
        }
        result = convert_v1_domains(v1_data)
        assert "example.com" in result.domains
        assert "inactive.com" not in result.domains
        d = result.domains["example.com"]
        assert d.user == "alice"
        assert d.php_version == "8.2"
        assert d.ssl == SSLMode.AUTO
        assert d.aliases == ["www.example.com", "test.example.com"]

    def test_convert_v1_domains_logs_non_web(self, caplog):
        """Non-web domains should be logged as skipped (fix #13)."""
        import logging

        v1_data = {
            "alice": {
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                },
                "dns-only.com": {
                    "name": "dns-only.com",
                    "user": "alice",
                    "web": "false",
                },
            }
        }
        with caplog.at_level(logging.WARNING, logger="nopanel.config"):
            result = convert_v1_domains(v1_data)
        assert "example.com" in result.domains
        assert "dns-only.com" not in result.domains
        assert any("dns-only.com" in r.message for r in caplog.records)

    def test_convert_v1_domains_no_php(self):
        v1_data = {
            "alice": {
                "static.com": {
                    "name": "static.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "false",
                    "web_ssl": "no",
                },
            }
        }
        result = convert_v1_domains(v1_data)
        d = result.domains["static.com"]
        assert d.php_version is None
        assert d.ssl == SSLMode.NONE

    def test_convert_v1_domains_with_docroot(self):
        v1_data = {
            "alice": {
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                    "web_docroot": "htdocs",
                },
            }
        }
        result = convert_v1_domains(v1_data)
        d = result.domains["example.com"]
        assert d.docroot == "htdocs"

    def test_convert_v1_domains_default_docroot(self):
        v1_data = {
            "alice": {
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                },
            }
        }
        result = convert_v1_domains(v1_data)
        d = result.domains["example.com"]
        assert d.docroot == "public_html"

    def test_convert_v1_databases(self):
        v1_data = {
            "alice": {
                "alice_blog": {
                    "name": "alice_blog",
                    "dbuser": "alice_blog",
                    "password": "pass12345",
                },
            }
        }
        result = convert_v1_databases(v1_data)
        assert "alice_blog" in result.databases
        assert result.databases["alice_blog"].user == "alice"
        assert result.databases["alice_blog"].password == "pass12345"

    def test_convert_v1_modules(self):
        v1_data = {
            "mariadb": {"installed": "true", "password": "rootpass"},
            "php-fpm": {"8.2": "true", "8.3": "true", "7.4": "false"},
            "valkey": {"installed": "true"},
        }
        result = convert_v1_modules(v1_data)
        assert result.mariadb.root_password == "rootpass"
        assert "8.2" in result.php
        assert "8.3" in result.php
        assert "7.4" not in result.php

    def test_convert_v1_nopanel(self):
        v1_data = {"version": "1", "auto_elevate": "true"}
        result = convert_v1_nopanel(v1_data)
        assert result.version == 2  # v2 always
        # auto_elevate is no longer in v2 Settings (removed as unused)

    def test_convert_v1_nopanel_migrates_admin_email(self):
        """admin_email should be extracted from first user with an email (fix #3)."""
        v1_data = {"version": "1"}
        v1_users = {
            "alice": {"name": "alice", "email": "alice@example.com"},
            "bob": {"name": "bob", "email": "bob@example.com"},
        }
        result = convert_v1_nopanel(v1_data, v1_users)
        assert result.settings.admin_email == "alice@example.com"

    def test_convert_v1_nopanel_no_email_returns_empty(self):
        """If no users have email, admin_email should remain empty (fix #3)."""
        v1_data = {"version": "1"}
        v1_users = {"alice": {"name": "alice", "email": ""}}
        result = convert_v1_nopanel(v1_data, v1_users)
        assert result.settings.admin_email == ""

    def test_convert_v1_nopanel_no_users_returns_empty(self):
        """If no users dict provided, admin_email should remain empty (fix #3)."""
        v1_data = {"version": "1"}
        result = convert_v1_nopanel(v1_data)
        assert result.settings.admin_email == ""

    def test_convert_v1_nopanel_preserves_mariadb_branch(self):
        """mariadb.default_branch should be preserved from v1 (fix #3)."""
        v1_data = {"version": "1", "mariadb": {"default_branch": "latest"}}
        result = convert_v1_nopanel(v1_data)
        assert result.mariadb.default_branch == "latest"

    def test_convert_v1_nopanel_preserves_php_modules(self):
        """php.additional_modules should be preserved from v1 (fix #3)."""
        v1_data = {"version": "1", "php": {"additional_modules": "imagick,redis"}}
        result = convert_v1_nopanel(v1_data)
        assert "imagick" in result.php.additional_modules
        assert "redis" in result.php.additional_modules


class TestV1JSONReading:
    def test_read_v1_users(self, tmp_path: Path):
        data = {"alice": {"name": "alice", "fullname": "Alice"}}
        (tmp_path / "users.json").write_text(json.dumps(data))
        from nopanel.config import read_v1_users

        result = read_v1_users(tmp_path)
        assert "alice" in result

    def test_read_v1_nopanel(self, tmp_path: Path):
        data = {"version": "1"}
        (tmp_path / "nopanel.json").write_text(json.dumps(data))
        from nopanel.config import read_v1_nopanel

        result = read_v1_nopanel(tmp_path)
        assert result["version"] == "1"

    def test_read_v1_user_domains(self, tmp_path: Path):
        nopanel_dir = tmp_path / ".nopanel"
        nopanel_dir.mkdir()
        data = {"example.com": {"name": "example.com", "web": "true"}}
        (nopanel_dir / "domains.json").write_text(json.dumps(data))
        from nopanel.config import read_v1_user_domains

        result = read_v1_user_domains(tmp_path)
        assert "example.com" in result


class TestConvertV1ModulesParseBool:
    """Fix #5: convert_v1_modules must use _parse_bool for MariaDB/Valkey installed."""

    def test_mariadb_string_false_not_installed(self):
        """v1 stores 'false' as string which is truthy in Python — must use _parse_bool."""
        from nopanel.config import convert_v1_modules
        v1 = {"mariadb": {"installed": "false", "password": "secret"}}
        result = convert_v1_modules(v1)
        # MariaDB should NOT be enabled when installed is string "false"
        assert result.mariadb.root_password == ""

    def test_mariadb_string_true_installed(self):
        from nopanel.config import convert_v1_modules
        v1 = {"mariadb": {"installed": "true", "password": "secret"}}
        result = convert_v1_modules(v1)
        assert result.mariadb.root_password == "secret"

    def test_valkey_string_false_not_installed(self):
        from nopanel.config import convert_v1_modules
        v1 = {"valkey": {"installed": "false"}}
        result = convert_v1_modules(v1)
        # Valkey should use default (not explicitly enabled)
        assert result.valkey.image == "valkey/valkey:8-alpine"

    def test_valkey_string_true_installed(self):
        from nopanel.config import convert_v1_modules
        v1 = {"valkey": {"installed": "true"}}
        result = convert_v1_modules(v1)
        assert result.valkey.image == "valkey/valkey:8-alpine"
