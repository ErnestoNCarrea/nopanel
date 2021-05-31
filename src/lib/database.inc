#!/bin/bash

nplib_databases_list() {
    osal_json_get "$NOPANEL_ETC/databases.json" ".databases[] | select(.user == \"$param_user\") | .name"
}

nplib_databases_list_json() {
    osal_json_get "$NOPANEL_ETC/databases.json" "[.databases[] | select(.user == \"$param_user\")]"
}