#!/bin/bash

# nplib_databases_set 'database' 'key' 'value'
nplib_databases_set() {
    osal_json_set "$NOPANEL_HOME/$param_user/.nopanel/databases.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_databases_get 'database' 'key'
nplib_databases_get() {
    osal_json_get "$NOPANEL_HOME/$param_user/.nopanel/databases.json" ".\"$1\".\"$2\" // \"\""
}

# nplib_databases_list ['user']
nplib_databases_list() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_HOME/$param_user/.nopanel/databases.json" ".[] | select(.user == \"$1\") | .name"
    else
        osal_json_get "$NOPANEL_HOME/$param_user/.nopanel/databases.json" "keys[]"
    fi
}

# nplib_databases_list_json ['user']
nplib_databases_list_json() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_HOME/$param_user/.nopanel/databases.json" "with_entries(select(.value.user == \"$1\"))"
    else
        osal_json_get "$NOPANEL_HOME/$param_user/.nopanel/databases.json" "."
    fi
}

# nplib_databases_exists 'database'
nplib_databases_exists() {
    [[ $(nplib_databases_get "$1" 'name') ]]
}

# nplib_databases_delete 'username'
nplib_databases_delete() {
    osal_json_set "$NOPANEL_HOME/$param_user/.nopanel/databases.json" "del(.\"$1\")"
}