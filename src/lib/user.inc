#!/bin/bash

nplib_user_get() {
    osal_json_get "$NOPANEL_ETC/users.json" ".users[] | .name"
}

nplib_user_get_json() {
    osal_json_get "$NOPANEL_ETC/users.json" "[.users[]]"
}