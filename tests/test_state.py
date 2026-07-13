"""Tests for nopanel.state — committed state and diff engine."""

from pathlib import Path

import pytest

from nopanel.models import (
    Database,
    DatabasesConfig,
    Domain,
    DomainsConfig,
    FullConfig,
    NetworkMode,
    NopanelConfig,
    PHPFpmService,
    Settings,
    User,
    UsersConfig,
)
from nopanel.state import (
    ConfigDiff,
    EntityChange,
    SectionDiff,
    diff_configs,
    format_diff,
    load_committed,
    save_committed,
)


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "nopanel"
    d.mkdir()
    return d


def make_config(
    users: dict[str, User] | None = None,
    domains: dict[str, Domain] | None = None,
    databases: dict[str, Database] | None = None,
    admin_email: str = "",
    network_mode: NetworkMode = NetworkMode.HOST,
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
        nopanel=NopanelConfig(settings=Settings(admin_email=admin_email, network_mode=network_mode)),
        users=UsersConfig(users=all_users),
        domains=DomainsConfig(domains=domains or {}),
        databases=DatabasesConfig(databases=databases or {}),
    )


class TestDiffConfigs:
    def test_empty_diff(self):
        config = make_config(users={"alice": User(fullname="Alice")})
        diff = diff_configs(config, config)
        assert diff.is_empty

    def test_user_added(self):
        committed = make_config()
        desired = make_config(users={"alice": User(fullname="Alice")})
        diff = diff_configs(desired, committed)
        assert not diff.is_empty
        assert len(diff.users.added) == 1
        assert diff.users.added[0].name == "alice"
        assert len(diff.users.modified) == 0
        assert len(diff.users.deleted) == 0

    def test_user_deleted(self):
        committed = make_config(users={"alice": User(fullname="Alice")})
        desired = make_config()
        diff = diff_configs(desired, committed)
        assert len(diff.users.deleted) == 1
        assert diff.users.deleted[0].name == "alice"

    def test_user_modified(self):
        committed = make_config(users={"alice": User(fullname="Alice")})
        desired = make_config(users={"alice": User(fullname="Alice Smith")})
        diff = diff_configs(desired, committed)
        assert len(diff.users.modified) == 1
        assert diff.users.modified[0].name == "alice"

    def test_domain_added(self):
        committed = make_config()
        desired = make_config(domains={"example.com": Domain(user="alice")})
        diff = diff_configs(desired, committed)
        assert len(diff.domains.added) == 1

    def test_database_added(self):
        committed = make_config()
        desired = make_config(
            databases={"alice_blog": Database(user="alice", dbuser="alice_blog", password="pass1234")}
        )
        diff = diff_configs(desired, committed)
        assert len(diff.databases.added) == 1

    def test_settings_changed(self):
        committed = make_config(admin_email="old@test.com")
        desired = make_config(admin_email="new@test.com")
        diff = diff_configs(desired, committed)
        assert diff.settings_changed
        assert diff.settings_new["admin_email"] == "new@test.com"

    def test_network_mode_changed(self):
        committed = make_config(network_mode=NetworkMode.HOST)
        desired = make_config(network_mode=NetworkMode.BRIDGE)
        diff = diff_configs(desired, committed)
        assert diff.settings_changed

    def test_total_changes(self):
        committed = make_config()
        desired = make_config(
            users={"alice": User(), "bob": User()},
            domains={"example.com": Domain(user="alice")},
        )
        diff = diff_configs(desired, committed)
        assert diff.total_changes == 3  # 2 users + 1 domain

    def test_mariadb_settings_changed(self):
        """Changes to nopanel.mariadb settings should be detected (fix #4)."""
        from nopanel.models import MariaDBSettings
        committed = make_config()
        desired = make_config()
        desired = desired.model_copy(update={
            "nopanel": desired.nopanel.model_copy(update={
                "mariadb": MariaDBSettings(default_branch="latest")
            })
        })
        diff = diff_configs(desired, committed)
        assert diff.settings_changed

    def test_php_settings_changed(self):
        """Changes to nopanel.php settings should be detected (fix #4)."""
        from nopanel.models import PHPSettings
        committed = make_config()
        desired = make_config()
        desired = desired.model_copy(update={
            "nopanel": desired.nopanel.model_copy(update={
                "php": PHPSettings(additional_modules=["imagick"])
            })
        })
        diff = diff_configs(desired, committed)
        assert diff.settings_changed


class TestServicesDiff:
    """Tests for per-PHP-version services diff (fix #10)."""

    def _make_config_with_php(self, php_versions: dict[str, PHPFpmService]) -> FullConfig:
        from nopanel.models import MariaDBService, ServicesConfig, ValkeyService, WebService
        return FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(),
            domains=DomainsConfig(),
            databases=DatabasesConfig(),
            services=ServicesConfig(
                web=WebService(),
                php=php_versions,
                mariadb=MariaDBService(),
                valkey=ValkeyService(),
            ),
        )

    def test_php_version_added(self):
        committed = self._make_config_with_php({"8.2": PHPFpmService()})
        desired = self._make_config_with_php({"8.2": PHPFpmService(), "8.3": PHPFpmService()})
        diff = diff_configs(desired, committed)
        assert len(diff.services.added) == 1
        assert diff.services.added[0].name == "php-8.3"

    def test_php_version_removed(self):
        committed = self._make_config_with_php({"8.2": PHPFpmService(), "8.3": PHPFpmService()})
        desired = self._make_config_with_php({"8.2": PHPFpmService()})
        diff = diff_configs(desired, committed)
        assert len(diff.services.deleted) == 1
        assert diff.services.deleted[0].name == "php-8.3"

    def test_single_php_version_modified(self):
        committed = self._make_config_with_php({
            "8.2": PHPFpmService(image="nopanel/php-8.2:old"),
            "8.3": PHPFpmService(image="nopanel/php-8.3:latest"),
        })
        desired = self._make_config_with_php({
            "8.2": PHPFpmService(image="nopanel/php-8.2:new"),
            "8.3": PHPFpmService(image="nopanel/php-8.3:latest"),
        })
        diff = diff_configs(desired, committed)
        assert len(diff.services.modified) == 1
        assert diff.services.modified[0].name == "php-8.2"

    def test_no_php_changes(self):
        config = self._make_config_with_php({"8.2": PHPFpmService(), "8.3": PHPFpmService()})
        diff = diff_configs(config, config)
        assert diff.services.total_changes == 0


class TestCommittedState:
    def test_save_and_load_committed(self, tmp_config_dir: Path):
        config = make_config(users={"alice": User(fullname="Alice")})
        save_committed(config, tmp_config_dir)
        loaded = load_committed(tmp_config_dir)
        assert "alice" in loaded.users.users
        assert loaded.users.users["alice"].fullname == "Alice"

    def test_load_committed_empty(self, tmp_config_dir: Path):
        loaded = load_committed(tmp_config_dir)
        assert len(loaded.users.users) == 0


class TestFormatDiff:
    def test_empty_diff(self):
        diff = ConfigDiff()
        assert format_diff(diff) == "No changes to commit."

    def test_format_with_changes(self):
        diff = ConfigDiff(
            users=SectionDiff(
                added=[EntityChange(
                    name="alice", old=None, new={"fullname": "Alice"}
                )]
            )
        )
        text = format_diff(diff)
        assert "alice" in text
        assert "Users:" in text
        assert "+" in text
