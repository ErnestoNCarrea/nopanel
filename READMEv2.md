# noPanel v2

Containerized web hosting control panel CLI.

## Overview

noPanel v2 is a rewrite of the noPanel CLI tool as a containerized Python application.
It manages Apache, PHP-FPM, MariaDB, and Valkey containers via Docker Compose, with
a single `commit` command to apply all configuration changes.

## Installation

### Container (noPanel v2)

```bash
pip install -e ".[dev]"
```

### Host wrapper script

Install `share/host/nopanel` to `/usr/local/bin/nopanel` on the host:

```bash
install -m 755 share/host/nopanel /usr/local/bin/nopanel
```

The host wrapper proxies all commands to the nopanel container via `docker exec`
and handles host-side operations (system user management). It must be run as root
or via sudo (see `share/etc/sudoers.d/nopanel`).

## Usage

```bash
# Initialize config directory
nopanel init

# Add a user (config only — system user created on next commit)
nopanel user add --user alice --password mypassword --fullname "Alice Smith"

# Add a domain
nopanel domain add --domain example.com --user alice --php 8.2 --ssl auto

# Add a database
nopanel database add --user alice --db blog --password dbpassword

# Apply all changes (auto-detects nsenter or pending-commands backend)
nopanel commit

# Commit without host operations (skip user management)
nopanel commit --no-host

# Run pending host commands separately (pending-commands backend only)
nopanel host-commands --run

# Check status
nopanel status

# Migrate from v1
nopanel migrate --pre-check
nopanel migrate --dry-run
nopanel migrate
```

## CLI Commands

```
nopanel init                              Initialize config directory
nopanel status                            Show overall status and pending changes
nopanel commit [--dry-run] [--service S] [--no-docker] [--no-host]  Apply all pending configuration changes

nopanel user add --user U --password P [--fullname F] [--email E] [--login ssh|sftp|no] [--admin]
nopanel user mod --user U [--password P] [--fullname F] [--email E] [--login ssh|sftp|no] [--admin]
nopanel user remove --user U
nopanel user list
nopanel user host-commands [--raw]       Show host commands (from container)

nopanel host-commands                     Show pending system user commands
nopanel host-commands --run               Run pending host commands on the host

nopanel domain add --domain D --user U [--php V] [--ssl auto|self|none] [--aliases A]
nopanel domain mod --domain D [--php V] [--ssl auto|self|none] [--aliases A]
nopanel domain remove --domain D
nopanel domain list

nopanel database add --user U --db D [--dbuser U] --password P
nopanel database mod --user U --db D [--dbuser U] [--password P]
nopanel database remove --user U --db D
nopanel database list

nopanel service up [SERVICES...]
nopanel service down
nopanel service stop [SERVICES...]
nopanel service restart [SERVICES...]
nopanel service status
nopanel service pull [SERVICES...]

nopanel php add-module --version V MODULE
nopanel php remove-module --version V MODULE
nopanel php list-modules --version V
nopanel php list-versions

nopanel export [--output FILE]
nopanel import --file FILE [--dry-run] [--force]

nopanel migrate [--dry-run] [--pre-check] [--service S] [--all] [--reconvert] [--diff]
```

## Architecture

- **Config**: YAML files in `/etc/nopanel/` (nopanel.yml, users.yml, domains.yml, databases.yml, services.yml)
- **Commit engine**: Diffs desired vs committed state, generates configs, applies changes, snapshots
- **Docker**: All services run as Docker containers, managed via docker compose
- **Templates**: Jinja2 templates for Apache vhosts, PHP-FPM pools, docker-compose.yml

### Project Structure

```
nopanel/                  Python package
  models.py               Pydantic v2 models (User, Domain, Database, Config)
  config.py               YAML load/save, v1 JSON reading, v1→v2 conversion
  state.py                Committed state I/O, diff engine
  docker_manager.py       Docker Compose CLI wrapper
  host_ops.py             Pluggable host operations backend (HostOps protocol)
  templates.py            Jinja2 template rendering functions
  commit.py               Commit engine (diff → generate → apply → reload → snapshot)
  migrate.py              Migration engine (v1→v2, RHEL-only)
  cli.py                  Typer CLI app
  commands/               CLI subcommand modules
  services/               Service modules (web, php, database, cache)
  templates/              Jinja2 template files
docker/                   Static Dockerfiles and Apache config
  php-8.2/Dockerfile      Default PHP 8.2 FPM image
  php-8.3/Dockerfile      Default PHP 8.3 FPM image
  php-8.4/Dockerfile      Default PHP 8.4 FPM image
  php-8.5/Dockerfile      Default PHP 8.5 FPM image
  apache/httpd.conf.j2    Base Apache config template
tests/                    Unit tests
docs/                     Documentation
Dockerfile                Multi-stage build for nopanel container
docker-compose.yml        Compose file for running nopanel container
pyproject.toml            Project metadata and dependencies
```

### Key Design Decisions

- **Functional core**: Config parsing, diffing, template rendering are pure functions
- **Dependency injection**: DockerManager, SQLExecutor, FileWriter, SystemOps, HostOps are protocols
- **Immutable models**: All Pydantic models are frozen for safe diffing
- **Plaintext DB passwords**: Stored in YAML with strict file permissions (chmod 600)
- **RHEL-only migration**: v1→v2 migration supports RHEL-based hosts only
- **Dual logging**: Docker json-file driver + volume-mounted per-domain Apache logs
- **Host networking during migration**: Configurable network_mode (host or bridge)
- **mod_md for SSL**: ACME certificates with global admin_email setting
- **Pluggable host operations**: Host system user management (`useradd`,
  `chpasswd`, `chsh`, `userdel`) and service management (`systemctl`) use a
  pluggable `HostOps` backend with three implementations:
  - **NsenterHostOps** (default when available): executes commands directly on
    the host via `nsenter -t 1 -m -u -i -n --`, requiring `--privileged` and
    `--pid=host` on the nopanel container. No host-side agent needed.
  - **PendingCommandsHostOps** (fallback): queues commands to
    `pending-host-cmds.sh` for later execution by the host wrapper script
    (`share/host/nopanel`). Commands are validated against a whitelist and
    logged to `/var/log/nopanel/host-commands.log`.
  - **NoOpHostOps**: no-op for `--no-host` or dry-run mode.
  The backend is auto-detected at runtime by `auto_detect_host_ops()`. Removing
  `--privileged` and `--pid=host` from the compose file automatically falls back
  to the pending-commands workflow.

## Testing

```bash
pytest
```

Unit tests covering models, config I/O, state/diff, templates, services, commit engine, migration (including per-service, reconvert, diff, image pull, config generation, and post-migration cleanup), Docker manager, host operations (nsenter, pending-commands, no-op backends), and CLI.

## Documentation

- [Migration Guide](docs/migration.md)
