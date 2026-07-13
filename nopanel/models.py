"""Pydantic models for all noPanel v2 configuration entities.

All models use Pydantic v2 for validation and serialization.
Models are immutable (frozen) to enable safe diffing.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigModel(BaseModel):
    """Base config model with frozen fields and extra='forbid'."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NetworkMode(str, Enum):
    HOST = "host"
    BRIDGE = "bridge"


class LoginType(str, Enum):
    SSH = "ssh"
    SFTP = "sftp"
    NO = "no"


class SSLMode(str, Enum):
    AUTO = "auto"
    SELF = "self"
    NONE = "none"


# ---------------------------------------------------------------------------
# Global Settings (nopanel.yml)
# ---------------------------------------------------------------------------


class Settings(ConfigModel):
    network_mode: NetworkMode = NetworkMode.HOST
    admin_email: str = ""


class MariaDBSettings(ConfigModel):
    default_branch: str = "lts"


class PHPSettings(ConfigModel):
    versions: list[str] = Field(default_factory=lambda: ["8.2", "8.3", "8.4", "8.5"])
    additional_modules: list[str] = Field(default_factory=list)


class NopanelConfig(ConfigModel):
    version: int = 2
    settings: Settings = Field(default_factory=Settings)
    mariadb: MariaDBSettings = Field(default_factory=MariaDBSettings)
    php: PHPSettings = Field(default_factory=PHPSettings)


# ---------------------------------------------------------------------------
# Users (users.yml)
# ---------------------------------------------------------------------------


_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_PASSWORD_MIN_LEN = 8
_PASSWORD_MAX_LEN = 128


def validate_username(username: str) -> bool:
    """Validate a Unix username."""
    return bool(_USERNAME_RE.match(username))


def validate_password(password: str) -> bool:
    """Validate password strength. Returns True if valid."""
    if not password:
        return False
    if len(password) < _PASSWORD_MIN_LEN:
        return False
    if len(password) > _PASSWORD_MAX_LEN:
        return False
    return True


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# Module names: alphanumeric, dashes, underscores, and optional pecl: prefix.
# Prevents shell metacharacter injection into generated Dockerfiles.
_MODULE_RE = re.compile(r"^(pecl:)?[a-zA-Z0-9][a-zA-Z0-9_-]*\Z")


def validate_module_name(module: str) -> bool:
    """Validate a PHP module name to prevent Dockerfile/shell injection."""
    return bool(_MODULE_RE.match(module))


# Docroot: relative path with no path traversal, no newlines, no shell metacharacters.
# Prevents Apache config injection via generated vhost files.
_DOCROOT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*\Z")


def validate_docroot(docroot: str) -> bool:
    """Validate a docroot relative path (no traversal, no newlines, no injection)."""
    if not docroot or "\n" in docroot or "\r" in docroot:
        return False
    if ".." in docroot.split("/"):
        return False
    return bool(_DOCROOT_RE.match(docroot))


def validate_email(email: str) -> bool:
    """Validate an email address format."""
    return bool(_EMAIL_RE.match(email))


class User(ConfigModel):
    fullname: str = ""
    email: str = ""
    login: LoginType = LoginType.SFTP
    admin: bool = False
    password: str = ""

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        if v and not validate_email(v):
            raise ValueError(f"Invalid email format: {v}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        # Defense-in-depth: CLI validates too, but this catches import/migrate/hand-edited YAML.
        # Empty password is allowed (user may not need login yet).
        if v and not validate_password(v):
            raise ValueError(
                f"Password must be {_PASSWORD_MIN_LEN}-{_PASSWORD_MAX_LEN} characters"
            )
        return v


class UsersConfig(ConfigModel):
    users: dict[str, User] = Field(default_factory=dict)

    @field_validator("users")
    @classmethod
    def validate_usernames(cls, v: dict[str, User]) -> dict[str, User]:
        for username in v:
            if not validate_username(username):
                raise ValueError(f"Invalid username: {username}")
        return v


# ---------------------------------------------------------------------------
# Domains (domains.yml)
# ---------------------------------------------------------------------------


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$"
)


def validate_domain(domain: str) -> bool:
    """Validate a domain name."""
    return bool(_DOMAIN_RE.match(domain))


class Domain(ConfigModel):
    user: str
    php_version: str | None = None  # None means no PHP
    ssl: SSLMode = SSLMode.NONE
    aliases: list[str] = Field(default_factory=list)
    web: bool = True
    docroot: str = "public_html"  # Relative to /home/$user/web/$domain/

    @field_validator("php_version")
    @classmethod
    def validate_php_version(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not re.match(r"^\d+\.\d+$", v):
            raise ValueError(f"Invalid PHP version format: {v}")
        return v

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, v: list[str]) -> list[str]:
        # Prevent Apache config injection: each alias must be a valid domain.
        for alias in v:
            if not validate_domain(alias):
                raise ValueError(f"Invalid domain alias: {alias}")
        return v

    @field_validator("docroot")
    @classmethod
    def validate_docroot_field(cls, v: str) -> str:
        if not validate_docroot(v):
            raise ValueError(f"Invalid docroot: {v}")
        return v


class DomainsConfig(ConfigModel):
    domains: dict[str, Domain] = Field(default_factory=dict)

    @field_validator("domains")
    @classmethod
    def validate_domain_names(cls, v: dict[str, Domain]) -> dict[str, Domain]:
        for domain_name in v:
            if not validate_domain(domain_name):
                raise ValueError(f"Invalid domain name: {domain_name}")
        return v


# ---------------------------------------------------------------------------
# Databases (databases.yml)
# ---------------------------------------------------------------------------


_DB_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$")


def validate_db_name(name: str) -> bool:
    """Validate a database name."""
    return bool(_DB_NAME_RE.match(name))


class Database(ConfigModel):
    user: str  # Owner (nopanel user)
    dbuser: str  # MariaDB username
    password: str = ""  # Plaintext — MariaDB GRANT requires it

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        # Defense-in-depth: catches import/migrate/hand-edited YAML.
        # Empty password is allowed (will be caught at commit time by grant_user_sql).
        if v and not validate_password(v):
            raise ValueError(
                f"Password must be {_PASSWORD_MIN_LEN}-{_PASSWORD_MAX_LEN} characters"
            )
        return v


class DatabasesConfig(ConfigModel):
    databases: dict[str, Database] = Field(default_factory=dict)

    @field_validator("databases")
    @classmethod
    def validate_db_names(cls, v: dict[str, Database]) -> dict[str, Database]:
        for db_name in v:
            if not validate_db_name(db_name):
                raise ValueError(f"Invalid database name: {db_name}")
        return v


# ---------------------------------------------------------------------------
# Services (services.yml)
# ---------------------------------------------------------------------------


class WebService(ConfigModel):
    image: str = "httpd:2.4-alpine"
    ports: list[int] = Field(default_factory=lambda: [80, 443])
    modules: list[str] = Field(
        default_factory=lambda: ["md", "proxy", "proxy_fcgi", "rewrite", "ssl"]
    )


class PHPFpmService(ConfigModel):
    image: str = ""
    custom_image: bool = True  # Built from docker/php-X.Y/Dockerfile


class MariaDBService(ConfigModel):
    image: str = "mariadb:lts"
    port: int = 3306
    root_password: str = ""
    enabled: bool = True


class ValkeyService(ConfigModel):
    image: str = "valkey/valkey:8-alpine"
    port: int = 6379
    enabled: bool = True


class ServicesConfig(ConfigModel):
    web: WebService = Field(default_factory=WebService)
    php: dict[str, PHPFpmService] = Field(default_factory=dict)
    mariadb: MariaDBService = Field(default_factory=MariaDBService)
    valkey: ValkeyService = Field(default_factory=ValkeyService)


# ---------------------------------------------------------------------------
# Full Config (aggregate of all YAML files)
# ---------------------------------------------------------------------------


class FullConfig(ConfigModel):
    """Aggregate of all noPanel config files.

    Used for in-memory operations, diffing, and export/import.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nopanel: NopanelConfig = Field(default_factory=NopanelConfig)
    users: UsersConfig = Field(default_factory=UsersConfig)
    domains: DomainsConfig = Field(default_factory=DomainsConfig)
    databases: DatabasesConfig = Field(default_factory=DatabasesConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)

    @model_validator(mode="after")
    def validate_cross_references(self) -> "FullConfig":
        """Validate that domain and database owners exist in users config."""
        usernames = set(self.users.users.keys())

        for domain_name, domain in self.domains.domains.items():
            if domain.user not in usernames:
                raise ValueError(
                    f"Domain '{domain_name}' references unknown user '{domain.user}'"
                )

        for db_name, db in self.databases.databases.items():
            if db.user not in usernames:
                raise ValueError(
                    f"Database '{db_name}' references unknown user '{db.user}'"
                )

        return self
