#!/bin/bash

# Backup config files (usually prior to module install)
# nopanel_config_backup 'prefix' file1 file2 file3 ...
nopanel_config_backup() {
    local dest=$NOPANEL_STATE/backup/
    local filename=${1}-$(date +%Y%m%d%H%M%S)
    shift

    if [ "$1" ]; then
        mkdir -p $dest
        [ "$NOPANEL_DEBUG" ] && >&2 echo tarring -f $dest/${filename}.tar.gz $@
        tar -zc --ignore-failed-read -f $dest/${filename}.tar.gz $@ > /dev/null 2>&1
    fi
}

nopanel_safe_rm() {
    for file in "$@"; do
        if [[ $file =~ ^/etc/.*|^/var/.*|^/usr/share/.* ]]; then
            [ "$NOPANEL_DEBUG" ] && >&2 echo rm -rf $file
            rm -rf $file
        fi
    done
}