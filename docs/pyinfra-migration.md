# pyInfra Backend — Implementation

## Status: Implemented

pyInfra 3.10+ is a required dependency. `PyInfraHostOps` and `PyInfraSystemOps` are implemented and tested (27 tests, mock-based).

## Files

| File | Purpose |
|---|---|
| `nopanel/pyinfra_backend.py` | `PyInfraHostOps` (HostOps protocol) + `PyInfraSystemOps` (SystemOps adapter) |
| `nopanel/orchestrator.py` | `build_inventory()` — builds pyInfra Inventory + Config from nopanel config |
| `nopanel/host_ops.py` | `auto_detect_host_ops(prefer_pyinfra=True)` — pyInfra detection branch |
| `tests/test_pyinfra_host_ops.py` | 27 tests (mock-based, no real pyInfra connection needed) |

## Operation Mapping

| HostOps method | pyInfra operation |
|---|---|
| `create_user` | `server.user(..., create_home=True)` + `server.shell(chpasswd)` |
| `set_user_password` | `server.shell(["echo 'user:pass' \| chpasswd"])` |
| `set_user_shell` | `server.user(..., shell=...)` |
| `delete_user` | `server.user(..., present=False)` + `server.shell(rm home)` |
| `stop_service` | `systemd.service(..., running=False)` |
| `start_service` | `systemd.service(..., running=True)` |
| `disable_service` | `systemd.service(..., enabled=False)` |
| `detect_os` | `get_facts(Os)` |
| `query_package_version` | `get_facts(RpmPackage, package)` |
| `query_packages` | `get_facts(RpmPackages)` + glob filter |

## Transport

| Mode | Config | Use case |
|---|---|---|
| `@local` | `ssh_target=None` (default) | Privileged container with `--pid=host` |
| SSH | `ssh_target="user@host:port"` | Remote host, unprivileged container |

## Auto-detection

`auto_detect_host_ops()` tries backends in this order:

1. **pyInfra** — only if `prefer_pyinfra=True` (avoids unexpected sudo prompts)
2. **nsenter** — if `nsenter -t 1 -m -- true` succeeds
3. **pending-commands** — fallback

pyInfra is not tried by default because `@local` transport requires sudo, which may prompt for a password in non-interactive contexts.

## pyInfra vs nsenter

| Aspect | nsenter | pyInfra |
|---|---|---|
| Execution | Direct, in-process | Declarative, idempotent |
| Container reqs | `--privileged --pid=host` | SSH or `@local` (nsenter) |
| Host reqs | None | SSH server (or `@local`) |
| Idempotency | No (manual checks) | Yes (built-in) |
| Dry-run | Manual | `--dry` flag built-in |
| Audit trail | Manual logging | Operation diff output |
| Complexity | Low | Medium |

## Design Notes

- pyInfra's `server.user` `password` parameter expects a pre-encrypted hash. We use `server.shell` with `chpasswd` for plaintext passwords instead.
- Each operation creates a fresh pyInfra State (connect → add_op → run_ops → disconnect). This is simpler than maintaining a long-lived connection and matches the one-shot nature of nopanel commits.
- `PyInfraSystemOps` reuses the same MariaDB version detection logic as `NsenterSystemOps` (checks v2 config, docker inspect, then host RPM via pyInfra facts).
