#!/bin/bash

_PHP_SUPPORTED_FALLBACK='5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5'
_PHP_DEFAULT_FALLBACK=8.4

_php_fetch_remi_versions() {
    # Requires OS_BASE='rhel' and dnf + a remi repo configured
    [[ "$OS_BASE" == 'rhel' ]] || return 1
    command -v dnf &>/dev/null || return 1

    # Discover the first enabled remi repo that supplies php<NN> packages
    # (remi-safe on enterprise RHEL, remi on Fedora)
    local repoid
    repoid=$(timeout 10 dnf repolist --enabled 2>/dev/null \
        | awk 'NR>1 {print $1}' \
        | grep -i '^remi' \
        | grep -iv 'modular\|debug\|test\|source' \
        | head -1)
    [[ -n "$repoid" ]] || return 1

    local pkgs
    pkgs=$(timeout 30 dnf repoquery -q --cacheonly --repo="$repoid" --qf '%{name}\n' 'php[0-9][0-9]' 2>/dev/null)
    [[ -n "$pkgs" ]] || return 1

    # Convert php56 -> 5.6, php84 -> 8.4, sort, space-delimited
    printf '%s\n' "$pkgs" \
        | grep -oE '^php[0-9]{2}$' \
        | sed 's/php\(.\)\(.\)/\1.\2/' \
        | sort -V \
        | uniq \
        | tr '\n' ' ' \
        | sed 's/ $//'
}

_php_default_from_list() {
    # Pick second-to-last version (latest - 1)
    local versions=($1)
    local count=${#versions[@]}
    if (( count >= 2 )); then
        echo "${versions[count-2]}"
    elif (( count == 1 )); then
        echo "${versions[0]}"
    fi
}

if [[ "$OS_BASE" == 'rhel' ]]; then
    if _remi_versions=$(_php_fetch_remi_versions 2>/dev/null) && [[ -n "$_remi_versions" ]]; then
        PHP_SUPPORTED_VERSIONS="$_remi_versions"
        PHP_DEFAULT_VERSION=$(_php_default_from_list "$_remi_versions")
    else
        PHP_SUPPORTED_VERSIONS="$_PHP_SUPPORTED_FALLBACK"
        PHP_DEFAULT_VERSION=$(_php_default_from_list "$_PHP_SUPPORTED_FALLBACK")
    fi
    unset _remi_versions
else
    PHP_SUPPORTED_VERSIONS="$_PHP_SUPPORTED_FALLBACK"
    PHP_DEFAULT_VERSION=$(_php_default_from_list "$_PHP_SUPPORTED_FALLBACK")
fi

unset _PHP_SUPPORTED_FALLBACK _PHP_DEFAULT_FALLBACK
unset -f _php_fetch_remi_versions _php_default_from_list
