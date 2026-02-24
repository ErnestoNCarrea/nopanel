#!/bin/bash

_MARIADB_LATEST_FALLBACK=12.2
_MARIADB_LTS_FALLBACK=11.8

_mariadb_fetch_versions() {
    command -v jq &>/dev/null || return 1

    local json
    json=$(curl -sf --max-time 5 "https://endoflife.date/api/v1/products/mariadb/") || return 1

    local latest lts
    latest=$(printf '%s' "$json" | jq -r '[.result.releases[] | select(.isMaintained == true and .isLts == false)] | first | .name' 2>/dev/null) || return 1
    lts=$(printf '%s' "$json"    | jq -r '[.result.releases[] | select(.isMaintained == true and .isLts == true)]  | first | .name' 2>/dev/null) || return 1

    [[ -n "$latest" && "$latest" != "null" && -n "$lts" && "$lts" != "null" ]] || return 1
    printf '%s %s\n' "$latest" "$lts"
}

if _mariadb_versions=$(_mariadb_fetch_versions 2>/dev/null); then
    MARIADB_LATEST_VERSION=${_mariadb_versions%% *}
    MARIADB_LTS_VERSION=${_mariadb_versions##* }
else
    MARIADB_LATEST_VERSION=$_MARIADB_LATEST_FALLBACK
    MARIADB_LTS_VERSION=$_MARIADB_LTS_FALLBACK
fi

unset _MARIADB_LATEST_FALLBACK _MARIADB_LTS_FALLBACK _mariadb_versions
unset -f _mariadb_fetch_versions
