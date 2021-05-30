#!/bin/bash

nopanel_command_echo() {
    if [[ "$param_interactive" ]]; then
        echo "$@"
    fi
    nopanel_command_log "$@"
}

nopanel_command_log() {
    logger "$@"
}

nopanel_command_return() {
    if [[ "$param_interactive" ]]; then
        echo $1: $2
    else
        jq -n ".status=\"$1\"|.message=\"$2\""
    fi

    if [[ "$1" == "ok" ]]; then
        exit 0
    else
        exit 1
    fi
}

# Backup config files (usually prior to module install)
# nopanel_config_backup 'prefix' file1 file2 file3 ...
nopanel_config_backup() {
    local dest=$NOPANEL_STATE/backup/
    local filename=${1}-$(date +%Y%m%d%H%M%S)
    shift

    if [ "$1" ]; then
        mkdir -p $dest
        nopanel_command_log "tar -f $dest/${filename}.tar.gz $@"
        tar -zc --ignore-failed-read -f $dest/${filename}.tar.gz $@ > /dev/null 2>&1
    fi
}

nopanel_safe_rm() {
    for file in "$@"; do
        if [[ $file =~ ^/etc/.*|^/var/.*|^/home/.* ]]; then
            nopanel_command_log "rm -rf $file"
            rm -rf $file
        fi
    done
}

nopanel_exit_on_failure() {
    if [ $? -ne 0 ]; then
        nopanel_command_return 'error' "$2"
    fi
}