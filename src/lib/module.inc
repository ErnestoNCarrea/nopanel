#!/bin/bash

# nplib_module_set 'MODULENAME' 'key' 'value'
nplib_module_set() {
    osal_json_set "$NOPANEL_ETC/modules.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_module_set 'MODULENAME' 'key'
nplib_module_get() {
    osal_json_get "$NOPANEL_ETC/modules.json" ".\"$1\" | .\"$2\""
}

# nplib_module_set_installed 'MODULENAME' 'true|false'
nplib_module_set_installed() {
    nplib_module_set $1 'installed' $2
}

nplib_module_get_installed() {
    local installed=$(nplib_module_get $1 'installed')
    [ "$installed" = 'true' ];
}