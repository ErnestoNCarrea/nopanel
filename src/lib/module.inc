#!/bin/bash

# nplib_modules_set 'MODULENAME' 'key' 'value'
nplib_modules_set() {
    osal_json_set "$NOPANEL_ETC/modules.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_modules_get 'MODULENAME' 'key'
nplib_modules_get() {
    osal_json_get "$NOPANEL_ETC/modules.json" ".\"$1\" | .\"$2\""
}

# nplib_modules_set_installed 'MODULENAME' 'true|false'
nplib_modules_set_installed() {
    nplib_modules_set $1 'installed' $2
}

# nplib_modules_get_installed 'MODULENAME'
nplib_modules_get_installed() {
    local installed=$(nplib_modules_get $1 'installed')
    [ "$installed" = 'true' ];
}