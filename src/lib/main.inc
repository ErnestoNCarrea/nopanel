#!/bin/bash
# noPanel library (nplib) misc functions
# © Ernesto N. Carrea / https://www.nopanel.cc

nplib_command_echo() {
    if nplib_is_false $param_interactive && [[ ! "$param_output" ]]; then
        echo "$@"
    fi
    nplib_command_log "$@"
}

nplib_command_log() {
    logger -- "$@"
}

# Outputs command result
# nplib_command_output 'ok|error' 'Message' 'additional data' 'jq table_format'
nplib_command_output() {
    if [ "$param_output" = 'json' ]; then
        if [[ "$3" ]]; then
            jq -n ".status=\"$1\"|.message=\"$2\"|.data=$3"
        else
            jq -n ".status=\"$1\"|.message=\"$2\""
        fi
    elif [ "$param_output" = 'plain' ]; then
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
            echo -e $3
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
        nplib_command_output 'error' "$2"
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

# test if a value is a valid boolean according to noPanel
# 'yes', 'true', 'on' and '1' are all true
# 'no', 'false', 'off' and '0' are all false
nplib_is_bool() {
    [[ $(nplib_bool_value $1) ]]
}

# returns 'true' for truthy values, false for falsy values, nothing for everythin else
nplib_bool_value() {
    if nplib_is_true $1; then
        echo 'true'
    elif nplib_is_false $1; then
        echo 'false'
    fi
}

# test if a value is a 'truthy' according to noPanel
# 'yes', 'true', 'on' and '1' are all true
nplib_is_true() {
    if [ "${1,,}" = 'yes' ] \
        || [ "${1,,}" = 'true' ] \
        || [ "${1,,}" = 'on' ] \
        || [ "$1" = '1' ]; then
        return 0
    else
        return 1
    fi
}

# test if a value is a 'falsy' according to noPanel
# 'no', 'false', 'off' and '0' are all false
nplib_is_false() {
    if [ "${1,,}" = 'no' ] \
        || [ "${1,,}" = 'false' ] \
        || [ "${1,,}" = 'off' ] \
        || [ "$1" = '0' ]; then
        return 0
    else
        return 1
    fi
}


nplib_is_nopanel_admin() {
    local usr=$1
    [[ "$usr" ]] || usr=$USER
    [ "$usr" = 'root' ] && return 0
    groups $usr | grep -q '\bnopanel-admins\b'
}

# check if there is --user and if current user is allowed to use it
nplib_check_user() {
    if ! nplib_is_nopanel_admin; then
        # is regular user
        if [[ "$param_user" ]] && [ ! "$param_user" = "$USER" ]; then
            # can only use it's own username
            nplib_command_output 'error' "You are not allowed to become $param_user"
            exit 1
        fi

        # regular users can only be themselves
        if [[ ! "$param_user" ]]; then
            param_user=$USER
        fi
    elif [ ! $param_user = $USER ]; then
        # admin trying to impersonate another user, auto elevate
        nplib_auto_elevate
    fi
}

# auto elevate privileges, or die
nplib_auto_elevate() {
    if [ "$EUID" -eq 0 ]; then
        return;
    fi

    local auto_elevate=$(osal_json_get "$NOPANEL_ETC/nopanel.json" ".\"prefs\".\"autoElevate\"")
    if nplib_is_true $auto_elevate; then
        nplib_elevate
    elif nplib_is_nopanel_admin; then
        nplib_command_output 'error' "You need to be root for that (try with sudo)"
        exit 1
    else
        nplib_command_output 'error' 'You are not allowed to use that command, ask your administrator'
        exit 1
    fi
}

# re-run this script as root
nplib_elevate() {
    if [ "$EUID" -ne 0 ]; then
        sudo "$0" "$nplib_original_params"
        exit $?
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