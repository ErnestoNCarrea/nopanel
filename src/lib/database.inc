#!/bin/bash

nplib_database_get() {
    osal_json_get "$NOPANEL_ETC/databases.json" ".databases[] | select(.user == \"$param_user\") | .name"
}

nplib_database_get_json() {
    osal_json_get "$NOPANEL_ETC/databases.json" "[.databases[] | select(.user == \"$param_user\")]"
}