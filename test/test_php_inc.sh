#!/bin/bash
# Tests for src/lib/php.inc
# Covers: fallback path, remi live query path, default version logic

cd "$(dirname "$0")/.." || exit 1

PASS=0
FAIL=0

_ok() {
    echo "✓ $1"
    (( PASS++ ))
}

_fail() {
    echo "✗ $1"
    (( FAIL++ ))
}

_assert_eq() {
    local label="$1" got="$2" expected="$3"
    if [[ "$got" == "$expected" ]]; then
        _ok "$label (got: '$got')"
    else
        _fail "$label (expected: '$expected', got: '$got')"
    fi
}

_assert_nonempty() {
    local label="$1" val="$2"
    if [[ -n "$val" ]]; then
        _ok "$label (got: '$val')"
    else
        _fail "$label (empty)"
    fi
}

_assert_in_list() {
    local label="$1" needle="$2" haystack="$3"
    if [[ " $haystack " == *" $needle "* ]]; then
        _ok "$label ('$needle' found in list)"
    else
        _fail "$label ('$needle' not found in '$haystack')"
    fi
}

# Create a temp dir for stub scripts and prepend to PATH so they override the
# real dnf binary (timeout spawns subprocesses, so bash function stubs don't work)
STUB_DIR=$(mktemp -d)
trap 'rm -rf "$STUB_DIR"' EXIT
PATH="$STUB_DIR:$PATH"

_stub_dnf() {
    # Write a dnf stub script; args: repolist_output repoquery_output
    cat > "$STUB_DIR/dnf" <<EOF
#!/bin/bash
case "\$1" in
    repolist)   printf '%s\n' ${1@Q} ;;
    repoquery)  printf '%s\n' ${2@Q} ;;
esac
EOF
    # Rewrite properly using positional args passed in
    local repolist_out="$1" repoquery_out="$2"
    cat > "$STUB_DIR/dnf" <<SCRIPT
#!/bin/bash
case "\$1" in
    repolist)
        printf '%s\n' $(printf '%q' "$repolist_out")
        ;;
    repoquery)
        printf '%s\n' $(printf '%q' "$repoquery_out")
        ;;
esac
SCRIPT
    chmod +x "$STUB_DIR/dnf"
}

_remove_stub() {
    rm -f "$STUB_DIR/dnf"
}

# Helper to source php.inc in a clean subshell and print the two vars
_source_php_inc() {
    local os_base="$1"
    bash --norc --noprofile -c "
        PATH='$PATH'
        OS_BASE='$os_base'
        source src/lib/php.inc
        echo \"SUPPORTED=\$PHP_SUPPORTED_VERSIONS\"
        echo \"DEFAULT=\$PHP_DEFAULT_VERSION\"
    "
}

echo "=== php.inc tests ==="
echo ""

# --- 1. Fallback path: OS_BASE != rhel ---
echo "-- Fallback path (OS_BASE=debian) --"
_remove_stub
out=$(_source_php_inc debian)
supported=$(grep '^SUPPORTED=' <<<"$out" | cut -d= -f2-)
default=$(grep  '^DEFAULT='   <<<"$out" | cut -d= -f2-)
_assert_eq "PHP_SUPPORTED_VERSIONS uses fallback" \
    "$supported" '5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5'
_assert_eq "PHP_DEFAULT_VERSION is latest-1 of fallback (8.4)" \
    "$default" "8.4"
echo ""

# --- 2. Fallback path: OS_BASE=rhel, no dnf in PATH ---
echo "-- Fallback path (OS_BASE=rhel, dnf not in PATH) --"
_remove_stub
out=$(bash --norc --noprofile -c "
    PATH=''   # empty PATH: bash builtins still work, no external commands found
    OS_BASE=rhel
    source src/lib/php.inc
    echo \"SUPPORTED=\$PHP_SUPPORTED_VERSIONS\"
    echo \"DEFAULT=\$PHP_DEFAULT_VERSION\"
")
supported=$(grep '^SUPPORTED=' <<<"$out" | cut -d= -f2-)
default=$(grep  '^DEFAULT='   <<<"$out" | cut -d= -f2-)
_assert_eq "PHP_SUPPORTED_VERSIONS uses fallback when dnf absent" \
    "$supported" '5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5'
_assert_eq "PHP_DEFAULT_VERSION uses fallback default (8.4)" \
    "$default" "8.4"
echo ""

# --- 3. Fallback path: OS_BASE=rhel, dnf present but no remi repo ---
echo "-- Fallback path (OS_BASE=rhel, no remi repo in repolist) --"
_stub_dnf $'repo id\trepo name\nbase\tBase' ""
out=$(_source_php_inc rhel)
supported=$(grep '^SUPPORTED=' <<<"$out" | cut -d= -f2-)
_assert_eq "PHP_SUPPORTED_VERSIONS uses fallback when no remi repo" \
    "$supported" '5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5'
echo ""

# --- 4. Mocked remi query ---
echo "-- Mocked remi query (OS_BASE=rhel) --"
_stub_dnf $'repo id\nremi-safe\tremi safe\n' $'php74\nphp80\nphp81\nphp82\nphp83\nphp84\nphp85'
out=$(_source_php_inc rhel)
supported=$(grep '^SUPPORTED=' <<<"$out" | cut -d= -f2-)
default=$(grep  '^DEFAULT='   <<<"$out" | cut -d= -f2-)
_assert_eq "PHP_SUPPORTED_VERSIONS from mocked remi" \
    "$supported" '7.4 8.0 8.1 8.2 8.3 8.4 8.5'
_assert_eq "PHP_DEFAULT_VERSION is latest-1 (8.4)" \
    "$default" "8.4"
echo ""

# --- 5. Default version logic edge cases ---
echo "-- Default version logic --"
_remove_stub
_php_default_from_list() {
    local versions=($1)
    local count=${#versions[@]}
    if (( count >= 2 )); then echo "${versions[count-2]}"
    elif (( count == 1 )); then echo "${versions[0]}"
    fi
}
_assert_eq "single version returns that version" \
    "$(_php_default_from_list '8.4')" "8.4"
_assert_eq "two versions returns first (latest-1)" \
    "$(_php_default_from_list '8.4 8.5')" "8.4"
_assert_eq "three versions returns second" \
    "$(_php_default_from_list '8.3 8.4 8.5')" "8.4"
echo ""

# --- 6. Live remi query (only on RHEL with remi) ---
echo "-- Live remi query (skipped if not on RHEL with remi) --"
_remove_stub
source src/lib/osal.inc 2>/dev/null || true
if [[ "$OS_BASE" == 'rhel' ]] && command -v dnf &>/dev/null; then
    source src/lib/php.inc
    _assert_nonempty "PHP_SUPPORTED_VERSIONS from live remi" "$PHP_SUPPORTED_VERSIONS"
    _assert_nonempty "PHP_DEFAULT_VERSION from live remi"    "$PHP_DEFAULT_VERSION"
    _assert_in_list  "PHP_DEFAULT_VERSION is in supported list" \
        "$PHP_DEFAULT_VERSION" "$PHP_SUPPORTED_VERSIONS"
else
    echo "  (skipped — not an RHEL system with dnf)"
fi
echo ""

# --- Summary ---
echo "================================"
echo "Results: $PASS passed, $FAIL failed"
echo "================================"
[[ $FAIL -eq 0 ]]
