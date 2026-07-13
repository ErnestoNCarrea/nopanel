"""Config file I/O — load and save YAML config files, read v1 JSON.

All functions take a base path parameter (defaulting to /etc/nopanel)
so they are testable with temporary directories.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from nopanel.models import (
    Database,
    DatabasesConfig,
    Domain,
    DomainsConfig,
    FullConfig,
    LoginType,
    MariaDBService,
    MariaDBSettings,
    NopanelConfig,
    PHPFpmService,
    PHPSettings,
    ServicesConfig,
    Settings,
    SSLMode,
    User,
    UsersConfig,
    ValkeyService,
    WebService,
)

DEFAULT_CONFIG_DIR = Path("/etc/nopanel")

logger = logging.getLogger(__name__)

# YAML file names
FILE_NOPANEL = "nopanel.yml"
FILE_USERS = "users.yml"
FILE_DOMAINS = "domains.yml"
FILE_DATABASES = "databases.yml"
FILE_SERVICES = "services.yml"

# v1 JSON file names
V1_FILE_NOPANEL = "nopanel.json"
V1_FILE_USERS = "users.json"
V1_FILE_MODULES = "modules.json"


# ---------------------------------------------------------------------------
# YAML helpers (pure functions)
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return a dict. Returns empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write a dict to a YAML file. Creates parent directories.

    Sets file permissions to 0o600 because config files may contain
    plaintext passwords (users.yml, databases.yml, services.yml).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=True)
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# Load individual config files
# ---------------------------------------------------------------------------


def load_nopanel_config(base: Path | None = None) -> NopanelConfig:
    """Load nopanel.yml (global settings)."""
    base = base or DEFAULT_CONFIG_DIR
    data = _read_yaml(base / FILE_NOPANEL)
    return NopanelConfig.model_validate(data)


def load_users_config(base: Path | None = None) -> UsersConfig:
    """Load users.yml."""
    base = base or DEFAULT_CONFIG_DIR
    data = _read_yaml(base / FILE_USERS)
    return UsersConfig.model_validate(data)


def load_domains_config(base: Path | None = None) -> DomainsConfig:
    """Load domains.yml."""
    base = base or DEFAULT_CONFIG_DIR
    data = _read_yaml(base / FILE_DOMAINS)
    return DomainsConfig.model_validate(data)


def load_databases_config(base: Path | None = None) -> DatabasesConfig:
    """Load databases.yml."""
    base = base or DEFAULT_CONFIG_DIR
    data = _read_yaml(base / FILE_DATABASES)
    return DatabasesConfig.model_validate(data)


def load_services_config(base: Path | None = None) -> ServicesConfig:
    """Load services.yml."""
    base = base or DEFAULT_CONFIG_DIR
    data = _read_yaml(base / FILE_SERVICES)
    return ServicesConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Load all configs
# ---------------------------------------------------------------------------


def load_config(base: Path | None = None) -> FullConfig:
    """Load all config files from a directory and return a FullConfig."""
    base = base or DEFAULT_CONFIG_DIR
    return FullConfig(
        nopanel=load_nopanel_config(base),
        users=load_users_config(base),
        domains=load_domains_config(base),
        databases=load_databases_config(base),
        services=load_services_config(base),
    )


# ---------------------------------------------------------------------------
# Save individual config files
# ---------------------------------------------------------------------------


def save_nopanel_config(config: NopanelConfig, base: Path | None = None) -> None:
    """Save nopanel.yml."""
    base = base or DEFAULT_CONFIG_DIR
    _write_yaml(base / FILE_NOPANEL, config.model_dump(mode="json"))


def save_users_config(config: UsersConfig, base: Path | None = None) -> None:
    """Save users.yml."""
    base = base or DEFAULT_CONFIG_DIR
    _write_yaml(base / FILE_USERS, config.model_dump(mode="json"))


def save_domains_config(config: DomainsConfig, base: Path | None = None) -> None:
    """Save domains.yml."""
    base = base or DEFAULT_CONFIG_DIR
    _write_yaml(base / FILE_DOMAINS, config.model_dump(mode="json"))


def save_databases_config(
    config: DatabasesConfig, base: Path | None = None
) -> None:
    """Save databases.yml."""
    base = base or DEFAULT_CONFIG_DIR
    _write_yaml(base / FILE_DATABASES, config.model_dump(mode="json"))


def save_services_config(config: ServicesConfig, base: Path | None = None) -> None:
    """Save services.yml."""
    base = base or DEFAULT_CONFIG_DIR
    _write_yaml(base / FILE_SERVICES, config.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Save all configs
# ---------------------------------------------------------------------------


def save_config(config: FullConfig, base: Path | None = None) -> None:
    """Save all config files to a directory."""
    base = base or DEFAULT_CONFIG_DIR
    save_nopanel_config(config.nopanel, base)
    save_users_config(config.users, base)
    save_domains_config(config.domains, base)
    save_databases_config(config.databases, base)
    save_services_config(config.services, base)


# ---------------------------------------------------------------------------
# v1 JSON reading (for migration)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file and return a dict. Returns empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return data or {}


def read_v1_users(base: Path | None = None) -> dict[str, Any]:
    """Read v1 users.json."""
    base = base or DEFAULT_CONFIG_DIR
    return _read_json(base / V1_FILE_USERS)


def read_v1_nopanel(base: Path | None = None) -> dict[str, Any]:
    """Read v1 nopanel.json (global settings)."""
    base = base or DEFAULT_CONFIG_DIR
    return _read_json(base / V1_FILE_NOPANEL)


def read_v1_modules(base: Path | None = None) -> dict[str, Any]:
    """Read v1 modules.json (installed modules and their config)."""
    base = base or DEFAULT_CONFIG_DIR
    return _read_json(base / V1_FILE_MODULES)


def read_v1_user_domains(home_dir: Path) -> dict[str, Any]:
    """Read v1 per-user domains.json from ~/.nopanel/domains.json."""
    return _read_json(home_dir / ".nopanel" / "domains.json")


def read_v1_user_databases(home_dir: Path) -> dict[str, Any]:
    """Read v1 per-user databases.json from ~/.nopanel/databases.json."""
    return _read_json(home_dir / ".nopanel" / "databases.json")


# ---------------------------------------------------------------------------
# v1 → v2 config conversion (pure functions)
# ---------------------------------------------------------------------------


def convert_v1_users(v1_data: dict[str, Any]) -> UsersConfig:
    """Convert v1 users.json to v2 UsersConfig.

    v1 fields: name, fullname, email, login, admin, password
    v2 fields: fullname, email, login, admin, password
    """
    users: dict[str, User] = {}
    for username, raw in v1_data.items():
        if not isinstance(raw, dict):
            continue
        login_str = raw.get("login", "sftp")
        try:
            login = LoginType(login_str)
        except ValueError:
            login = LoginType.SFTP

        users[username] = User(
            fullname=raw.get("fullname", ""),
            email=raw.get("email", ""),
            login=login,
            admin=_parse_bool(raw.get("admin", False)),
            password=raw.get("password", ""),
        )
    return UsersConfig(users=users)


def convert_v1_domains(
    all_user_domains: dict[str, dict[str, Any]],
) -> DomainsConfig:
    """Convert v1 per-user domains.json files to v2 DomainsConfig.

    Args:
        all_user_domains: dict mapping username → v1 domains.json content
    """
    domains: dict[str, Domain] = {}
    for username, v1_domains in all_user_domains.items():
        if not isinstance(v1_domains, dict):
            continue
        for domain_name, raw in v1_domains.items():
            if not isinstance(raw, dict):
                continue
            # Only include domains with web=true
            web_val = raw.get("web", "false")
            if not _parse_bool(web_val):
                logger.warning("Skipping non-web domain '%s' (user: %s) — v2 only supports web domains", domain_name, username)
                continue

            php_val = raw.get("web_php", "false")
            php_version = None if _parse_bool_false(php_val) else php_val or None

            ssl_val = raw.get("web_ssl", "no")
            ssl_map = {"le": "auto", "self": "self", "no": "none"}
            ssl_str = ssl_map.get(ssl_val, "none")
            try:
                ssl = SSLMode(ssl_str)
            except ValueError:
                ssl = SSLMode.NONE

            aliases_str = raw.get("web_aliases", "")
            aliases = [a.strip() for a in aliases_str.split(",") if a.strip()] if aliases_str else []

            domains[domain_name] = Domain(
                user=username,
                php_version=php_version,
                ssl=ssl,
                aliases=aliases,
                web=True,
                docroot=raw.get("web_docroot", "public_html"),
            )
    return DomainsConfig(domains=domains)


def convert_v1_databases(
    all_user_databases: dict[str, dict[str, Any]],
) -> DatabasesConfig:
    """Convert v1 per-user databases.json files to v2 DatabasesConfig.

    Args:
        all_user_databases: dict mapping username → v1 databases.json content
    """
    databases: dict[str, Database] = {}
    for username, v1_dbs in all_user_databases.items():
        if not isinstance(v1_dbs, dict):
            continue
        for db_fullname, raw in v1_dbs.items():
            if not isinstance(raw, dict):
                continue
            dbuser = raw.get("dbuser", db_fullname)
            databases[db_fullname] = Database(
                user=username,
                dbuser=dbuser,
                password=raw.get("password", ""),
            )
    return DatabasesConfig(databases=databases)


def convert_v1_modules(v1_modules: dict[str, Any]) -> ServicesConfig:
    """Convert v1 modules.json to v2 ServicesConfig."""
    services = ServicesConfig()

    # MariaDB
    mariadb_data = v1_modules.get("mariadb", {})
    if isinstance(mariadb_data, dict) and _parse_bool(mariadb_data.get("installed")):
        root_pw = mariadb_data.get("password", "")
        services = services.model_copy(
            update={"mariadb": MariaDBService(root_password=root_pw)}
        )

    # PHP-FPM versions
    php_data = v1_modules.get("php-fpm", {})
    if isinstance(php_data, dict):
        php_services: dict[str, PHPFpmService] = {}
        for version, installed in php_data.items():
            if _parse_bool(installed):
                php_services[version] = PHPFpmService()
        if php_services:
            services = services.model_copy(update={"php": php_services})

    # Valkey (v1 might call it valkey or redis)
    valkey_data = v1_modules.get("valkey", {})
    if isinstance(valkey_data, dict) and _parse_bool(valkey_data.get("installed")):
        services = services.model_copy(
            update={"valkey": ValkeyService()}
        )

    return services


def convert_v1_nopanel(
    v1_nopanel: dict[str, Any],
    v1_users: dict[str, Any] | None = None,
) -> NopanelConfig:
    """Convert v1 nopanel.json to v2 NopanelConfig.

    Attempts to preserve useful settings from v1:
    - admin_email: extracted from the first v1 user with an email address
      (used by mod_md for ACME certificate registration)
    - mariadb.default_branch: from v1 nopanel.json mariadb section
    - php.additional_modules: from v1 nopanel.json php section
    """
    settings = Settings()

    # Try to extract admin email from first user with an email
    if v1_users:
        for user_data in v1_users.values():
            if isinstance(user_data, dict):
                email = user_data.get("email", "")
                if email:
                    settings = settings.model_copy(update={"admin_email": email})
                    break

    # MariaDB default branch
    mariadb_settings = MariaDBSettings()
    v1_mariadb = v1_nopanel.get("mariadb", {})
    if isinstance(v1_mariadb, dict):
        branch = v1_mariadb.get("default_branch", "")
        if branch:
            mariadb_settings = mariadb_settings.model_copy(update={"default_branch": branch})

    # PHP additional modules
    php_settings = PHPSettings()
    v1_php = v1_nopanel.get("php", {})
    if isinstance(v1_php, dict):
        modules_str = v1_php.get("additional_modules", "")
        if modules_str:
            modules = [m.strip() for m in modules_str.split(",") if m.strip()]
            if modules:
                php_settings = php_settings.model_copy(update={"additional_modules": modules})

    return NopanelConfig(
        settings=settings,
        mariadb=mariadb_settings,
        php=php_settings,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: Any) -> bool:
    """Parse various boolean representations from v1 JSON."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def _parse_bool_false(value: Any) -> bool:
    """Return True if value represents 'false' (for php=false check)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value.lower() in ("false", "0", "no", "off", "")
    return False


# ---------------------------------------------------------------------------
# Default config creation
# ---------------------------------------------------------------------------


def create_default_config() -> FullConfig:
    """Create a default FullConfig for fresh installs."""
    return FullConfig(
        nopanel=NopanelConfig(),
        users=UsersConfig(),
        domains=DomainsConfig(),
        databases=DatabasesConfig(),
        services=ServicesConfig(
            web=WebService(),
            php={
                "8.2": PHPFpmService(image="nopanel/php-8.2:latest"),
                "8.3": PHPFpmService(image="nopanel/php-8.3:latest"),
                "8.4": PHPFpmService(image="nopanel/php-8.4:latest"),
                "8.5": PHPFpmService(image="nopanel/php-8.5:latest"),
            },
            mariadb=MariaDBService(),
            valkey=ValkeyService(),
        ),
    )


def init_config_dir(base: Path | None = None) -> None:
    """Initialize a config directory with default config files."""
    base = base or DEFAULT_CONFIG_DIR
    base.mkdir(parents=True, exist_ok=True)
    config = create_default_config()
    save_config(config, base)
