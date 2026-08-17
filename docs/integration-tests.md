# Integration Test Plan

## Goal

End-to-end tests on real AlmaLinux 9/10 VMs via KVM + cloud-init.

## Architecture

```
tests/integration/
  conftest.py            # fixtures, markers, config
  vm_manager.py          # VM lifecycle (virt-install, snapshot, destroy)
  cloudinit.py           # Generate seed ISO via mkisofs
  ssh_runner.py          # SSH exec + SCP
  test_v2_install.py     # Fresh v2 install + operations
  test_v1_migration.py   # V1 install → migrate → verify
  test_multiuser.py      # Multi-user, multi-site
  images/                # Cached qcow2 cloud images
```

## Test Matrix

| Test | VM | Steps | Est. runtime |
|---|---|---|---|
| V2 install | AlmaLinux 9/10 | Boot → Docker → build → init → add users/domains/dbs → commit → verify | 5-10 min |
| V1 migration | AlmaLinux 9/10 | Boot → install v1 stack → create v1 configs → migrate → verify | 10-20 min |
| Multi-user | AlmaLinux 9/10 | Snapshot → 5 users × 2-3 domains × 1-2 dbs → commit → verify | 5-10 min |

## VM Strategy

1. Download qcow2 cloud image (cached once)
2. Create COW overlay per test class
3. Cloud-init: install Docker, create user, inject SSH key
4. `virt-install --import`, poll for SSH (≤120s)
5. Snapshot after boot+Docker install → revert between tests
6. Destroy VM + overlay after class

## Prerequisites

| Package | Status | Action |
|---|---|---|
| `virt-install` | Installed | — |
| `qemu-img` | Installed | — |
| `mkisofs` | Installed | — |
| `python3-paramiko` | Missing | `pip install paramiko` |
| libvirt NAT network | Missing | Create in conftest |
| `cloud-localds` | Missing | Optional, use `mkisofs` instead |

## Implementation Order

1. `vm_manager.py` + `cloudinit.py` + `ssh_runner.py` — VM lifecycle layer
2. `conftest.py` — fixtures (`almalinux9_vm`, `almalinux10_vm`, session-scoped)
3. `test_v2_install.py` — simplest, validates the whole stack
4. `test_multiuser.py` — extends v2 install with data-driven scenarios
5. `test_v1_migration.py` — hardest, needs v1 stack replication
6. CI integration — `@pytest.mark.integration` marker, opt-in

## Effort

| Phase | Days |
|---|---|
| VM management layer | 1-2 |
| V2 install test | 1 |
| Multi-user test | 1 |
| V1 migration test | 2-3 |
| CI integration | 0.5 |
| **Total** | **5-7** |
