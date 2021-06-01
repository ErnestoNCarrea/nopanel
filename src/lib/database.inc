#!/bin/bash

# nplib_databases_set 'domain' 'key' 'value'
nplib_databases_set() {
    osal_json_set "$NOPANEL_ETC/databases.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_databases_get 'domain' 'key'
nplib_databases_get() {
    osal_json_get "$NOPANEL_ETC/databases.json" ".\"$1\" | .\"$2\""
}

# nplib_databases_list ['user']
nplib_databases_list() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_ETC/databases.json" ".[] | select(.user == \"$1\") | .name"
    else
        osal_json_get "$NOPANEL_ETC/databases.json" "keys[]"
    fi
}

# nplib_databases_list_json ['user']
nplib_databases_list_json() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_ETC/databases.json" "with_entries(select(.value.user == \"$1\"))"
    else
        osal_json_get "$NOPANEL_ETC/databases.json" "."
    fi
}