#!/bin/bash
# Run all nopanel tests: unit tests first, then integration tests.
#
# Unit tests are fast (seconds) and need no external resources.
# Integration tests boot a real AlmaLinux 9 KVM VM via libvirt and run
# nopanel end-to-end over SSH — they require passwordless sudo for
# virsh/virt-install/iptables (see tests/integration/nopanel-integration.sudoers).
#
# Usage:
#   ./run-tests.sh              # unit + integration
#   ./run-tests.sh --unit-only  # skip integration
#   ./run-tests.sh --int-only   # skip unit
#   ./run-tests.sh --help

set -euo pipefail

cd "$(dirname "$0")"

RUN_UNIT=1
RUN_INT=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --unit-only)  RUN_INT=0;  shift ;;
        --int-only)   RUN_UNIT=0; shift ;;
        --help|-h)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1 ;;
    esac
done

# -- Prerequisites ----------------------------------------------------------

if [[ "$RUN_INT" -eq 1 ]]; then
    for bin in virt-install virsh qemu-img mkisofs; do
        if ! command -v "$bin" >/dev/null 2>&1; then
            echo "ERROR: $bin not found — integration tests need libvirt tooling" >&2
            exit 1
        fi
    done
    if ! sudo -n virsh list >/dev/null 2>&1; then
        echo "ERROR: passwordless sudo for virsh is required." >&2
        echo "Install: sudo install -m 440 tests/integration/nopanel-integration.sudoers /etc/sudoers.d/nopanel-integration" >&2
        exit 1
    fi
fi

# -- Unit tests -------------------------------------------------------------

if [[ "$RUN_UNIT" -eq 1 ]]; then
    echo "=== Unit tests ==="
    python -m pytest --tb=short -q
    echo
fi

# -- Integration tests ------------------------------------------------------

if [[ "$RUN_INT" -eq 1 ]]; then
    echo "=== Integration tests (boots KVM VM — this takes a while) ==="
    python -m pytest -m integration --tb=short -v
fi
