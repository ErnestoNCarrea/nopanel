"""Tests for service modules — web, php, database, cache."""

import pytest

from nopanel.models import (
    Database,
    Domain,
    DomainsConfig,
    FullConfig,
    NopanelConfig,
    PHPFpmService,
    PHPSettings,
    ServicesConfig,
    SSLMode,
    User,
    UsersConfig,
    WebService,
)
from nopanel.services.base import docroot_path, php_socket_path
from nopanel.services.database import (
    apply_database_changes,
    create_database_sql,
    drop_database_sql,
    drop_user_sql,
    full_db_name,
    full_db_user,
    grant_user_sql,
)
from nopanel.services.php import (
    add_module,
    generate_dockerfiles,
    generate_pool_configs,
    list_modules,
    remove_module,
)
from nopanel.services.web import generate_vhost_configs


def make_config(
    users: dict[str, User] | None = None,
    domains: dict[str, Domain] | None = None,
    php_versions: list[str] | None = None,
    additional_modules: list[str] | None = None,
) -> FullConfig:
    php_settings = PHPSettings(
        versions=php_versions or ["8.2", "8.3", "8.4", "8.5"],
        additional_modules=additional_modules or [],
    )
    nopanel = NopanelConfig(php=php_settings)
    services = ServicesConfig(
        php={v: PHPFpmService() for v in (php_versions or ["8.2", "8.3", "8.4", "8.5"])}
    )
    return FullConfig(
        nopanel=nopanel,
        users=UsersConfig(users=users or {}),
        domains=DomainsConfig(domains=domains or {}),
        services=services,
    )


class TestWebService:
    def test_generate_vhost_basic(self):
        config = make_config(
            users={"alice": User(email="alice@test.com")},
            domains={"example.com": Domain(user="alice", php_version="8.2")},
        )
        files = generate_vhost_configs(config)
        assert "apache/httpd.conf" in files
        assert "apache/domains/example.com.http.conf" in files

    def test_generate_vhost_with_ssl(self):
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", ssl=SSLMode.AUTO)},
        )
        files = generate_vhost_configs(config)
        assert "apache/mod_md.conf" in files
        assert "apache/domains/example.com.https.conf" in files

    def test_generate_vhost_no_ssl(self):
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", ssl=SSLMode.NONE)},
        )
        files = generate_vhost_configs(config)
        assert "apache/mod_md.conf" not in files
        assert "apache/domains/example.com.https.conf" not in files

    def test_generate_vhost_with_aliases(self):
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", aliases=["www.example.com"])},
        )
        files = generate_vhost_configs(config)
        assert "www.example.com" in files["apache/domains/example.com.http.conf"]

    def test_generate_vhost_ssl_auto_has_redirect(self):
        """HTTP vhost for auto-SSL domain should contain HTTPS redirect."""
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", ssl=SSLMode.AUTO)},
        )
        files = generate_vhost_configs(config)
        http_conf = files["apache/domains/example.com.http.conf"]
        assert "RewriteRule" in http_conf
        assert "https://%{HTTP_HOST}" in http_conf

    def test_generate_vhost_ssl_none_no_redirect(self):
        """HTTP vhost for non-SSL domain should NOT contain HTTPS redirect."""
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", ssl=SSLMode.NONE)},
        )
        files = generate_vhost_configs(config)
        http_conf = files["apache/domains/example.com.http.conf"]
        assert "RewriteRule" not in http_conf

    def test_generate_vhost_custom_docroot(self):
        config = make_config(
            users={"alice": User()},
            domains={"example.com": Domain(user="alice", docroot="htdocs")},
        )
        files = generate_vhost_configs(config)
        vhost = files["apache/domains/example.com.http.conf"]
        assert "/home/alice/web/example.com/htdocs" in vhost
        assert "public_html" not in vhost


class TestPHPFpmService:
    def test_generate_pool_configs(self):
        config = make_config(
            users={"alice": User()},
            domains={
                "example.com": Domain(user="alice", php_version="8.2"),
                "test.com": Domain(user="alice", php_version="8.3"),
            },
        )
        files = generate_pool_configs(config)
        assert "php-fpm/php82/example.com.conf" in files
        assert "php-fpm/php83/test.com.conf" in files
        assert "[example.com]" in files["php-fpm/php82/example.com.conf"]
        assert "[test.com]" in files["php-fpm/php83/test.com.conf"]

    def test_generate_pool_configs_multiple_same_version(self):
        """Two domains with the same PHP version must produce separate files."""
        config = make_config(
            users={"alice": User()},
            domains={
                "example.com": Domain(user="alice", php_version="8.2"),
                "test.com": Domain(user="alice", php_version="8.2"),
            },
        )
        files = generate_pool_configs(config)
        assert "php-fpm/php82/example.com.conf" in files
        assert "php-fpm/php82/test.com.conf" in files
        assert "[example.com]" in files["php-fpm/php82/example.com.conf"]
        assert "[test.com]" in files["php-fpm/php82/test.com.conf"]

    def test_generate_pool_configs_no_php(self):
        config = make_config(
            users={"alice": User()},
            domains={"static.com": Domain(user="alice", php_version=None)},
        )
        files = generate_pool_configs(config)
        assert len(files) == 0

    def test_generate_dockerfiles(self):
        config = make_config(php_versions=["8.2", "8.3", "8.4", "8.5"])
        files = generate_dockerfiles(config)
        assert "docker/php-8.2/Dockerfile" in files
        assert "docker/php-8.3/Dockerfile" in files
        assert "docker/php-8.4/Dockerfile" in files
        assert "docker/php-8.5/Dockerfile" in files
        assert "FROM php:8.2-fpm-alpine" in files["docker/php-8.2/Dockerfile"]
        assert "FROM php:8.5-fpm-alpine" in files["docker/php-8.5/Dockerfile"]

    def test_add_module(self):
        config = make_config()
        new_config = add_module(config, "8.2", "imagick")
        assert "imagick" in new_config.nopanel.php.additional_modules

    def test_remove_module(self):
        config = make_config(additional_modules=["imagick", "redis"])
        new_config = remove_module(config, "8.2", "imagick")
        assert "imagick" not in new_config.nopanel.php.additional_modules
        assert "redis" in new_config.nopanel.php.additional_modules

    def test_list_modules(self):
        config = make_config(additional_modules=["imagick", "pecl:redis"])
        modules = list_modules(config, "8.2")
        assert "imagick" in modules
        assert "pecl:redis" in modules


class TestDatabaseService:
    def test_create_database_sql(self):
        sql = create_database_sql("alice_blog")
        assert "CREATE DATABASE IF NOT EXISTS `alice_blog`" in sql

    def test_grant_user_sql(self):
        statements = grant_user_sql("alice_blog", "alice_blog", "pass12345")
        assert len(statements) == 2
        assert "GRANT ALL ON `alice_blog`.* TO `alice_blog`@`%`" in statements[0]
        assert "IDENTIFIED BY 'pass12345'" in statements[0]
        assert "localhost" in statements[1]

    def test_grant_user_sql_no_password(self):
        with pytest.raises(ValueError, match="empty password"):
            grant_user_sql("alice_blog", "alice_blog", "")

    def test_drop_database_sql(self):
        sql = drop_database_sql("alice_blog")
        assert "DROP DATABASE IF EXISTS `alice_blog`" in sql

    def test_drop_user_sql(self):
        sql = drop_user_sql("alice_blog")
        assert "DROP USER IF EXISTS `alice_blog`" in sql

    def test_full_db_name(self):
        assert full_db_name("alice", "blog") == "alice_blog"

    def test_full_db_user(self):
        assert full_db_user("alice", "blog") == "alice_blog"

    def test_apply_database_changes_added(self):
        """Test creating databases via apply_database_changes (fix #8)."""
        executed = []

        class FakeExecutor:
            def execute(self, query):
                executed.append(query)

        added = [Database(user="alice", dbuser="alice_blog", password="pass12345")]
        result = apply_database_changes(
            added=added,
            modified=[],
            deleted=[],
            db_names=["alice_blog"],
            executor=FakeExecutor(),
        )
        assert any("CREATE DATABASE" in q for q in executed)
        assert any("GRANT ALL" in q for q in executed)
        assert len(result) == 3  # CREATE + 2 GRANTs

    def test_apply_database_changes_modified(self):
        """Modified databases should DROP old user + GRANT new (fix #8)."""
        executed = []

        class FakeExecutor:
            def execute(self, query):
                executed.append(query)

        old_db = Database(user="alice", dbuser="alice_blog", password="oldpass12")
        new_db = Database(user="alice", dbuser="alice_blog", password="newpass12")
        result = apply_database_changes(
            added=[],
            modified=[(old_db, new_db)],
            deleted=[],
            db_names=["alice_blog"],
            executor=FakeExecutor(),
        )
        assert any("DROP USER" in q for q in executed)
        assert any("GRANT ALL" in q and "newpass12" in q for q in executed)
        assert len(result) == 3  # DROP + 2 GRANTs

    def test_apply_database_changes_deleted(self):
        """Deleted databases should DROP DATABASE + DROP USER (fix #8)."""
        executed = []

        class FakeExecutor:
            def execute(self, query):
                executed.append(query)

        deleted = [Database(user="alice", dbuser="alice_blog", password="pass1234")]
        result = apply_database_changes(
            added=[],
            modified=[],
            deleted=deleted,
            db_names=["alice_blog"],
            executor=FakeExecutor(),
        )
        assert any("DROP DATABASE" in q for q in executed)
        assert any("DROP USER" in q for q in executed)
        assert len(result) == 2

    def test_apply_database_changes_mismatched_db_names_raises(self):
        """Should raise ValueError if db_names length doesn't match (fix #8)."""

        class FakeExecutor:
            def execute(self, query):
                pass

        with pytest.raises(ValueError, match="db_names has"):
            apply_database_changes(
                added=[Database(user="a", dbuser="b", password="c1234567")],
                modified=[],
                deleted=[],
                db_names=[],
                executor=FakeExecutor(),
            )

    def test_apply_database_changes_all_three(self):
        """Test added + modified + deleted in one call (fix #8 indexing)."""
        executed = []

        class FakeExecutor:
            def execute(self, query):
                executed.append(query)

        added = [Database(user="alice", dbuser="alice_new", password="pass1234")]
        old_db = Database(user="bob", dbuser="bob_old", password="oldpass12")
        new_db = Database(user="bob", dbuser="bob_new", password="newpass12")
        deleted = [Database(user="carol", dbuser="carol_del", password="delpass12")]
        result = apply_database_changes(
            added=added,
            modified=[(old_db, new_db)],
            deleted=deleted,
            db_names=["alice_new", "bob_db", "carol_del"],
            executor=FakeExecutor(),
        )
        # added: CREATE + 2 GRANTs = 3
        # modified: DROP + 2 GRANTs = 3
        # deleted: DROP DB + DROP USER = 2
        assert len(result) == 8
        assert "alice_new" in result[0]  # CREATE for added
        assert "bob_bob_old" in result[3]  # DROP USER for modified (old dbuser)
        assert "carol_del" in result[6]  # DROP DATABASE for deleted


class TestBaseService:
    def test_php_socket_path(self):
        assert php_socket_path("8.2") == "/var/run/php-fpm/php82-www.sock"
        assert php_socket_path("8.3") == "/var/run/php-fpm/php83-www.sock"
        assert php_socket_path("8.4") == "/var/run/php-fpm/php84-www.sock"
        assert php_socket_path("8.5") == "/var/run/php-fpm/php85-www.sock"

    def test_docroot_path(self):
        assert docroot_path("alice", "example.com") == "/home/alice/web/example.com/public_html"

    def test_docroot_path_custom(self):
        assert docroot_path("alice", "example.com", "htdocs") == (
            "/home/alice/web/example.com/htdocs"
        )


class TestSqlIdentifierEscaping:
    """Tests for backtick escaping in SQL identifiers (fix #1)."""

    def test_create_database_escapes_backticks(self):
        sql = create_database_sql("alice`malicious")
        assert "``" in sql
        assert "alice`malicious" not in sql

    def test_drop_database_escapes_backticks(self):
        sql = drop_database_sql("alice`evil")
        assert "``" in sql
        assert "alice`evil" not in sql

    def test_drop_user_escapes_backticks(self):
        sql = drop_user_sql("user`injection")
        assert "``" in sql
        assert "user`injection" not in sql

    def test_grant_user_escapes_backticks_in_db_name(self):
        statements = grant_user_sql("db`name", "user", "pass12345")
        assert "``" in statements[0]
        assert "db`name" not in statements[0]

    def test_grant_user_escapes_backticks_in_user_name(self):
        statements = grant_user_sql("db", "user`name", "pass12345")
        assert "``" in statements[0]
        assert "user`name" not in statements[0]

    def test_normal_identifiers_unchanged(self):
        sql = create_database_sql("alice_blog")
        assert sql == "CREATE DATABASE IF NOT EXISTS `alice_blog`"


class TestSqlBackslashEscaping:
    """Fix #16: SQL string escaping must handle backslashes."""

    def test_grant_user_escapes_backslash_in_password(self):
        statements = grant_user_sql("alice_blog", "alice_blog", "pass\\word")
        assert "\\\\" in statements[0]
        assert "pass\\word" not in statements[0]

    def test_grant_user_escapes_backslash_and_quote(self):
        statements = grant_user_sql("db", "user", "pa\\ss'word")
        # Both backslash and single quote must be escaped
        assert "\\\\" in statements[0]
        assert "''" in statements[0]


class TestContainerLogPaths:
    """Fix #4: Log paths in vhost configs must use container-side paths."""

    def test_domain_log_dir_is_container_path(self):
        from nopanel.services.base import domain_log_dir
        assert domain_log_dir() == "/var/log/apache2"

    def test_vhost_uses_container_log_path(self):
        config = make_config(
            users={"alice": User(email="alice@test.com")},
            domains={"example.com": Domain(user="alice", php_version="8.2")},
        )
        files = generate_vhost_configs(config)
        http_conf = files["apache/domains/example.com.http.conf"]
        assert "/var/log/apache2/domains/" in http_conf
        assert "/var/log/nopanel/apache" not in http_conf


class TestHttpdModulesFromConfig:
    """Fix #7: httpd.conf should use modules from WebService config."""

    def test_httpd_uses_custom_modules(self):
        custom_web = WebService(modules=["md", "proxy_fcgi", "proxy", "rewrite", "ssl", "socache_shmcb", "headers"])
        config = FullConfig(
            nopanel=NopanelConfig(),
            users=UsersConfig(),
            domains=DomainsConfig(),
            services=ServicesConfig(web=custom_web),
        )
        files = generate_vhost_configs(config)
        httpd = files["apache/httpd.conf"]
        assert "LoadModule headers_module" in httpd
