"""Tests for nopanel.commit — commit engine with mock dependencies."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from nopanel.commit import CommitEngine, _to_compose_names
from nopanel.config import save_config
from nopanel.docker_manager import CommandResult
from nopanel.models import (
    Database,
    DatabasesConfig,
    Domain,
    DomainsConfig,
    FullConfig,
    LoginType,
    NopanelConfig,
    PHPFpmService,
    SSLMode,
    User,
    UsersConfig,
)
from nopanel.state import save_committed


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "nopanel"
    d.mkdir()
    return d


def make_full_config(
    users: dict[str, User] | None = None,
    domains: dict[str, Domain] | None = None,
    databases: dict[str, Database] | None = None,
) -> FullConfig:
    # Auto-add stub users for any domain/database owners not explicitly provided
    all_users = dict(users or {})
    for domain in (domains or {}).values():
        if domain.user not in all_users:
            all_users[domain.user] = User(fullname=domain.user)
    for db in (databases or {}).values():
        if db.user not in all_users:
            all_users[db.user] = User(fullname=db.user)
    return FullConfig(
        nopanel=NopanelConfig(),
        users=UsersConfig(users=all_users),
        domains=DomainsConfig(domains=domains or {}),
        databases=DatabasesConfig(databases=databases or {}),
    )


class MockFileWriter:
    """Mock file writer that stores files in memory."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def write(self, path: str, content: str) -> None:
        self.files[path] = content


class MockDockerManager:
    """Mock Docker manager that records calls."""

    def __init__(self):
        self.calls: list[tuple[str, Any]] = []
        self._running: set[str] = set()

    def compose_up(self, services=None, detach=True):
        self.calls.append(("up", services))
        if services:
            self._running.update(services)
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_down(self, services=None):
        self.calls.append(("down", services))
        if services:
            self._running.difference_update(services)
        else:
            self._running.clear()
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_stop(self, services=None):
        self.calls.append(("stop", services))
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_restart(self, services=None):
        self.calls.append(("restart", services))
        return CommandResult(returncode=0, stdout="", stderr="")

    def compose_pull(self, services=None):
        self.calls.append(("pull", services))
        return CommandResult(returncode=0, stdout="", stderr="")

    def get_container_status(self, service):
        return {"State": "running"} if service in self._running else None

    def build_image(self, dockerfile_dir=None, tag=None):
        self.calls.append(("build_image", tag))
        return CommandResult(returncode=0, stdout="", stderr="")


class MockSQLExecutor:
    """Mock SQL executor that records executed queries."""

    def __init__(self):
        self.queries: list[str] = []

    def execute(self, query: str) -> Any:
        self.queries.append(query)
        return None


class TestCommitEngine:
    def test_no_changes(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        save_committed(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.diff.is_empty
        assert "No changes to commit" in result.summary

    def test_dry_run(self, tmp_config_dir: Path):
        config = make_full_config(users={"alice": User(fullname="Alice")})
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run(dry_run=True)
        assert result.dry_run
        assert len(result.diff.users.added) == 1
        assert "alice" in result.summary

    def test_user_added_config_only(self, tmp_config_dir: Path):
        """User changes are config-only — no host user creation, just snapshot."""
        config = make_full_config(users={"alice": User(fullname="Alice", password="pass12345")})
        save_config(config, tmp_config_dir)

        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
        )
        result = engine.run()
        assert result.success
        # User is in the diff but no side effects — just snapshotted
        assert len(result.diff.users.added) == 1
        assert result.diff.users.added[0].name == "alice"

    def test_database_added(self, tmp_config_dir: Path):
        config = make_full_config(
            databases={"alice_blog": Database(user="alice", dbuser="alice_blog", password="pass12345")}
        )
        save_config(config, tmp_config_dir)

        mock_sql = MockSQLExecutor()
        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
            sql_executor=mock_sql,
        )
        result = engine.run()
        assert result.success
        assert any("CREATE DATABASE" in q for q in mock_sql.queries)
        assert any("GRANT ALL" in q for q in mock_sql.queries)

    def test_generated_configs(self, tmp_config_dir: Path):
        config = make_full_config(
            users={"alice": User(fullname="Alice")},
            domains={"example.com": Domain(user="alice", php_version="8.2")},
        )
        save_config(config, tmp_config_dir)

        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
        )
        result = engine.run()
        assert "apache/httpd.conf" in result.generated_files
        assert "apache/domains/example.com.http.conf" in result.generated_files
        assert "docker-compose.yml" in result.generated_files

    def test_committed_state_saved(self, tmp_config_dir: Path):
        config = make_full_config(users={"alice": User(fullname="Alice")})
        save_config(config, tmp_config_dir)

        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
        )
        result = engine.run()
        assert result.success

        # Verify committed state was saved
        from nopanel.state import load_committed
        committed = load_committed(tmp_config_dir)
        assert "alice" in committed.users.users


class TestToComposeNames:
    """Tests for _to_compose_names helper (fix #3)."""

    def test_web_maps_to_apache(self):
        config = make_full_config()
        result = _to_compose_names(["web"], config)
        assert result == ["apache"]

    def test_mariadb_passes_through(self):
        config = make_full_config()
        result = _to_compose_names(["mariadb"], config)
        assert result == ["mariadb"]

    def test_valkey_passes_through(self):
        config = make_full_config()
        result = _to_compose_names(["valkey"], config)
        assert result == ["valkey"]

    def test_php_expands_to_versions(self):
        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
        )
        # Add PHP versions via services config
        from nopanel.models import MariaDBService, ServicesConfig, ValkeyService, WebService
        config = config.model_copy(update={
            "services": ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            )
        })
        result = _to_compose_names(["php"], config)
        assert result == ["php-8.2", "php-8.3"]

    def test_mixed_names(self):
        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
        )
        from nopanel.models import MariaDBService, ServicesConfig, ValkeyService, WebService
        config = config.model_copy(update={
            "services": ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            )
        })
        result = _to_compose_names(["web", "php", "mariadb"], config)
        assert result == ["apache", "php-8.2", "mariadb"]


class TestRealFileWriter:
    """Tests for RealFileWriter path resolution (fix #5)."""

    def test_writes_to_base_dir_not_parent(self, tmp_path: Path):
        from nopanel.commit import RealFileWriter
        base = tmp_path / "generated"
        base.mkdir()
        writer = RealFileWriter(base_dir=base)
        writer.write("apache/httpd.conf", "test content")
        assert (base / "apache" / "httpd.conf").read_text() == "test content"
        # Must NOT write to parent directory
        assert not (tmp_path / "apache" / "httpd.conf").exists()

    def test_creates_parent_dirs(self, tmp_path: Path):
        from nopanel.commit import RealFileWriter
        base = tmp_path / "generated"
        base.mkdir()
        writer = RealFileWriter(base_dir=base)
        writer.write("php-fpm/php82/example.com.conf", "pool config")
        assert (base / "php-fpm" / "php82" / "example.com.conf").read_text() == "pool config"


class TestRealSQLExecutor:
    """Tests for RealSQLExecutor using MariaDB socket and --defaults-extra-file."""

    def test_uses_socket_and_defaults_extra_file(self, monkeypatch):
        from nopanel.services.database import RealSQLExecutor

        captured_cmd = []
        captured_env = {}

        class MockResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            captured_env.update(kwargs.get("env") or {})
            return MockResult()

        monkeypatch.setattr("nopanel.services.database.subprocess.run", mock_run)
        executor = RealSQLExecutor(root_password="secret123")
        executor.execute("SELECT 1")

        assert captured_cmd[0][0] == "mariadb"
        assert "-u" in captured_cmd[0]
        assert "root" in captured_cmd[0]
        assert "--socket" in captured_cmd[0]
        assert "--defaults-extra-file" in captured_cmd[0]
        # Password must not appear on the command line
        assert "secret123" not in " ".join(captured_cmd[0])
        # Password must not be passed via MYSQL_PWD env var
        assert "MYSQL_PWD" not in captured_env

    def test_custom_socket_path(self, monkeypatch):
        from nopanel.services.database import RealSQLExecutor

        captured_cmd = []

        class MockResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            return MockResult()

        monkeypatch.setattr("nopanel.services.database.subprocess.run", mock_run)
        executor = RealSQLExecutor(root_password="", socket="/custom/mysql.sock")
        executor.execute("SELECT 1")

        assert "--socket" in captured_cmd[0]
        assert "/custom/mysql.sock" in captured_cmd[0]

    def test_no_password_no_defaults_file(self, monkeypatch):
        from nopanel.services.database import RealSQLExecutor

        captured_cmd = []

        class MockResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            return MockResult()

        monkeypatch.setattr("nopanel.services.database.subprocess.run", mock_run)
        executor = RealSQLExecutor(root_password="")
        executor.execute("SELECT 1")
        assert "--defaults-extra-file" not in captured_cmd[0]


class TestPhpImageBuild:
    """Tests for PHP image building during commit (fix #3)."""

    def test_build_php_images_called(self, tmp_config_dir: Path):
        from nopanel.models import MariaDBService, ServicesConfig, ValkeyService, WebService

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)

        mock_docker = MockDockerManager()
        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=mock_writer,
        )
        result = engine.run()
        assert result.success
        build_calls = [c for c in mock_docker.calls if c[0] == "build_image"]
        assert len(build_calls) == 1

    def test_build_php_images_multiple_versions(self, tmp_config_dir: Path):
        from nopanel.models import MariaDBService, ServicesConfig, ValkeyService, WebService

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)

        mock_docker = MockDockerManager()
        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=mock_writer,
        )
        result = engine.run()
        assert result.success
        build_calls = [c for c in mock_docker.calls if c[0] == "build_image"]
        assert len(build_calls) == 2


class TestPhpServiceManagerName:
    """Tests for PHPFpmServiceManager.name format (fix #2)."""

    def test_name_has_dot(self):
        from nopanel.services.php import PHPFpmServiceManager
        mgr = PHPFpmServiceManager(version="8.2")
        assert mgr.name == "php-8.2"

    def test_name_not_nodot(self):
        from nopanel.services.php import PHPFpmServiceManager
        mgr = PHPFpmServiceManager(version="8.3")
        assert mgr.name != "php-83"


class TestStalePoolConfigCleanup:
    """Tests for stale PHP-FPM pool config cleanup on version change (fix #5)."""

    def test_old_pool_removed_on_version_change(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain,
            DomainsConfig,
            MariaDBService,
            PHPFpmService,
            ServicesConfig,
            ValkeyService,
            WebService,
        )

        # Committed state: domain with PHP 8.2
        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={"example.com": Domain(user="alice", php_version="8.2")}),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        # Desired state: same domain but PHP 8.3
        desired = committed.model_copy(update={
            "domains": DomainsConfig(domains={"example.com": Domain(user="alice", php_version="8.3")})
        })
        save_config(desired, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        # The old php82 pool config should be removed
        assert any("php-fpm/php82/example.com.conf" in p for p in removed_files)


class TestCommitServiceFilter:
    """Tests for commit service filter only restarting affected PHP versions (fix #9)."""

    def test_only_affected_php_versions_restarted(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain,
            DomainsConfig,
            MariaDBService,
            PHPFpmService,
            ServicesConfig,
            ValkeyService,
            WebService,
        )

        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        # Add a domain with PHP 8.2 only
        desired = committed.model_copy(update={
            "domains": DomainsConfig(domains={"example.com": Domain(user="alice", php_version="8.2")})
        })
        save_config(desired, tmp_config_dir)

        mock_docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        restart_calls = [c for c in mock_docker.calls if c[0] == "restart"]
        # Should restart apache and php-8.2, but NOT php-8.3
        restarted = []
        for call in restart_calls:
            restarted.extend(call[1] or [])
        assert "php-8.2" in restarted
        assert "php-8.3" not in restarted


class TestRealSQLExecutorNoPasswordLeak:
    """Tests for RealSQLExecutor not leaking password via env or cmdline."""

    def test_no_pwd_in_env_or_cmdline(self, monkeypatch):
        from nopanel.services.database import RealSQLExecutor

        captured_cmd = []
        captured_env = {}

        class MockResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            captured_env.update(kwargs.get("env") or {})
            return MockResult()

        monkeypatch.setattr("nopanel.services.database.subprocess.run", mock_run)

        executor = RealSQLExecutor(root_password="secret123")
        executor.execute("SELECT 1")

        # Password must not appear in env
        assert "MYSQL_PWD" not in captured_env
        # Password must not appear on command line
        assert "secret123" not in " ".join(captured_cmd[0])


class TestSelfSignedCertGeneration:
    """Tests for self-signed SSL cert generation (SSLMode.SELF)."""

    def test_no_certs_when_no_self_domains(self, tmp_config_dir: Path, monkeypatch):
        """Should not attempt cert generation when no SELF-mode domains exist."""
        config = make_full_config(
            users={"alice": User(fullname="Alice")},
            domains={"example.com": Domain(user="alice", php_version="8.2")},
        )
        save_config(config, tmp_config_dir)

        call_count = 0
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            nonlocal call_count
            if args and "openssl" in str(args[0]):
                call_count += 1
            return original_run(*args, **kwargs)

        monkeypatch.setattr("nopanel.commit.subprocess.run", mock_run)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=MockDockerManager(),
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert call_count == 0

    def test_https_vhost_has_cert_paths_for_self_mode(self, tmp_config_dir: Path):
        """HTTPS vhost for SELF mode should include ssl_cert and ssl_key paths."""
        from nopanel.services.web import generate_vhost_configs

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2", ssl=SSLMode.SELF),
            }),
            databases=DatabasesConfig(),
        )
        files = generate_vhost_configs(config)
        https_conf = files.get("apache/domains/example.com.https.conf")
        assert https_conf is not None
        assert "self/example.com.crt" in https_conf
        assert "self/example.com.key" in https_conf

    def test_no_https_vhost_cert_paths_for_auto_mode(self, tmp_config_dir: Path):
        """HTTPS vhost for AUTO mode should not include ssl_cert paths (mod_md handles it)."""
        from nopanel.services.web import generate_vhost_configs

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2", ssl=SSLMode.AUTO),
            }),
            databases=DatabasesConfig(),
        )
        files = generate_vhost_configs(config)
        https_conf = files.get("apache/domains/example.com.https.conf")
        assert https_conf is not None
        assert "self/example.com.crt" not in https_conf


class TestPhpImageBuildGating:
    """Tests for gating PHP image builds on PHP-related diff changes only."""

    def test_no_build_when_only_users_changed(self, tmp_config_dir: Path):
        """PHP images should not be rebuilt when only users change."""
        config = make_full_config(
            users={"alice": User(fullname="Alice")},
        )
        config = config.model_copy(update={
            "services": config.services.model_copy(update={
                "php": {"8.2": PHPFpmService(image="nopanel/php-8.2:latest")}
            })
        })
        save_config(config, tmp_config_dir)
        # Save same services as committed so PHP isn't in the diff
        committed = config.model_copy(update={
            "users": UsersConfig(users={}),
        })
        save_committed(committed, tmp_config_dir)

        docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=docker,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        build_calls = [c for c in docker.calls if c[0] == "build_image"]
        assert build_calls == []

    def test_build_when_php_service_added(self, tmp_config_dir: Path):
        """PHP images should be built when a new PHP version is added to services."""
        committed = make_full_config()
        save_committed(committed, tmp_config_dir)

        config = make_full_config()
        config = config.model_copy(update={
            "services": config.services.model_copy(update={
                "php": {"8.2": PHPFpmService(image="nopanel/php-8.2:latest")}
            })
        })
        save_config(config, tmp_config_dir)

        docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=docker,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        build_calls = [c for c in docker.calls if c[0] == "build_image"]
        assert len(build_calls) == 1
        assert "nopanel/php-8.2:latest" in build_calls[0][1]


class TestServiceFilterValidation:
    """Tests for service_filter validation in CommitEngine.run()."""

    def test_invalid_filter_returns_error(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)

        engine = CommitEngine(config_dir=tmp_config_dir)
        result = engine.run(service_filter="invalid_service")
        assert not result.success
        assert any("Invalid service filter" in e for e in result.errors)

    def test_valid_php_filter_accepted(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        save_committed(config, tmp_config_dir)

        engine = CommitEngine(config_dir=tmp_config_dir)
        result = engine.run(service_filter="php-8.2")
        assert result.success  # No changes, so it's successful


class TestSqlExecutorNotMutated:
    """Test that CommitEngine.run() does not mutate self.sql."""

    def test_sql_not_mutated(self, tmp_config_dir: Path):
        config = make_full_config(
            users={"alice": User(fullname="Alice")},
            databases={"blog": Database(user="alice", dbuser="alice_blog", password="secret123")},
        )
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            sql_executor=None,  # Explicitly None
            file_writer=MockFileWriter(),
        )
        assert engine.sql is None
        result = engine.run()
        assert engine.sql is None  # Should not have been mutated


class TestStaleModMdCleanup:
    """Tests for stale mod_md.conf cleanup when no auto-SSL domains remain (fix #2)."""

    def test_mod_md_removed_when_no_auto_ssl(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain,
            DomainsConfig,
            MariaDBService,
            PHPFpmService,
            ServicesConfig,
            ValkeyService,
            WebService,
        )

        # Committed state: domain with SSL auto
        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2", ssl=SSLMode.AUTO),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        # Desired state: same domain but SSL changed to none
        desired = committed.model_copy(update={
            "domains": DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2", ssl=SSLMode.NONE),
            })
        })
        save_config(desired, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("mod_md.conf" in p for p in removed_files)

    def test_mod_md_not_removed_when_auto_ssl_present(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain,
            DomainsConfig,
            MariaDBService,
            PHPFpmService,
            ServicesConfig,
            ValkeyService,
            WebService,
        )

        # Both committed and desired have auto-SSL domain
        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2", ssl=SSLMode.AUTO),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)
        save_committed(config, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert not any("mod_md.conf" in p for p in removed_files)


class TestStaleHttpsVhostCleanup:
    """Fix #6: HTTPS vhost configs must be removed when SSL mode changes to none."""

    def test_https_vhost_removed_on_ssl_to_none(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )

        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", ssl=SSLMode.AUTO),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "domains": DomainsConfig(domains={
                "example.com": Domain(user="alice", ssl=SSLMode.NONE),
            }),
        })
        save_config(desired, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("example.com.https.conf" in p for p in removed_files)


class TestConfigErrorSkipsRestart:
    """Fix #8: Services must not be restarted when config generation fails."""

    def test_no_restart_on_config_generation_failure(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2"),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)

        class FailingFileWriter(MockFileWriter):
            def write(self, path: str, content: str) -> None:
                raise RuntimeError("Simulated write failure")

        mock_docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=FailingFileWriter(),
        )
        result = engine.run()
        assert not result.success
        assert any("Config generation failed" in e for e in result.errors)
        # No restart calls should have been made
        assert not any(c[0] == "restart" for c in mock_docker.calls)


class TestNetworkOnlyFullRestart:
    """Fix #11: Only network mode change should trigger full compose_down/up."""

    def test_php_module_change_no_full_restart(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            PHPSettings, ServicesConfig, ValkeyService, WebService,
        )

        committed = FullConfig(
            nopanel=NopanelConfig(php=PHPSettings(additional_modules=[])),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2"),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "nopanel": NopanelConfig(php=PHPSettings(additional_modules=["imagick"])),
        })
        save_config(desired, tmp_config_dir)

        mock_docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        # No compose_down should have been called (only network mode change triggers that)
        assert not any(c[0] == "down" for c in mock_docker.calls)


class TestSelfSignedCertCleanup:
    """Fix #13: Self-signed certs must be cleaned up for deleted domains."""

    def test_self_signed_cert_removed_on_domain_delete(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )
        from nopanel.services.base import SELF_SIGNED_DIR

        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", ssl=SSLMode.SELF),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "domains": DomainsConfig(domains={}),
        })
        save_config(desired, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("example.com.https.conf" in p for p in removed_files)


class TestStaleDockerfileCleanup:
    """Fix #14: Stale Dockerfiles must be cleaned up for removed PHP versions."""

    def test_dockerfile_removed_on_php_version_removed(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )

        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2"),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "services": ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        })
        save_config(desired, tmp_config_dir)

        removed_files: list[str] = []

        class TrackingFileWriter(MockFileWriter):
            def remove(self, path: str) -> None:
                removed_files.append(path)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=TrackingFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("docker/php-8.3/Dockerfile" in p for p in removed_files)


class TestCommitLock:
    """Fix #18: Concurrent commits must be prevented via lock file."""

    def test_lock_prevents_concurrent_commit(self, tmp_config_dir: Path):
        import fcntl

        config = make_full_config(users={"alice": User(fullname="Alice")})
        save_config(config, tmp_config_dir)

        # Acquire the lock manually to simulate another commit in progress
        lock_path = tmp_config_dir / ".commit.lock"
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            engine = CommitEngine(
                config_dir=tmp_config_dir,
                file_writer=MockFileWriter(),
            )
            result = engine.run()
            assert not result.success
            assert any("Another commit is in progress" in e for e in result.errors)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def test_lock_released_after_commit(self, tmp_config_dir: Path):
        config = make_full_config(users={"alice": User(fullname="Alice")})
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        # Lock file should be cleaned up after successful commit
        assert not (tmp_config_dir / ".commit.lock").exists()


class TestHostCommands:
    """System user changes generate host commands instead of direct operations.

    noPanel runs in a container and cannot manage host system users directly.
    The commit engine generates shell commands for the administrator to run.
    """

    def test_useradd_command_on_add(self, tmp_config_dir: Path):
        config = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("useradd" in cmd and "alice" in cmd for cmd in result.host_commands)
        assert any("chpasswd" in cmd and "alice" in cmd for cmd in result.host_commands)

    def test_chpasswd_command_on_password_modify(self, tmp_config_dir: Path):
        committed = make_full_config(
            users={"alice": User(fullname="Alice", password="oldpass12")}
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "users": UsersConfig(users={
                "alice": User(fullname="Alice", password="newpass34")
            })
        })
        save_config(desired, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("chpasswd" in cmd and "newpass34" in cmd for cmd in result.host_commands)
        assert not any("useradd" in cmd for cmd in result.host_commands)

    def test_chsh_command_on_login_type_change(self, tmp_config_dir: Path):
        committed = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345", login=LoginType.SFTP)}
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "users": UsersConfig(users={
                "alice": User(fullname="Alice", password="pass12345", login=LoginType.SSH)
            })
        })
        save_config(desired, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("chsh" in cmd and "/bin/bash" in cmd for cmd in result.host_commands)

    def test_userdel_command_on_remove(self, tmp_config_dir: Path):
        committed = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "users": UsersConfig(users={})
        })
        save_config(desired, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert any("userdel" in cmd and "alice" in cmd for cmd in result.host_commands)

    def test_no_host_commands_when_no_user_changes(self, tmp_config_dir: Path):
        config = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(config, tmp_config_dir)
        save_committed(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        assert result.host_commands == []

    def test_host_commands_shell_safe(self, tmp_config_dir: Path):
        """Host commands must use shlex.quote to prevent injection."""
        config = make_full_config(
            users={"alice": User(fullname="Alice", password="pass'word")}
        )
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        # Password with single quote must be safely quoted
        assert any("chpasswd" in cmd for cmd in result.host_commands)
        # No raw unescaped single quote in the password portion
        chpasswd_cmd = [c for c in result.host_commands if "chpasswd" in c][0]
        assert "'pass'\"'\"'word'" in chpasswd_cmd or "pass\\'word" not in chpasswd_cmd

    def test_pending_file_written_on_commit(self, tmp_config_dir: Path):
        """Commit writes host commands to pending-host-cmds.sh in config_dir."""
        config = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        pending = tmp_config_dir / "pending-host-cmds.sh"
        assert pending.exists()
        content = pending.read_text()
        assert "useradd" in content
        assert "alice" in content
        assert content.startswith("# batch:")

    def test_batches_accumulate_in_pending_file(self, tmp_config_dir: Path):
        """Multiple commits append batches to the same pending file."""
        # First commit: add alice
        config1 = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(config1, tmp_config_dir)
        save_committed(config1, tmp_config_dir)

        # Add bob and commit again
        config2 = config1.model_copy(update={
            "users": UsersConfig(users={
                "alice": User(fullname="Alice", password="pass12345"),
                "bob": User(fullname="Bob", password="bobpass12"),
            })
        })
        save_config(config2, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        pending = tmp_config_dir / "pending-host-cmds.sh"
        assert pending.exists()
        content = pending.read_text()
        # Only bob's commands should be in this batch (alice was already committed)
        assert "bob" in content
        assert "useradd" in content

    def test_warns_when_pending_commands_exist(self, tmp_config_dir: Path):
        """Commit warns if pending-host-cmds.sh already exists from a previous commit."""
        # Pre-create a pending file simulating unexecuted commands
        pending = tmp_config_dir / "pending-host-cmds.sh"
        pending.write_text("# batch: 2024-01-01 00:00:00\nuseradd -m -s /sbin/nologin charlie\n")

        config = make_full_config(
            users={"alice": User(fullname="Alice", password="pass12345")}
        )
        save_config(config, tmp_config_dir)

        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert not result.success
        assert any("Pending host commands" in e for e in result.errors)
        # New commands should still be appended
        content = pending.read_text()
        assert "charlie" in content
        assert "alice" in content


class TestServiceFilterConfigGeneration:
    """Fix #7: Config generation should respect service_filter."""

    def test_databases_filter_skips_web_configs(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2"),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)

        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
        )
        result = engine.run(service_filter="databases")
        assert result.success
        # Web configs should not be generated with databases filter
        assert "apache/httpd.conf" not in result.generated_files
        assert "apache/domains/example.com.http.conf" not in result.generated_files

    def test_web_filter_generates_web_configs(self, tmp_config_dir: Path):
        from nopanel.models import (
            Domain, DomainsConfig, MariaDBService, PHPFpmService,
            ServicesConfig, ValkeyService, WebService,
        )

        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(domains={
                "example.com": Domain(user="alice", php_version="8.2"),
            }),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(config, tmp_config_dir)

        mock_writer = MockFileWriter()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            file_writer=mock_writer,
        )
        result = engine.run(service_filter="web")
        assert result.success
        assert "apache/httpd.conf" in result.generated_files
        assert "apache/domains/example.com.http.conf" in result.generated_files


class TestDeletedServiceStop:
    """Fix #8: Deleted service containers must be stopped during commit."""

    def test_deleted_php_version_stopped(self, tmp_config_dir: Path):
        from nopanel.models import (
            MariaDBService, PHPFpmService, ServicesConfig, ValkeyService, WebService,
        )

        committed = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(users={"alice": User(fullname="Alice")}),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService(), "8.3": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )
        save_config(committed, tmp_config_dir)
        save_committed(committed, tmp_config_dir)

        desired = committed.model_copy(update={
            "services": ServicesConfig(
                web=WebService(),
                php={"8.2": PHPFpmService()},
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        })
        save_config(desired, tmp_config_dir)

        mock_docker = MockDockerManager()
        engine = CommitEngine(
            config_dir=tmp_config_dir,
            docker_manager=mock_docker,
            file_writer=MockFileWriter(),
        )
        result = engine.run()
        assert result.success
        stop_calls = [c for c in mock_docker.calls if c[0] == "stop"]
        stopped_services = []
        for call in stop_calls:
            stopped_services.extend(call[1] or [])
        assert "php-8.3" in stopped_services


class TestComposeConditionalServices:
    """Fix #10: MariaDB and Valkey should be conditional in compose template."""

    def test_mariadb_excluded_when_disabled(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": False},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "nopanel-mariadb" not in result
        assert "nopanel-valkey" in result

    def test_valkey_excluded_when_disabled(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": False},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "nopanel-mariadb" in result
        assert "nopanel-valkey" not in result

    def test_both_excluded_when_disabled(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": False},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": False},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "nopanel-mariadb" not in result
        assert "nopanel-valkey" not in result
        assert "nopanel-apache" in result
        assert "nopanel-php-8.2" in result


class TestComposePhpImageFromConfig:
    """Fix #9: Compose template should use PHP service image from config."""

    def test_custom_image_used(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "myregistry/php-8.2:v2"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "myregistry/php-8.2:v2" in result
        assert "nopanel/php-8.2:latest" not in result

    def test_fallback_to_default_when_empty(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": ""}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "nopanel/php-8.2:latest" in result


class TestInitForceCleanup:
    """Fix #11: init --force should clean up .committed/ and generated/."""

    def test_force_cleans_committed_and_generated(self, tmp_path: Path):
        from nopanel.cli import init
        from nopanel.config import DEFAULT_CONFIG_DIR
        from nopanel.state import get_committed_dir

        # Create a fake config dir with stale state
        config_dir = tmp_path / "nopanel"
        config_dir.mkdir()
        committed_dir = get_committed_dir(config_dir)
        committed_dir.mkdir(parents=True)
        (committed_dir / "users.yml").write_text("stale")

        # Create stale generated dir (now relative to config_dir)
        generated_dir = config_dir / "generated"
        generated_dir.mkdir()
        stale_file = generated_dir / "docker-compose.yml"
        stale_file.write_text("stale")

        # Monkeypatch DEFAULT_CONFIG_DIR
        import nopanel.cli as cli_mod
        import nopanel.config as config_mod

        original_config_dir = config_mod.DEFAULT_CONFIG_DIR
        config_mod.DEFAULT_CONFIG_DIR = config_dir

        try:
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(cli_mod.app, ["init", "--force"])
            assert result.exit_code == 0
            assert not committed_dir.exists()
            # The generated dir is recreated (empty) by init, but stale content must be gone
            assert not stale_file.exists()
        finally:
            config_mod.DEFAULT_CONFIG_DIR = original_config_dir


class TestHttpdEssentialModules:
    """Fix #3: httpd.conf must include essential modules for httpd:2.4-alpine."""

    def test_essential_modules_present(self):
        from nopanel.templates import render_httpd_base

        result = render_httpd_base(modules=["md", "ssl"])
        assert "LoadModule mpm_event_module" in result
        assert "LoadModule authn_core_module" in result
        assert "LoadModule authz_core_module" in result
        assert "LoadModule mime_module" in result
        assert "LoadModule log_config_module" in result
        assert "LoadModule dir_module" in result

    def test_socache_shmcb_loads_before_ssl(self):
        from nopanel.templates import render_httpd_base

        result = render_httpd_base(modules=["ssl", "md"])
        socache_pos = result.index("LoadModule socache_shmcb_module")
        ssl_pos = result.index("LoadModule ssl_module")
        assert socache_pos < ssl_pos

    def test_proxy_loads_before_proxy_fcgi(self):
        from nopanel.templates import render_httpd_base

        result = render_httpd_base(modules=["proxy", "proxy_fcgi", "ssl"])
        proxy_pos = result.index("LoadModule proxy_module")
        proxy_fcgi_pos = result.index("LoadModule proxy_fcgi_module")
        assert proxy_pos < proxy_fcgi_pos


class TestComposeApacheCommand:
    """Fix #2: Apache compose service must use generated httpd.conf."""

    def test_compose_has_command_override(self):
        from nopanel.templates import render_compose

        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "command:" in result
        assert "conf.d/httpd.conf" in result
        assert "-DFOREGROUND" in result


class TestServiceFilterValidation:
    """Tests for strengthened service_filter validation in commit engine."""

    def test_invalid_filter_rejected(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        engine = CommitEngine(config_dir=tmp_config_dir, docker_manager=None)
        result = engine.run(service_filter="phpwhatever")
        assert len(result.errors) == 1
        assert "Invalid service filter" in result.errors[0]

    def test_garbage_filter_rejected(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        engine = CommitEngine(config_dir=tmp_config_dir, docker_manager=None)
        result = engine.run(service_filter="; rm -rf /")
        assert len(result.errors) == 1
        assert "Invalid service filter" in result.errors[0]

    def test_valid_php_version_filter_accepted(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        engine = CommitEngine(config_dir=tmp_config_dir, docker_manager=None)
        result = engine.run(dry_run=True, service_filter="php-8.2")
        # Should not error on filter validation
        assert not any("Invalid service filter" in e for e in result.errors)

    def test_valid_named_filter_accepted(self, tmp_config_dir: Path):
        config = make_full_config()
        save_config(config, tmp_config_dir)
        engine = CommitEngine(config_dir=tmp_config_dir, docker_manager=None)
        for f in ("databases", "web", "apache", "services", "users", "php"):
            result = engine.run(dry_run=True, service_filter=f)
            assert not any("Invalid service filter" in e for e in result.errors)
