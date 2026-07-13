# noPanel

A panel-less web panel.

noPanel is a multi-user, CLI-only web server manager, with Apache, Let's Encrypt (mod_md), MariaDB and multi-version PHP support.

## v2 (current)

Containerized Python CLI tool. Manages Apache, PHP-FPM, MariaDB, and Valkey containers via Docker Compose, with a single `commit` command to apply all configuration changes.

### Installation

```bash
pip install -e ".[dev]"
```

### Usage

```bash
# Initialize config directory
nopanel init

# Add a user
nopanel user add --user alice --password mypassword --fullname "Alice Smith"

# Add a domain
nopanel domain add --domain example.com --user alice --php 8.2 --ssl auto

# Add a database
nopanel database add --user alice --db blog --password dbpassword

# Apply all changes
nopanel commit

# Check status
nopanel status

# Migrate from v1
nopanel migrate --pre-check
nopanel migrate --dry-run
nopanel migrate
```

### Architecture

- **Config**: YAML files in `/etc/nopanel/` (nopanel.yml, users.yml, domains.yml, databases.yml, services.yml)
- **Commit engine**: Diffs desired vs committed state, generates configs, applies changes, snapshots
- **Docker**: All services run as Docker containers, managed via docker compose
- **Templates**: Jinja2 templates for Apache vhosts, PHP-FPM pools, docker-compose.yml

### Testing

```bash
pytest
```

### Documentation

- [Migration Guide](docs/migration.md)

## v1 (legacy)

Written entirely in Bash, with minimal dependencies.

### noPanel command line interface

```bash
nopanel [--output json|plain] [--interactive [yes|no]] SUB_COMMAND
```

Where SUB_COMMAND is:

```bash
[n]     ver
[id]    init
[Ri]    commit

[n]     module list

[Rid]   module apache install
[Rnd]   module apache reload

[Rid]   module mariadb install
[Rid]   module mariadb upgrade
[Rid]   module mariadb wipe --force

[n]     user list
[c]     user add --user USERNAME --password PASSWORD [--email EMAIL] [--login ssh|sftp|no] \
            [--fullname FULL_NAME] [--admin [yes|no]]
[ic]    user mod --user USERNAME [--password PASSWORD] [--email EMAIL] [--login ssh|sftp|no] \
            [--fullname FULL_NAME] [--admin [yes|no]]
[c]     user remove --user USERNAME --force [--delete [--no-backup]]
[Ri]    user commit [--user USER]

[Ri]    web commit
[n]     web domain list --user USER
[c]     web domain add --user USER --domain DOMAIN [--aliases ALIASES] [--php VERSION|no] [--ssl le|custom|self|no]
[ic]    web domain mod --user USER --domain DOMAIN [--aliases ALIASES] [--php VERSION|no] [--ssl le|custom|self|no]
[c]     web domain remove --user USER --domain DOMAIN --force
[Ri]    web domain commit [--user USER] [--domain DOMAIN]

[n]     database list
[c]     database add --user USER --db DBNAME [--dbuser DBUSER] --password PASSWORD
[ic]    database mod --user USER --db DBNAME [--dbuser DBUSER] [--password PASSWORD]
[c]     database remove --user USER --db DBNAME
[Ri]    database commit [--user USER] [--db DBNAME]

[n]     module php-fpm info
[Ri]    module php-fpm install
[Ri]    module php-fpm add [--version MAJOR.MINOR]
[Ri]    module php-fpm del [--version MAJOR.MINOR]

[n]     export [--output FILE] [--users] [--domains] [--databases]
[Ri]    import --file FILE [--users] [--domains] [--databases] [--skip-existing] [--dry-run] [--default-password PASS]
```

Ref.:
[n] Causes no change
[R] Needs root always
[i] Idempotent
[d] May disrupt service
[c] Takes effect on commit

### BYOJ (Bring Your Own Json)

/etc/nopanel/users.json (root only)
~/.nopanel/domains.json
~/.nopanel/databases.json

Just edit and then run `nopanel commit --reload` to apply changes.

### Export/Import

Use `nopanel export` and `nopanel import` to backup and restore your entire noPanel configuration.

```bash
# Export everything to a JSON file
nopanel export --output=backup.json

# Import from a backup file
nopanel import --file=backup.json --dry-run  # test first
nopanel import --file=backup.json --users
nopanel commit
nopanel import --file=backup.json --skip-existing
```

See [docs/export-import.md](docs/export-import.md) for complete documentation.
