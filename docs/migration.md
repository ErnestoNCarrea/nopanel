# noPanel v2 Migration Guide

This guide covers migrating from noPanel v1 to v2 on the same host.

## Prerequisites

- **RHEL-based host only**: Migration supports RHEL, CentOS, AlmaLinux, and Rocky Linux.
- **Docker installed**: Docker Engine and Docker Compose must be available.
- **Root access**: Migration requires root to stop/start services and manage configs.
- **v1 running**: The v1 noPanel installation must be present and running.

## Migration Overview

Migration converts a running v1 server to v2 on the same host, preserving all data
with minimal downtime. The process:

1. **Pre-migration check** — Detect OS, v1 installation, MariaDB version, PHP versions
2. **Config conversion** — Convert v1 JSON configs to v2 YAML configs
3. **Service cutover** — Stop host services, start containers (one at a time)
4. **Verification** — Confirm all services are running in containers

### Migration Order

Services are migrated in this order to minimize dependencies:

1. **Valkey** (no dependencies)
2. **MariaDB** (depends on sockets)
3. **PHP-FPM** (depends on MariaDB sockets)
4. **Apache** (depends on PHP-FPM sockets)

### Data Preservation

No data is moved during migration. All data directories are volume-mounted directly:

- `/home` — web content, user data
- `/var/lib/mysql` — MariaDB data
- `/var/log/nopanel/apache` — Apache logs
- `/etc/nopanel/pki` — SSL certificates (mod_md store)

## Running Migration

### Step 1: Pre-migration check

```bash
nopanel migrate --pre-check
```

This verifies:
- OS is RHEL-based
- v1 installation is detected
- MariaDB version is identified
- PHP versions are detected

### Step 2: Dry run

```bash
nopanel migrate --dry-run
```

This converts all v1 configs to v2 format and displays the result without
making any changes. Review the output carefully.

### Step 3: Full migration

```bash
nopanel migrate
```

This will:
1. Save converted v2 configs to `/etc/nopanel/`
2. Generate docker-compose.yml and service configs
3. Stop and disable host services (httpd, mariadb, valkey, php-fpm)
4. Start service containers via docker compose
5. Verify all services are running

### Rollback

If migration fails or services don't work:

```bash
# Stop all containers
nopanel service down

# Re-enable and start host services
systemctl enable --now httpd mariadb valkey
systemctl enable --now php82-php-fpm  # adjust version as needed
```

Since no data is moved, rollback is trivial — stop containers, start host services.

## Post-migration

After successful migration:

1. Run `nopanel commit` to apply any remaining config changes
2. Verify websites load correctly
3. Check `nopanel status` for pending changes
4. Consider transitioning from `host` to `bridge` networking:
   ```bash
   # Edit /etc/nopanel/nopanel.yml: set network_mode: bridge
   nopanel commit
   ```

## Key Differences v1 → v2

| Aspect | v1 | v2 |
|--------|----|----|
| Config format | JSON | YAML |
| Config location | `/etc/nopanel/*.json` + `~/.nopanel/*.json` | `/etc/nopanel/*.yml` (centralized) |
| Services | Host systemd services | Docker containers |
| PHP-FPM | OS packages (Remi) | Custom Docker images |
| SSL | getssl | mod_md (ACME) |
| Apply mechanism | Per-entity commit | Global `nopanel commit` |
| Networking | Host only | Host or bridge (configurable) |
