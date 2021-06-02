#!/bin/bash

# nplib_users_set 'username' 'key' 'value'
nplib_users_set() {
    osal_json_set "$NOPANEL_ETC/users.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_users_get 'username' 'key'
nplib_users_get() {
    osal_json_get "$NOPANEL_ETC/users.json" ".\"$1\".\"$2\" // \"\""
}

# nplib_users_exists 'username'
nplib_users_exists() {
    [[ $(nplib_users_get $1 'name') ]]
}

# nplib_users_list
nplib_users_list() {
    osal_json_get "$NOPANEL_ETC/users.json" "keys[]"
}

nplib_users_list_json() {
    osal_json_get "$NOPANEL_ETC/users.json" "."
}

# nplib_users_delete 'username'
nplib_users_delete() {
    osal_json_set "$NOPANEL_ETC/users.json" "del(.\"$1\")"
}