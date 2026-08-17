# pyInfra Backend — Implementation

## Status: Implemented

pyInfra 3.10+ is a required dependency. The host operations architecture
uses two orthogonal axes: **transport** (how commands reach the host) and
**strategy** (how operations are expressed).

## Architecture

```
Transport (how to reach the host):
  LocalTransport     — direct subprocess (nopanel on host)
  NsenterTransport   — nsenter -t 1 -m -u -i -n -- (privileged container)

Strategy (how to execute operations):
  PyInfraHostOps     — declarative, idempotent via pyInfra

Combined: PyInfraHostOps(transport=LocalTransport())
          PyInfraHostOps(transport=NsenterTransport())

Special cases (not transport/strategy based):
  PendingCommandsHostOps — queues to file (no host access)
  NoOpHostOps            — dry-run / --no-host
```

## Files

| File | Purpose |
|---|---|
| `nopanel/host_ops.py` | `HostTransport` protocol, `LocalTransport`, `NsenterTransport`, `detect_transport()`, `HostOps` protocol, `PendingCommandsHostOps`, `NoOpHostOps`, `auto_detect_host_ops()` |
| `nopanel/pyinfra_backend.py` | `PyInfraHostOps` (strategy), `NsenterConnector` (pyInfra connector for nsenter), `PyInfraSystemOps` (SystemOps adapter) |
| `nopanel/orchestrator.py` | `build_inventory()` — builds pyInfra Inventory + Config from transport detection |
| `tests/test_host_ops.py` | Transport + pending-commands + no-op tests |
| `tests/test_pyinfra_host_ops.py` | 27 pyInfra tests (mock-based) |

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

## Transport Details

| Transport | pyInfra target | Use case |
|---|---|---|
| `LocalTransport` | `@local` | nopanel runs directly on host |
| `NsenterTransport` | `@nsenter` (custom connector) | Privileged container with `--pid=host` |

The `@nsenter` connector subclasses pyInfra's `LocalConnector` and prefixes
every command with `nsenter -t 1 -m -u -i -n --`. It is registered
dynamically at runtime via `_register_nsenter_connector()`.

## Auto-detection

`auto_detect_host_ops()`:

1. If `prefer_pyinfra=True`: calls `detect_transport()` → creates
   `PyInfraHostOps(transport=detected_transport)`.
2. Otherwise: falls back to `PendingCommandsHostOps`.

`detect_transport()` tries nsenter first, then local, then returns `None`.

pyInfra is not tried by default because `@local` transport requires sudo,
which may prompt for a password in non-interactive contexts.

## Design Notes

- pyInfra's `server.user` `password` parameter expects a pre-encrypted hash.
  We use `server.shell` with `chpasswd` for plaintext passwords instead.
- Each operation creates a fresh pyInfra State (connect → add_op → run_ops).
  This matches the one-shot nature of nopanel commits.
- `PyInfraSystemOps` reuses the same MariaDB version detection logic
  (checks v2 config, docker inspect, then host RPM via pyInfra facts).
- The `NsenterConnector` is a proper pyInfra connector (subclass of
  `LocalConnector`), not a wrapper. pyInfra's operation scheduling, fact
  gathering, and sudo handling all work transparently through it.
