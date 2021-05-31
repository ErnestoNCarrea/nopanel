#!/bin/bash

nplib_users_get() {
    osal_json_get "$NOPANEL_ETC/users.json" ".users[] | .name"
}

nplib_users_get_json() {
    osal_json_get "$NOPANEL_ETC/users.json" "[.users[]]"
}