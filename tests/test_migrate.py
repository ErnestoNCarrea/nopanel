"""Tests for nopanel.migrate — v1 to v2 migration engine."""

import json
from pathlib import Path
from typing import Any

import pytest

from nopanel.migrate import (
    RHEL_VARIANTS,
    MigrationEngine,
    is_rhel_based,
)


class MockSystemOps:
    """Mock system operations for testing."""

    def __init__(
        self,
        os_id: str = "almalinux",
        mariadb_version: str = "10.11.8",
        php_versions: list[str] | None = None,
        v1_users: dict[str, Any] | None = None,
    ):
        self._os_id = os_id
        self._mariadb_version = mariadb_version
        self._php_versions = php_versions or ["8.2", "8.3"]
        self._v1_users = v1_users or {}
        self.stopped_services: list[str] = []
        self.disabled_services: list[str] = []

    def detect_os(self) -> str:
        return self._os_id

    def stop_service(self, service: str) -> bool:
        self.stopped_services.append(service)
        return True

    def start_service(self, service: str) -> bool:
        return True

    def disable_service(self, service: str) -> bool:
        self.disabled_services.append(service)
        return True

    def get_mariadb_version(self) -> str | None:
        return self._mariadb_version

    def get_installed_php_versions(self) -> list[str]:
        return self._php_versions

    def get_v1_user_list(self) -> list[str]:
        return list(self._v1_users.keys())


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "nopanel"
    d.mkdir()
    return d


@pytest.fixture
def tmp_home_dir(tmp_path: Path) -> Path:
    d = tmp_path / "home"
    d.mkdir()
    return d


def write_v1_config(config_dir: Path, nopanel_data: dict | None = None, users_data: dict | None = None, modules_data: dict | None = None):
    """Write v1 JSON config files."""
    if nopanel_data is not None:
        (config_dir / "nopanel.json").write_text(json.dumps(nopanel_data))
    if users_data is not None:
        (config_dir / "users.json").write_text(json.dumps(users_data))
    if modules_data is not None:
        (config_dir / "modules.json").write_text(json.dumps(modules_data))


def write_v1_user_data(home_dir: Path, username: str, domains: dict | None = None, databases: dict | None = None):
    """Write v1 per-user JSON config files."""
    user_nopanel = home_dir / username / ".nopanel"
    user_nopanel.mkdir(parents=True)
    if domains is not None:
        (user_nopanel / "domains.json").write_text(json.dumps(domains))
    if databases is not None:
        (user_nopanel / "databases.json").write_text(json.dumps(databases))


class TestOSDetection:
    def test_rhel_variants(self):
        for os_id in RHEL_VARIANTS:
            assert is_rhel_based(os_id)

    def test_non_rhel(self):
        assert not is_rhel_based("debian")
        assert not is_rhel_based("ubuntu")
        assert not is_rhel_based("unknown")


class TestPreMigrationCheck:
    def test_rhel_detected(self, tmp_config_dir: Path):
        write_v1_config(tmp_config_dir, nopanel_data={"version": "1"})
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            system_ops=MockSystemOps(os_id="almalinux"),
        )
        result = engine.pre_migration_check()
        assert result.is_rhel
        assert result.v1_detected
        assert len(result.errors) == 0

    def test_non_rhel_aborts(self, tmp_config_dir: Path):
        write_v1_config(tmp_config_dir, nopanel_data={"version": "1"})
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            system_ops=MockSystemOps(os_id="ubuntu"),
        )
        result = engine.pre_migration_check()
        assert not result.is_rhel
        assert any("RHEL" in err for err in result.errors)

    def test_v1_not_found(self, tmp_config_dir: Path):
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            system_ops=MockSystemOps(os_id="almalinux"),
        )
        result = engine.pre_migration_check()
        assert any("v1" in err.lower() for err in result.errors)


class TestConfigConversion:
    def test_convert_full_config(self, tmp_config_dir: Path, tmp_home_dir: Path):
        # Write v1 configs
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1", "auto_elevate": "true"},
            users_data={
                "alice": {
                    "name": "alice",
                    "fullname": "Alice Smith",
                    "email": "alice@example.com",
                    "login": "ssh",
                    "admin": "true",
                    "password": "",
                }
            },
            modules_data={
                "mariadb": {"installed": "true", "password": "rootpass"},
                "php-fpm": {"8.2": "true"},
                "valkey": {"installed": "true"},
            },
        )
        write_v1_user_data(
            tmp_home_dir, "alice",
            domains={
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                    "web_ssl": "le",
                    "web_aliases": "www.example.com",
                }
            },
            databases={
                "alice_blog": {
                    "name": "alice_blog",
                    "dbuser": "alice_blog",
                    "password": "pass12345",
                }
            },
        )

        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        config = engine.convert_configs()

        assert "alice" in config.users.users
        assert config.users.users["alice"].fullname == "Alice Smith"
        assert config.users.users["alice"].login.value == "ssh"

        assert "example.com" in config.domains.domains
        assert config.domains.domains["example.com"].user == "alice"
        assert config.domains.domains["example.com"].php_version == "8.2"

        assert "alice_blog" in config.databases.databases
        assert config.databases.databases["alice_blog"].password == "pass12345"

        assert "8.2" in config.services.php
        assert config.services.mariadb.root_password == "rootpass"

    def test_mariadb_image_tag_10x(self, tmp_config_dir: Path, tmp_home_dir: Path):
        """MariaDB 10.x should map to mariadb:10.XX image tag."""
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(mariadb_version="10.11.8"),
        )
        config = engine.convert_configs()
        assert config.services.mariadb.image == "mariadb:10.11"

    def test_mariadb_image_tag_11x(self, tmp_config_dir: Path, tmp_home_dir: Path):
        """MariaDB 11.x should map to mariadb:11.X image tag (fix #9)."""
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(mariadb_version="11.4.2"),
        )
        config = engine.convert_configs()
        assert config.services.mariadb.image == "mariadb:11.4"

    def test_mariadb_version_from_services_yml(self, tmp_config_dir: Path):
        """get_mariadb_version should read the image tag from v2 services.yml first."""
        import yaml
        from nopanel.migrate import RealSystemOps

        (tmp_config_dir / "services.yml").write_text(
            yaml.dump({"mariadb": {"image": "mariadb:10.11", "port": 3306}})
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        assert result == "10.11"

    def test_mariadb_version_from_compose_yml(self, tmp_config_dir: Path):
        """Fall back to generated docker-compose.yml when services.yml has no image."""
        import yaml
        from nopanel.migrate import RealSystemOps

        gen_dir = tmp_config_dir / "generated"
        gen_dir.mkdir()
        (gen_dir / "docker-compose.yml").write_text(
            yaml.dump({"services": {"mariadb": {"image": "mariadb:11.4"}}})
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        assert result == "11.4"

    def test_mariadb_version_from_docker_inspect(self, tmp_config_dir: Path, monkeypatch):
        """Fall back to docker inspect when no v2 config files exist."""
        from nopanel.migrate import RealSystemOps

        class InspectResult:
            returncode = 0
            stdout = "mariadb:10.11\n"
            stderr = ""

        class RPMResult:
            returncode = 1
            stdout = ""
            stderr = "not installed"

        def mock_run(cmd, **kw):
            if "inspect" in cmd:
                return InspectResult()
            return RPMResult()

        monkeypatch.setattr(
            "nopanel.migrate.subprocess.run",
            mock_run,
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        assert result == "10.11"

    def test_mariadb_version_from_rpm_fallback(self, tmp_config_dir: Path, monkeypatch):
        """Last resort: RPM query when no v2 sources are available (initial migration)."""
        from nopanel.migrate import RealSystemOps

        class RPMResult:
            returncode = 0
            stdout = "10.11.8\n"
            stderr = ""

        class InspectResult:
            returncode = 1
            stdout = ""
            stderr = "No such container"

        def mock_run(cmd, **kw):
            if "inspect" in cmd:
                return InspectResult()
            return RPMResult()

        monkeypatch.setattr(
            "nopanel.migrate.subprocess.run",
            mock_run,
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        assert result == "10.11.8"

    def test_mariadb_version_lts_tag_returns_none(self, tmp_config_dir: Path):
        """Non-numeric image tags like 'lts' should return None."""
        import yaml
        from nopanel.migrate import RealSystemOps

        (tmp_config_dir / "services.yml").write_text(
            yaml.dump({"mariadb": {"image": "mariadb:lts"}})
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        assert result is None

    def test_mariadb_version_parsing_empty_string(self, tmp_config_dir: Path, monkeypatch):
        """Version parsing should not raise IndexError on empty strings (fix #8)."""
        from nopanel.migrate import RealSystemOps

        class InspectResult:
            returncode = 1
            stdout = ""
            stderr = "No such container"

        class RPMResult:
            returncode = 1
            stdout = ""
            stderr = "not installed"

        monkeypatch.setattr(
            "nopanel.migrate.subprocess.run",
            lambda *a, **kw: InspectResult() if "inspect" in a[0] else RPMResult(),
        )
        ops = RealSystemOps(config_dir=tmp_config_dir)
        result = ops.get_mariadb_version()
        # Should not raise; either returns a version or None
        assert result is None or isinstance(result, str)


class TestMigrationRun:
    def test_dry_run(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice", "fullname": "Alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )

        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run(dry_run=True)
        assert result.dry_run
        assert result.success
        assert result.converted_config is not None
        assert "alice" in result.converted_config.users.users

    def test_non_rhel_aborts(self, tmp_config_dir: Path):
        write_v1_config(tmp_config_dir, nopanel_data={"version": "1"})
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            system_ops=MockSystemOps(os_id="debian"),
        )
        result = engine.run()
        assert not result.success
        assert any("RHEL" in err for err in result.errors)

    def test_service_migration_order(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "valkey": {"installed": "true"},
            },
        )

        mock_ops = MockSystemOps()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
        )
        result = engine.run()
        assert result.success
        # Valkey should be stopped before mariadb (migration order)
        assert mock_ops.stopped_services[0] == "valkey"
        assert mock_ops.stopped_services[1] == "mariadb"


class MockDockerManager:
    """Mock Docker manager for testing."""

    def __init__(self) -> None:
        self.pulled = False
        self.started_services: list[str] = []
        self.stopped_services: list[str] = []

    def compose_up(self, services: list[str] | None = None, detach: bool = True):
        if services:
            self.started_services.extend(services)
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_down(self):
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_stop(self, services: list[str] | None = None):
        if services:
            self.stopped_services.extend(services)
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_restart(self, services: list[str] | None = None):
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_pull(self, services: list[str] | None = None):
        self.pulled = True
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def build_image(self, dockerfile_dir: Path, tag: str, dockerfile: str = "Dockerfile"):
        from nopanel.docker_manager import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="")

    def get_container_status(self, service: str):
        return None

    def is_service_running(self, service: str):
        return False

    def list_running_services(self):
        return []


class MockFileWriter:
    """Mock file writer for testing."""

    def __init__(self) -> None:
        self.written: dict[str, str] = {}

    def write(self, path: str, content: str) -> None:
        self.written[path] = content


class TestServiceMigration:
    def test_migrate_single_service(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "valkey": {"installed": "true"},
            },
        )
        mock_ops = MockSystemOps()
        mock_docker = MockDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
            docker_manager=mock_docker,
        )
        result = engine.run(service="valkey")
        assert result.success
        assert len(result.step_results) == 1
        assert result.step_results[0].service == "valkey"
        assert "valkey" in mock_ops.stopped_services
        assert "valkey" in mock_docker.started_services
        # Only valkey should be migrated, not mariadb
        assert "mariadb" not in mock_ops.stopped_services

    def test_migrate_single_service_php(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "php-fpm": {"8.2": "true", "8.3": "true"},
            },
        )
        mock_ops = MockSystemOps(php_versions=["8.2", "8.3"])
        mock_docker = MockDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
            docker_manager=mock_docker,
        )
        result = engine.run(service="php")
        assert result.success
        assert result.step_results[0].service == "php"
        # Both PHP versions should be stopped
        assert "php82-php-fpm" in mock_ops.stopped_services
        assert "php83-php-fpm" in mock_ops.stopped_services

    def test_migrate_all_services(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "valkey": {"installed": "true"},
            },
        )
        mock_ops = MockSystemOps()
        mock_docker = MockDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
            docker_manager=mock_docker,
        )
        result = engine.run(all_services=True)
        assert result.success
        # All services should be migrated in order
        assert "valkey" in mock_ops.stopped_services
        assert "mariadb" in mock_ops.stopped_services
        assert "httpd" in mock_ops.stopped_services

    def test_migrate_service_failure_stops_chain(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "valkey": {"installed": "true"},
            },
        )

        class FailingOps(MockSystemOps):
            def stop_service(self, service: str) -> bool:
                if service == "mariadb":
                    return False
                return super().stop_service(service)

        mock_ops = FailingOps()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
        )
        result = engine.run()
        assert not result.success
        # Valkey should have been migrated, but not apache (chain stopped at mariadb)
        assert "valkey" in mock_ops.stopped_services
        assert "httpd" not in mock_ops.stopped_services


class TestReconvert:
    def test_reconvert_saves_config(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice", "fullname": "Alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run(reconvert=True)
        assert result.success
        assert result.converted_config is not None
        # v2 YAML should be saved
        assert (tmp_config_dir / "nopanel.yml").exists()
        assert (tmp_config_dir / "users.yml").exists()

    def test_reconvert_dry_run(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run(reconvert=True, dry_run=True)
        assert result.dry_run
        # Should not save anything
        assert not (tmp_config_dir / "nopanel.yml").exists()

    def test_reconvert_no_service_cutover(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        mock_ops = MockSystemOps()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
        )
        result = engine.run(reconvert=True)
        assert result.success
        # No services should be stopped during reconvert
        assert len(mock_ops.stopped_services) == 0
        assert len(result.step_results) == 0


class TestDiffMode:
    def test_diff_returns_config_without_changes(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        mock_ops = MockSystemOps()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=mock_ops,
        )
        result = engine.run(diff=True)
        assert result.dry_run
        assert result.converted_config is not None
        # No services should be stopped
        assert len(mock_ops.stopped_services) == 0
        # No YAML should be saved
        assert not (tmp_config_dir / "nopanel.yml").exists()


class TestImagePull:
    def test_images_pulled_during_migration(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "valkey": {"installed": "true"},
            },
        )
        mock_docker = MockDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
            docker_manager=mock_docker,
        )
        result = engine.run()
        assert result.success
        assert mock_docker.pulled

    def test_no_pull_without_docker(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        # Should not raise even without docker
        result = engine.run()
        assert result.success


class TestConfigGeneration:
    def test_configs_generated_during_migration(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice", "fullname": "Alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "php-fpm": {"8.2": "true"},
                "valkey": {"installed": "true"},
            },
        )
        write_v1_user_data(
            tmp_home_dir, "alice",
            domains={
                "example.com": {
                    "name": "example.com",
                    "user": "alice",
                    "web": "true",
                    "web_php": "8.2",
                    "web_ssl": "le",
                }
            },
        )
        mock_writer = MockFileWriter()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
            file_writer=mock_writer,
        )
        result = engine.run()
        assert result.success
        # docker-compose.yml should be generated
        assert "docker-compose.yml" in mock_writer.written
        # Apache vhost should be generated
        assert "apache/httpd.conf" in mock_writer.written
        assert "apache/domains/example.com.http.conf" in mock_writer.written
        # PHP-FPM pool should be generated
        assert any("php-fpm" in k for k in mock_writer.written)
        # PHP Dockerfile should be generated
        assert any("docker/php-" in k for k in mock_writer.written)


class TestPostMigrationCleanup:
    def test_v1_configs_backed_up(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run()
        assert result.success
        # v1 files should be backed up
        assert (tmp_config_dir / "nopanel.json.v1.bak").exists()
        assert (tmp_config_dir / "users.json.v1.bak").exists()
        assert (tmp_config_dir / "modules.json.v1.bak").exists()

    def test_no_backup_on_failure(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )

        class FailingOps(MockSystemOps):
            def stop_service(self, service: str) -> bool:
                return False

        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=FailingOps(),
        )
        result = engine.run()
        assert not result.success
        # No backups should be created on failure
        assert not (tmp_config_dir / "nopanel.json.v1.bak").exists()

    def test_backup_filename_correct(self, tmp_config_dir: Path, tmp_home_dir: Path):
        """Backup files should have .v1.bak suffix (fix #4 — Python 3.11 compat)."""
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run()
        assert result.success
        # Verify exact backup filenames (not broken by with_suffix compound issue)
        assert (tmp_config_dir / "nopanel.json.v1.bak").exists()
        assert (tmp_config_dir / "users.json.v1.bak").exists()
        assert (tmp_config_dir / "modules.json.v1.bak").exists()
        # Original files should be removed after backup
        assert not (tmp_config_dir / "nopanel.json").exists()

    def test_all_v1_files_removed_after_cleanup(self, tmp_config_dir: Path, tmp_home_dir: Path):
        """All v1 JSON files should be removed after migration cleanup."""
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={"mariadb": {"installed": "true", "password": ""}},
        )
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
        )
        result = engine.run()
        assert result.success
        assert not (tmp_config_dir / "nopanel.json").exists()
        assert not (tmp_config_dir / "users.json").exists()
        assert not (tmp_config_dir / "modules.json").exists()


class TestComposePullSkipsPhpImages:
    """Test that compose_pull skips custom PHP images during migration."""

    def test_pull_skips_php_services(self, tmp_config_dir: Path, tmp_home_dir: Path):
        """Migration should only pull non-PHP services (apache, mariadb, valkey)."""
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "php-fpm": {"8.2": "true", "8.3": "true"},
            },
        )

        class TrackingDockerManager:
            def __init__(self):
                self.pull_calls: list[list[str] | None] = []

            def compose_up(self, services=None, detach=True):
                from nopanel.docker_manager import CommandResult
                return CommandResult(returncode=0, stdout="", stderr="")

            def compose_pull(self, services=None):
                from nopanel.docker_manager import CommandResult
                self.pull_calls.append(services)
                return CommandResult(returncode=0, stdout="", stderr="")

        docker = TrackingDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
            docker_manager=docker,
        )
        result = engine.run()
        assert result.success
        assert len(docker.pull_calls) == 1
        pulled = docker.pull_calls[0]
        assert "apache" in pulled
        assert "mariadb" in pulled
        assert "valkey" in pulled
        assert not any(s.startswith("php") for s in pulled)


class TestMigrationBuildsPhpImages:
    """Fix #3: Migration must build custom PHP images, not just pull them."""

    def test_php_images_built_during_migration(self, tmp_config_dir: Path, tmp_home_dir: Path):
        write_v1_config(
            tmp_config_dir,
            nopanel_data={"version": "1"},
            users_data={"alice": {"name": "alice"}},
            modules_data={
                "mariadb": {"installed": "true", "password": ""},
                "php-fpm": {"8.2": "true", "8.3": "true"},
            },
        )

        class TrackingDockerManager:
            def __init__(self):
                self.pull_calls: list[list[str] | None] = []
                self.build_calls: list[str] = []

            def compose_up(self, services=None, detach=True):
                from nopanel.docker_manager import CommandResult
                return CommandResult(returncode=0, stdout="", stderr="")

            def compose_pull(self, services=None):
                from nopanel.docker_manager import CommandResult
                self.pull_calls.append(services)
                return CommandResult(returncode=0, stdout="", stderr="")

            def build_image(self, dockerfile_dir=None, tag=None):
                from nopanel.docker_manager import CommandResult
                self.build_calls.append(tag)
                return CommandResult(returncode=0, stdout="", stderr="")

        docker = TrackingDockerManager()
        engine = MigrationEngine(
            config_dir=tmp_config_dir,
            home_dir=tmp_home_dir,
            system_ops=MockSystemOps(),
            docker_manager=docker,
        )
        result = engine.run()
        assert result.success
        # PHP images should have been built
        assert any("nopanel/php-8.2" in t for t in docker.build_calls)
        assert any("nopanel/php-8.3" in t for t in docker.build_calls)
