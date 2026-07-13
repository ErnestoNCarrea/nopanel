"""Tests for nopanel CLI commands using Typer's CliRunner."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nopanel.cli import app
from nopanel.config import load_config, save_config
from nopanel.models import FullConfig

runner = CliRunner()


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch) -> Path:
    """Patch DEFAULT_CONFIG_DIR to use a temp directory."""
    d = tmp_path / "nopanel"
    d.mkdir()
    # Patch the config module's default
    import nopanel.config as config_mod
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", d)
    # Also patch state module
    import nopanel.state as state_mod
    monkeypatch.setattr(state_mod, "DEFAULT_CONFIG_DIR", d)
    # Patch commit module
    import nopanel.commit as commit_mod
    monkeypatch.setattr(commit_mod, "DEFAULT_CONFIG_DIR", d)
    # Patch commands that import DEFAULT_CONFIG_DIR
    import nopanel.commands.user as user_cmd
    monkeypatch.setattr(user_cmd, "DEFAULT_CONFIG_DIR", d)
    import nopanel.commands.commit as commit_cmd
    monkeypatch.setattr(commit_cmd, "DEFAULT_CONFIG_DIR", d)
    return d


class TestVersionCommand:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "nopanel" in result.stdout


class TestInitCommand:
    def test_init(self, tmp_config_dir: Path):
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_config_dir / "nopanel.yml").exists()

    def test_init_already_exists(self, tmp_config_dir: Path):
        # Create config first
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        # Try again without --force
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 1


class TestUserCommands:
    def test_user_add(self, tmp_config_dir: Path):
        result = runner.invoke(app, [
            "user", "add",
            "--user", "alice",
            "--password", "password123",
            "--fullname", "Alice Smith",
            "--email", "alice@test.com",
        ])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert "alice" in config.users.users
        assert config.users.users["alice"].fullname == "Alice Smith"

    def test_user_add_invalid_username(self, tmp_config_dir: Path):
        result = runner.invoke(app, [
            "user", "add",
            "--user", "Alice",  # uppercase invalid
            "--password", "password123",
        ])
        assert result.exit_code == 1

    def test_user_add_short_password(self, tmp_config_dir: Path):
        result = runner.invoke(app, [
            "user", "add",
            "--user", "alice",
            "--password", "short",
        ])
        assert result.exit_code == 1

    def test_user_add_duplicate(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        assert result.exit_code == 1

    def test_user_list(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["user", "add", "--user", "bob", "--password", "password123"])
        result = runner.invoke(app, ["user", "list"])
        assert result.exit_code == 0
        assert "alice" in result.stdout
        assert "bob" in result.stdout

    def test_user_remove(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, ["user", "remove", "--user", "alice"])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert "alice" not in config.users.users

    def test_user_host_commands_with_pending(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["commit", "--no-docker"])
        result = runner.invoke(app, ["user", "host-commands"])
        assert result.exit_code == 0
        assert "useradd" in result.stdout
        assert "alice" in result.stdout

    def test_user_host_commands_raw(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["commit", "--no-docker"])
        result = runner.invoke(app, ["user", "host-commands", "--raw"])
        assert result.exit_code == 0
        # Raw output should contain just the commands, no rich formatting
        assert "useradd" in result.stdout
        assert "alice" in result.stdout
        assert "Run these commands" not in result.stdout
        assert "Pending" not in result.stdout

    def test_user_host_commands_done(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["commit", "--no-docker"])
        result = runner.invoke(app, ["user", "host-commands", "--done"])
        assert result.exit_code == 0
        assert "Cleared" in result.stdout
        # Subsequent host-commands should show no pending
        result = runner.invoke(app, ["user", "host-commands"])
        assert result.exit_code == 0
        assert "No pending" in result.stdout

    def test_user_host_commands_no_changes(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["user", "host-commands"])
        assert result.exit_code == 0
        assert "No pending" in result.stdout

    def test_user_host_commands_raw_no_changes(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["user", "host-commands", "--raw"])
        assert result.exit_code == 0
        # Raw output with no changes should be empty (no "No pending" message)
        assert "useradd" not in result.stdout
        assert "No pending" not in result.stdout


class TestDomainCommands:
    def test_domain_add(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, [
            "domain", "add",
            "--domain", "example.com",
            "--user", "alice",
            "--php", "8.2",
            "--ssl", "auto",
        ])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert "example.com" in config.domains.domains

    def test_domain_add_invalid(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, [
            "domain", "add",
            "--domain", "not-a-domain",
            "--user", "alice",
        ])
        assert result.exit_code == 1

    def test_domain_list(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["domain", "add", "--domain", "example.com", "--user", "alice"])
        result = runner.invoke(app, ["domain", "list"])
        assert result.exit_code == 0
        assert "example.com" in result.stdout


class TestDatabaseCommands:
    def test_database_add(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, [
            "database", "add",
            "--user", "alice",
            "--db", "blog",
            "--password", "pass12345",
        ])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert "alice_blog" in config.databases.databases

    def test_database_list(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["database", "add", "--user", "alice", "--db", "blog", "--password", "pass12345"])
        result = runner.invoke(app, ["database", "list"])
        assert result.exit_code == 0
        assert "alice_blog" in result.stdout


class TestExportImport:
    def test_export_import_roundtrip(self, tmp_config_dir: Path, tmp_path: Path):
        # Create some config
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["domain", "add", "--domain", "example.com", "--user", "alice"])

        # Export
        export_file = tmp_path / "export.json"
        result = runner.invoke(app, ["export", "--output", str(export_file)])
        assert result.exit_code == 0
        assert export_file.exists()

        # Verify export content
        data = json.loads(export_file.read_text())
        assert "alice" in data["users"]["users"]
        assert "example.com" in data["domains"]["domains"]

        # Clear config
        save_config(FullConfig(), tmp_config_dir)

        # Import
        result = runner.invoke(app, ["import", "--file", str(export_file)])
        assert result.exit_code == 0

        # Verify import
        config = load_config(tmp_config_dir)
        assert "alice" in config.users.users
        assert "example.com" in config.domains.domains

    def test_import_dry_run(self, tmp_config_dir: Path, tmp_path: Path):
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(FullConfig().model_dump(mode="json")))
        result = runner.invoke(app, ["import", "--file", str(export_file), "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.stdout.lower()


class TestStatusCommand:
    def test_status_empty(self, tmp_config_dir: Path):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_with_data(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "alice" in result.stdout or "Users" in result.stdout


class TestMigrateCommand:
    def _write_v1_config(self, config_dir: Path):
        """Write minimal v1 config for migrate tests."""
        (config_dir / "nopanel.json").write_text(json.dumps({"version": "1"}))
        (config_dir / "users.json").write_text(json.dumps({
            "alice": {"name": "alice", "fullname": "Alice"}
        }))
        (config_dir / "modules.json").write_text(json.dumps({
            "mariadb": {"installed": "true", "password": ""},
            "valkey": {"installed": "true"},
        }))

    def test_migrate_pre_check(self, tmp_config_dir: Path, monkeypatch):
        self._write_v1_config(tmp_config_dir)

        from nopanel.migrate import MigrationEngine

        # Use a mock system ops
        class TestMockOps:
            def detect_os(self): return "almalinux"
            def stop_service(self, s): return True
            def start_service(self, s): return True
            def disable_service(self, s): return True
            def get_mariadb_version(self): return "10.11.8"
            def get_installed_php_versions(self): return ["8.2"]
            def get_v1_user_list(self): return ["alice"]

        original_init = MigrationEngine.__init__
        def patched_init(self, config_dir=None, **kwargs):
            if config_dir is None:
                config_dir = tmp_config_dir
            kwargs.setdefault('system_ops', TestMockOps())
            kwargs.setdefault('home_dir', tmp_config_dir.parent / "home")
            original_init(self, config_dir=config_dir, **kwargs)

        monkeypatch.setattr(MigrationEngine, "__init__", patched_init)

        result = runner.invoke(app, ["migrate", "--pre-check"])
        assert result.exit_code == 0
        assert "Migration Pre-Check" in result.stdout

    def test_migrate_dry_run(self, tmp_config_dir: Path, monkeypatch):
        self._write_v1_config(tmp_config_dir)

        class TestMockOps:
            def detect_os(self): return "almalinux"
            def stop_service(self, s): return True
            def start_service(self, s): return True
            def disable_service(self, s): return True
            def get_mariadb_version(self): return "10.11.8"
            def get_installed_php_versions(self): return ["8.2"]
            def get_v1_user_list(self): return ["alice"]

        from nopanel.migrate import MigrationEngine
        original_init = MigrationEngine.__init__
        def patched_init(self, config_dir=None, **kwargs):
            if config_dir is None:
                config_dir = tmp_config_dir
            kwargs.setdefault('system_ops', TestMockOps())
            kwargs.setdefault('home_dir', tmp_config_dir.parent / "home")
            original_init(self, config_dir=config_dir, **kwargs)

        monkeypatch.setattr(MigrationEngine, "__init__", patched_init)

        result = runner.invoke(app, ["migrate", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.stdout.lower()

    def test_migrate_diff(self, tmp_config_dir: Path, monkeypatch):
        self._write_v1_config(tmp_config_dir)

        class TestMockOps:
            def detect_os(self): return "almalinux"
            def stop_service(self, s): return True
            def start_service(self, s): return True
            def disable_service(self, s): return True
            def get_mariadb_version(self): return "10.11.8"
            def get_installed_php_versions(self): return ["8.2"]
            def get_v1_user_list(self): return ["alice"]

        from nopanel.migrate import MigrationEngine
        original_init = MigrationEngine.__init__
        def patched_init(self, config_dir=None, **kwargs):
            if config_dir is None:
                config_dir = tmp_config_dir
            kwargs.setdefault('system_ops', TestMockOps())
            kwargs.setdefault('home_dir', tmp_config_dir.parent / "home")
            original_init(self, config_dir=config_dir, **kwargs)

        monkeypatch.setattr(MigrationEngine, "__init__", patched_init)

        result = runner.invoke(app, ["migrate", "--diff"])
        assert result.exit_code == 0
        assert "diff mode" in result.stdout.lower()

    def test_migrate_reconvert(self, tmp_config_dir: Path, monkeypatch):
        self._write_v1_config(tmp_config_dir)

        class TestMockOps:
            def detect_os(self): return "almalinux"
            def stop_service(self, s): return True
            def start_service(self, s): return True
            def disable_service(self, s): return True
            def get_mariadb_version(self): return "10.11.8"
            def get_installed_php_versions(self): return ["8.2"]
            def get_v1_user_list(self): return ["alice"]

        from nopanel.migrate import MigrationEngine
        original_init = MigrationEngine.__init__
        def patched_init(self, config_dir=None, **kwargs):
            if config_dir is None:
                config_dir = tmp_config_dir
            kwargs.setdefault('system_ops', TestMockOps())
            kwargs.setdefault('home_dir', tmp_config_dir.parent / "home")
            original_init(self, config_dir=config_dir, **kwargs)

        monkeypatch.setattr(MigrationEngine, "__init__", patched_init)

        result = runner.invoke(app, ["migrate", "--reconvert"])
        assert result.exit_code == 0


class TestUserModFixes:
    """Tests for user mod --no-admin and field clearing (fix #5)."""

    def test_user_mod_no_admin(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123", "--admin"])
        result = runner.invoke(app, ["user", "mod", "--user", "alice", "--no-admin"])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.users.users["alice"].admin is False

    def test_user_mod_clear_fullname(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123", "--fullname", "Alice Smith"])
        result = runner.invoke(app, ["user", "mod", "--user", "alice", "--fullname", ""])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.users.users["alice"].fullname == ""

    def test_user_mod_clear_email(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123", "--email", "alice@test.com"])
        result = runner.invoke(app, ["user", "mod", "--user", "alice", "--email", ""])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.users.users["alice"].email == ""

    def test_user_mod_set_login_no(self, tmp_config_dir: Path):
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123", "--login", "ssh"])
        result = runner.invoke(app, ["user", "mod", "--user", "alice", "--login", "no"])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.users.users["alice"].login.value == "no"


class TestImportForceFlag:
    """Tests for import --force flag (fix #6)."""

    def test_import_without_force_fails_on_existing(self, tmp_config_dir: Path, tmp_path: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])

        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(FullConfig().model_dump(mode="json")))
        result = runner.invoke(app, ["import", "--file", str(export_file)])
        assert result.exit_code == 1
        assert "force" in result.stdout.lower()

    def test_import_with_force_overwrites(self, tmp_config_dir: Path, tmp_path: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])

        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(FullConfig().model_dump(mode="json")))
        result = runner.invoke(app, ["import", "--file", str(export_file), "--force"])
        assert result.exit_code == 0


class TestDomainValidation:
    """Tests for domain add validation (fixes #17, #18)."""

    def test_domain_add_nonexistent_user(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "domain", "add",
            "--domain", "example.com",
            "--user", "nobody",
        ])
        assert result.exit_code == 1
        assert "exist" in result.stdout.lower()

    def test_domain_add_invalid_php_version(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, [
            "domain", "add",
            "--domain", "example.com",
            "--user", "alice",
            "--php", "5.6",
        ])
        assert result.exit_code == 1
        assert "not configured" in result.stdout.lower()

    def test_domain_mod_invalid_php_version(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, ["domain", "add", "--domain", "example.com", "--user", "alice"])
        result = runner.invoke(app, [
            "domain", "mod",
            "--domain", "example.com",
            "--php", "5.6",
        ])
        assert result.exit_code == 1
        assert "not configured" in result.stdout.lower()


class TestDomainModClearAliases:
    """Tests for domain mod --aliases "" clearing aliases (fix #6)."""

    def test_domain_mod_clear_aliases(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, [
            "domain", "add", "--domain", "example.com", "--user", "alice",
            "--aliases", "www.example.com,test.example.com",
        ])
        config = load_config(tmp_config_dir)
        assert len(config.domains.domains["example.com"].aliases) == 2

        result = runner.invoke(app, [
            "domain", "mod", "--domain", "example.com", "--aliases", "",
        ])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.domains.domains["example.com"].aliases == []

    def test_domain_mod_no_aliases_flag_leaves_unchanged(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        runner.invoke(app, [
            "domain", "add", "--domain", "example.com", "--user", "alice",
            "--aliases", "www.example.com",
        ])
        # Mod something else without --aliases flag
        result = runner.invoke(app, [
            "domain", "mod", "--domain", "example.com", "--ssl", "auto",
        ])
        assert result.exit_code == 0
        config = load_config(tmp_config_dir)
        assert config.domains.domains["example.com"].aliases == ["www.example.com"]


class TestImportInvalidJson:
    """Tests for import with invalid JSON (fix #8)."""

    def test_import_invalid_json(self, tmp_config_dir: Path, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json")
        result = runner.invoke(app, ["import", "--file", str(bad_file)])
        assert result.exit_code == 1
        assert "invalid json" in result.stdout.lower()


class TestImportClearsCommittedState:
    """Tests for import clearing committed state (fix #7)."""

    def test_import_clears_committed(self, tmp_config_dir: Path, tmp_path: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])

        # Export
        export_file = tmp_path / "export.json"
        runner.invoke(app, ["export", "--output", str(export_file)])

        # Import with --force should also sync committed state
        result = runner.invoke(app, ["import", "--file", str(export_file), "--force"])
        assert result.exit_code == 0

        # Import no longer saves committed state — user must run 'nopanel commit'
        from nopanel.state import load_committed
        committed = load_committed(tmp_config_dir)
        assert "alice" not in committed.users.users


class TestStatusServiceCount:
    """Test status command service count (fix #11)."""

    def test_status_service_count_with_php(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        # init creates 4 PHP versions + 3 non-PHP services = 7
        assert "7" in result.stdout


class TestCommitNoDocker:
    """Test commit --no-docker flag (fix #5)."""

    def test_commit_no_docker(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["user", "add", "--user", "alice", "--password", "password123"])
        result = runner.invoke(app, ["commit", "--no-docker", "--dry-run"])
        assert result.exit_code == 0


class TestDatabaseAddUserValidation:
    """Database add must reject non-existent owning user."""

    def test_database_add_nonexistent_user(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "database", "add",
            "--user", "ghost",
            "--db", "blog",
            "--password", "pass12345",
        ])
        assert result.exit_code == 1
        assert "User does not exist" in result.stdout


class TestPhpModuleValidation:
    """PHP module add/remove must validate module name and PHP version."""

    def test_add_module_invalid_name(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "php", "add-module",
            "--version", "8.2",
            "xdebug && rm -rf /",
        ])
        assert result.exit_code == 1
        assert "Invalid module name" in result.stdout

    def test_add_module_nonexistent_version(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "php", "add-module",
            "--version", "99.0",
            "xdebug",
        ])
        assert result.exit_code == 1
        assert "not configured" in result.stdout

    def test_remove_module_invalid_name(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "php", "remove-module",
            "--version", "8.2",
            "evil;cmd",
        ])
        assert result.exit_code == 1
        assert "Invalid module name" in result.stdout

    def test_remove_module_nonexistent_version(self, tmp_config_dir: Path):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, [
            "php", "remove-module",
            "--version", "99.0",
            "xdebug",
        ])
        assert result.exit_code == 1
        assert "not configured" in result.stdout
