"""MariaDB database service — SQL generation and execution.

Pure functions for generating SQL statements from database config.
SQL execution is delegated to an injectable SQLExecutor protocol.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any, Protocol

from nopanel.models import Database, FullConfig

# ---------------------------------------------------------------------------
# SQL Executor protocol (injectable for testing)
# ---------------------------------------------------------------------------


class SQLExecutor(Protocol):
    """Protocol for executing SQL queries against MariaDB."""

    def execute(self, query: str) -> Any:
        """Execute a SQL query."""
        ...


# ---------------------------------------------------------------------------
# SQL generation (pure functions)
# ---------------------------------------------------------------------------


def _sql_identifier_escape(identifier: str) -> str:
    """Escape backticks for safe use in backtick-quoted SQL identifiers."""
    return identifier.replace("`", "``")


def create_database_sql(db_name: str) -> str:
    """Generate CREATE DATABASE SQL."""
    escaped = _sql_identifier_escape(db_name)
    return f"CREATE DATABASE IF NOT EXISTS `{escaped}`"


def _sql_escape(value: str) -> str:
    """Escape single quotes and backslashes for safe use in SQL string literals."""
    return value.replace("\\", "\\\\").replace("'", "''")


def grant_user_sql(db_name: str, db_user: str, password: str) -> list[str]:
    """Generate GRANT SQL statements for a database user.

    Raises ValueError if password is empty — a database without credentials
    is a misconfiguration that should surface explicitly, not silently skip.
    """
    if not password:
        raise ValueError(
            f"Cannot create GRANT for database '{db_name}' user '{db_user}': "
            "empty password"
        )
    statements = []
    escaped_pw = _sql_escape(password)
    escaped_db = _sql_identifier_escape(db_name)
    escaped_user = _sql_identifier_escape(db_user)
    statements.append(
        f"GRANT ALL ON `{escaped_db}`.* TO `{escaped_user}`@`%` IDENTIFIED BY '{escaped_pw}'"
    )
    statements.append(
        f"GRANT ALL ON `{escaped_db}`.* TO `{escaped_user}`@`localhost` IDENTIFIED BY '{escaped_pw}'"
    )
    return statements


def drop_database_sql(db_name: str) -> str:
    """Generate DROP DATABASE SQL."""
    escaped = _sql_identifier_escape(db_name)
    return f"DROP DATABASE IF EXISTS `{escaped}`"


def drop_user_sql(db_user: str) -> str:
    """Generate DROP USER SQL."""
    escaped = _sql_identifier_escape(db_user)
    return f"DROP USER IF EXISTS `{escaped}`"


def full_db_name(user: str, db_name: str) -> str:
    """Generate the full database name (user_dbname convention from v1)."""
    return f"{user}_{db_name}"


def full_db_user(user: str, db_user: str) -> str:
    """Generate the full database username (user_dbuser convention from v1)."""
    return f"{user}_{db_user}"


# ---------------------------------------------------------------------------
# SQL execution from config diff
# ---------------------------------------------------------------------------


def apply_database_changes(
    added: list[Database],
    modified: list[tuple[Database, Database]],  # (old, new)
    deleted: list[Database],
    db_names: list[str],  # full db names for each corresponding Database
    executor: SQLExecutor,
) -> list[str]:
    """Apply database changes via SQL.

    Args:
        added: New databases to create
        modified: (old, new) tuples for modified databases
        deleted: Databases to drop
        db_names: Full database names corresponding to the above lists.
            Must contain len(added) + len(modified) + len(deleted) entries,
            in that order.
        executor: SQLExecutor to run queries

    Returns:
        List of executed SQL statements (for logging).
    """
    executed: list[str] = []

    expected_len = len(added) + len(modified) + len(deleted)
    if len(db_names) != expected_len:
        raise ValueError(
            f"db_names has {len(db_names)} entries, expected {expected_len} "
            f"({len(added)} added + {len(modified)} modified + {len(deleted)} deleted)"
        )

    idx = 0

    # Create new databases
    for db in added:
        full_name = db_names[idx]
        idx += 1
        sql = create_database_sql(full_name)
        executor.execute(sql)
        executed.append(sql)

        full_user = full_db_user(db.user, db.dbuser)
        for grant_sql in grant_user_sql(full_name, full_user, db.password):
            executor.execute(grant_sql)
            executed.append(grant_sql)

    # Modify existing databases (password or dbuser changes)
    for old_db, new_db in modified:
        full_name = db_names[idx]
        idx += 1

        # Drop old user and re-grant with new credentials
        old_user = full_db_user(old_db.user, old_db.dbuser)
        drop_sql = drop_user_sql(old_user)
        executor.execute(drop_sql)
        executed.append(drop_sql)

        new_user = full_db_user(new_db.user, new_db.dbuser)
        for grant_sql in grant_user_sql(full_name, new_user, new_db.password):
            executor.execute(grant_sql)
            executed.append(grant_sql)

    # Drop deleted databases
    for db in deleted:
        full_name = db_names[idx]
        idx += 1
        sql = drop_database_sql(full_name)
        executor.execute(sql)
        executed.append(sql)

        full_user = full_db_user(db.user, db.dbuser)
        drop_sql = drop_user_sql(full_user)
        executor.execute(drop_sql)
        executed.append(drop_sql)

    return executed


# ---------------------------------------------------------------------------
# MariaDB service manager
# ---------------------------------------------------------------------------


class DatabaseService:
    """MariaDB container service manager."""

    def __init__(self, docker_manager: Any = None, sql_executor: SQLExecutor | None = None) -> None:
        self._docker = docker_manager
        self._sql = sql_executor

    @property
    def name(self) -> str:
        return "mariadb"

    def generate_config(self, config: FullConfig) -> dict[str, str]:
        """MariaDB doesn't need generated config files — managed via SQL."""
        return {}

    def start(self) -> Any:
        if self._docker:
            return self._docker.compose_up(["mariadb"])
        return None

    def stop(self) -> Any:
        if self._docker:
            return self._docker.compose_stop(["mariadb"])
        return None

    def restart(self) -> Any:
        if self._docker:
            return self._docker.compose_restart(["mariadb"])
        return None

    def status(self) -> dict[str, Any]:
        if self._docker:
            return self._docker.get_container_status("mariadb") or {}
        return {}

    def execute_sql(self, query: str) -> Any:
        """Execute a SQL query against MariaDB."""
        if self._sql:
            return self._sql.execute(query)
        raise RuntimeError("No SQL executor configured")


class RealSQLExecutor:
    """Default SQL executor using the mariadb client via Unix socket."""

    def __init__(
        self,
        root_password: str = "",
        socket: str = "/var/lib/mysql/mysql.sock",
    ) -> None:
        self._root_password = root_password
        self._socket = socket

    def execute(self, query: str) -> Any:
        cmd = ["mariadb", "-u", "root", "--socket", self._socket]
        if self._root_password:
            # Use --defaults-extra-file with a temp file to avoid leaking
            # the password via MYSQL_PWD env var (visible in /proc/<pid>/environ).
            fd, tmp_path = tempfile.mkstemp(suffix=".cnf", prefix="nopanel_")
            try:
                os.chmod(tmp_path, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(f"[client]\npassword={self._root_password}\n")
                cmd.extend(["--defaults-extra-file", tmp_path])
                result = subprocess.run(cmd, input=query, capture_output=True, text=True)
            finally:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
        else:
            result = subprocess.run(cmd, input=query, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"SQL execution failed: {result.stderr.strip()}")
        return result.stdout
