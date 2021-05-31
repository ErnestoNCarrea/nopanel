#!/bin/bash

# nplib_modules_set 'module' 'key' 'value'
nplib_modules_set() {
    osal_json_set "$NOPANEL_ETC/modules.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_modules_get 'module' 'key'
nplib_modules_get() {
    osal_json_get "$NOPANEL_ETC/modules.json" ".\"$1\" | .\"$2\""
}

# nplib_modules_list
nplib_modules_list() {
    osal_json_get "$NOPANEL_ETC/modules.json" "keys[]"
}

# nplib_modules_list_json
nplib_modules_list_json() {
    osal_json_get "$NOPANEL_ETC/modules.json" "."
}

# nplib_modules_set_installed 'MODULENAME' 'true|false'
nplib_modules_set_installed() {
    nplib_modules_set $1 'installed' $2
}

# nplib_modules_get_installed 'module'
nplib_modules_get_installed() {
    local installed=$(nplib_modules_get $1 'installed')
    [ "$installed" = 'true' ];
}