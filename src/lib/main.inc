#!/bin/bash

nplib_command_echo() {
    if [[ "$param_interactive" != "false" ]] && [[ ! "$param_output_silent" ]]; then
        echo "$@"
    fi
    nplib_command_log "$@"
}

nplib_command_log() {
    logger -- "$@"
}

# Outputs command result
# nplib_command_return 'ok|error' 'Message' 'additional data'
nplib_command_return() {
    if [[ "$param_output_json" ]]; then
        if [[ "$3" ]]; then
            jq -n ".status=\"$1\"|.message=\"$2\"|.data=$3"
        else
            jq -n ".status=\"$1\"|.message=\"$2\""
        fi
    elif [[ "$param_output_silent" ]]; then
        # Only data
        if [[ "$3" ]]; then
            echo $3
        fi
    else
        TERM_COLOR_NONE='\033[0m'
        TERM_COLOR_RED='\033[0;31m'
        TERM_COLOR_GREEN='\033[0;32m'
        if [[ "$1" == "ok" ]]; then
            echo -e "[ ${TERM_COLOR_GREEN}ok${TERM_COLOR_NONE} ]: $2"
        elif [[ "$1" == "error" ]]; then
            echo -e "[ ${TERM_COLOR_RED}error${TERM_COLOR_NONE} ]: $2"
        else
            echo "[ $1 ]: $2"
        fi
        if [[ "$3" ]]; then
            echo $3
        fi
    fi

    if [[ "$1" == "ok" ]]; then
        return 0
    else
        return 1
    fi
}

# Backup config files (usually prior to install/remove)
# nplib_config_backup 'prefix' file1 file2 file3 ...
nplib_config_backup() {
    local dest=$NOPANEL_STATE/backup/
    local filename=${1}-$(date +%Y%m%d%H%M%S)
    shift

    if [ "$1" ]; then
        mkdir -p $dest
        nplib_command_log "tar -f $dest/${filename}.tar.gz $@"
        tar -zc --ignore-failed-read -f $dest/${filename}.tar.gz $@ > /dev/null 2>&1
    fi
}

nplib_safe_rm() {
    for file in "$@"; do
        if [[ $file =~ ^/etc/.*|^/var/.*|^/home/.* ]]; then
            nplib_command_log "rm -rf $file"
            rm -rf $file
        fi
    done
}

nplib_exit_on_failure() {
    if [ $? -ne 0 ]; then
        nplib_command_return 'error' "$2"
    fi
}

# Run arbitrary CLI commands with dropped privileges
nplib_user_exec() {
    local user=$1
    shift

    local user_groups=$(id -G "$user")
    user_groups=${user_groups//\ /,}

    setpriv --groups "$user_groups" --reuid "$user" --regid "$user" -- $@
}

# Install template files to destination
nplib_install_template_files() {
    local src=$1
    local src_path=$(dirname $1)
    local dst=$2

    # Copy general template files
    if [[ -e "$NOPANEL_DATA/$src_path" ]]; then
        cp -rf $NOPANEL_DATA/$src $dst
    fi

    # Copy distro base-specific template files
    if [[ -e "$NOPANEL_DATA/$OS_BASE/$src_path" ]]; then
        cp -rf $NOPANEL_DATA/$OS_BASE/$src $dst
    fi

    # Copy distro-specific template files
    if [[ -e "$NOPANEL_DATA/$OS_TYPE/$src_path" ]]; then
        cp -rf $NOPANEL_DATA/$OS_TYPE/$src $dst
    fi
}

nplib_is_nopanel_admin() {
    local usr=$1
    [[ "$usr" ]] || usr=$USER
    [ "$usr" = 'root' ] && return 0
    groups $usr | grep -q '\bnopanel-admins\b'
}

nplib_check_user() {

    if ! nplib_is_nopanel_admin; then
        # is regular user
        if [[ "$param_user" ]] && [ ! "$param_user" = "$USER" ]; then
            # can only use it's own username
            nplib_command_return 'error' "You are not allowed to become $param_user"
            exit 1
        fi

        # regular users can only be themselves
        if [[ ! "$param_user" ]]; then
            param_user=$USER
        fi
    fi
}

# check if a string contains another string
# nplib_string_contains 'haystack' 'needle'
nplib_string_contains() {
    [[ ! "$1" ]] || [ ! -z "${1##*$2*}" ]
}

# source a lib if it hasn't been sourced yet
# nplib_require 'mylib.inc'
nplib_require() {
    if nplib_string_contains "$nplib_required" "$1"; then
        source $1
        nplib_required="$nplib_required $1"
    fi
}