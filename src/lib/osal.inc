#!/bin/sh

# Identifies OS type and variant
# Setups variables and provides OS-agnostic wrapper functions

OS_TYPE=$(grep "^ID=" /etc/os-release | cut -f 2 -d '=' | sed -e 's/^"//' -e 's/"$//' | sed -e 's/\(.*\)/\L\1/')
case "$OS_TYPE" in
debian)
    OS_BASE='debian'
    OS_VERSION=$(cat /etc/debian_version|grep -o "[0-9]\{1,2\}"|head -n1)
    OS_VERSION_MAJOR=${OS_VERSION%.*}
    OS_CODENAME="$(cat /etc/os-release |grep VERSION= |cut -f 2 -d \(|cut -f 1 -d \))"
    ;;
ubuntu)
    OS_BASE='debian'
    OS_VERSION="$(lsb_release -s -r)".
    OS_VERSION_MAJOR=${OS_VERSION%.*}
    OS_CODENAME="$(lsb_release -s -c)"
    ;;
centos|rhel|fedora|redhat|almalinux|rocky)
    OS_BASE='rhel'
    OS_VERSION=$(cat /etc/os-release | grep VERSION_ID | sed -e "s/VERSION_ID=//" | sed -e 's/^"//' -e 's/"$//')
    OS_VERSION_MAJOR=${OS_VERSION%.*}
    OS_CODENAME=''
    ;;
*)
    OS_BASE='unknown'
    ;;
esac

OSAL_PATH="$(cd "$(dirname "$BASH_SOURCE")" >/dev/null 2>&1 ; pwd -P)"

for OSAL_FILE in "osal_${OS_BASE}_based" \
                 "osal_${OS_TYPE}" \
                 "osal_${OS_TYPE}_${OS_VERSION}"
do
    # Search for OS specific OSAL file and source it
    if [ -f "$OSAL_PATH/${OSAL_FILE}.inc" ]; then
        source "$OSAL_PATH/${OSAL_FILE}.inc"
    fi
done

# service_start 'service-name'
osal_service_start() {
    [ "$NOPANEL_DEBUG" ] && >&2 echo Start service $1
    /usr/bin/systemctl start ${1}.service
}

# service_stop 'service-name'
osal_service_stop() {
    [ "$NOPANEL_DEBUG" ] && >&2 echo Stop service $1
    /usr/bin/systemctl stop ${1}.service
}

# service_restart 'service-name'
osal_service_restart() {
    [ "$NOPANEL_DEBUG" ] && >&2 echo Restart service $1
    /usr/bin/systemctl restart ${1}.service
}

# service_enable 'service-name'
osal_service_enable() {
    [ "$NOPANEL_DEBUG" ] && >&2 echo Enable service $1
    /usr/bin/systemctl enable ${1}.service
}

# service_disable 'service-name'
osal_service_disable() {
    [ "$NOPANEL_DEBUG" ] && >&2 echo Disable service $1
    /usr/bin/systemctl disable ${1}.service
}

osal_value_in_list() {
    local needle=$1
    shift

    if [[ -z "$@" ]]; then
        # Empty list. Return not found.
        return 1;
    fi

    [[ $@ =~ (^|[[:space:]])$needle($|[[:space:]]) ]] && return 0
    return 1
}

# VAR=$(ini_get 'file' 'section' 'param' 'value')
osal_ini_get() {
    #echo /usr/bin/crudini --get $@
    local retval=$(/usr/bin/crudini --get $@ 2>1)
    if [ $? -eq 0 ]; then
        echo $retval
    fi
}

# ini_set 'file' 'section' 'param' 'newvalue'
osal_ini_set() {
    if [ "$OSAL_DEBUG" ]; then
        echo /usr/bin/crudini --set $@
    fi
    /usr/bin/crudini --set $@
}

# For use in osal_kv_*
sed_escape() {
    sed -e 's/[]\/$*.^[]/\\&/g'
}

# write a value to a json file (ealue is in jq format)
# osal_json_set 'file' 'value'
osal_json_set() {
    local tmpfile=$(mktemp)
    [[ -s "$1" ]] || echo '{}' > "$1"
    jq "$2" "$1" > "$tmpfile" && (chown --reference=$1 $tmpfile; chmod --reference=$1 $tmpfile; mv "$tmpfile" "$1")
}

# read a value from a json file (value is in jq format)
# osal_json_get 'file' 'value'
osal_json_get() {
    jq --raw-output --compact-output "$2" "$1"
}

# Writes a value to a key-value file.
# osal_kv_write 'path' 'key' 'value'
osal_kv_write() {
    touch "$1"
    osal_kv_delete "$1" "$2"
    echo "$2=$3" >> "$1"
}

# Reads a value from a key-value file. # Exits successfully if it does.
# value=$(osal_kv_read path key defaultvalue)
osal_kv_read() {
    local kv_keyname=$(echo "$2" | sed_escape)
    if [ -s "$1" ]; then
        local retval=$(grep "^$kv_keyname\s*=" "$1" | sed "s/^$kv_keyname\s*=\s*//" | tail -1 | sed "s/^\([\"']\)\(.*\)\1\$/\2/g")
        if [ "$retval" ]; then
            echo $retval
        else
            echo $3
        fi
    else
        echo $3
    fi
}

# Deletes a value in a key-value file.
# osal_kv_delete 'filename' 'key'
osal_kv_delete() {
    local kv_keyname=$(echo "$2" | sed_escape)
    test -f "$1" && sed -i "/^${kv_keyname}\s*=.*$/d" "$1"
}

# Tests if a value exists in a key-value file.
# Exits successfully if it does.
# osal_kv_haskey 'filename' 'key'
osal_kv_haskey() {
    local kv_keyname=$(echo "$2" | sed_escape)
    test -f "$1" && grep "^${kv_keyname}\s*=" "$1" > /dev/null
    if [ $? -eq 0 ]; then
        return 0
    else
        return 1
    fi
}

# Tests if a boolean value is true in a key-value file.
# Exits successfully if it does.
# osal_kv_read_bool 'filename' 'keyname'
osal_kv_read_bool() {
    local retval=$(osal_kv_read $@)
    if [ "${retval,,}" == "yes" ] \
        || [ "${retval,,}" == "true" ] \
        || [ "${retval,,}" == "on" ] \
        || [ "$retval" == "1" ]; then
        return 0
    else
        return 1
    fi
}

# Converts a boolean value to 'yes'/'no' (or two terms provided as second and third argument)
# answer=$(osal_bool_tostring boolean_value yes_value no_value)
osal_bool_tostring() {
    if [ "${1,,}" == "yes" ] \
        || [ "${1,,}" == "true" ] \
        || [ "${1,,}" == "on" ] \
        || [ "$1" == "1" ]; then
        if [ -n "$2" ]; then echo "$2"; else echo 'yes'; fi
    else
        if [ -n "$3" ]; then echo "$3"; else echo 'no'; fi
    fi
}

# Executes a process and logs it's output
osal_execute() {
    echo "\$ $@" >> $NOPANEL_LOG/debug.log
    $@ | tee --append $NOPANEL_LOG/debug.log 2>&1
}

# Executes a process silently in the background while showing a spinner
osal_execute_with_spinner() {
    if [ "$OSAL_DEBUG" ]; then
        echo "$@"
        $@
    else
        echo "\$ $@" >> $NOPANEL_LOG/debug.log
        $@ > $NOPANEL_LOG/debug.log 2>&1 &
        local BACK_PID=$!

        local spinner="/-\|"
        local spin_i=1
        while kill -0 $BACK_PID > $NOPANEL_LOG/debug.log 2>&1 ; do
            printf "\b${spinner:spin_i++%${#spinner}:1}"
            sleep 0.5
        done

        # Do a blank echo to get the \n back
        echo
    fi
}

# Generates a random password
osal_gen_pass() {
    local MATRIX='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    local LENGTH=16
    while [ ${n:=1} -le $LENGTH ]; do
        PASS="$PASS${MATRIX:$(($RANDOM%${#MATRIX})):1}"
        let n+=1
    done
    echo "$PASS"
}

# osal_user_add_group 'user' 'group'
osal_user_add_group() {
    /usr/sbin/usermod -a -G "$2" "$1" > $NOPANEL_LOG/debug.log 2>&1
}

# osal_user_del_group 'user' 'group'
osal_user_del_group() {
    /usr/bin/gpasswd -d "$param_user" nopanel-sftp > $NOPANEL_LOG/debug.log 2>&1
}

# osal_user_del_group 'user' 'shell'
osal_user_set_shell() {
    /usr/sbin/usermod --shell "$2" "$1" > $NOPANEL_LOG/debug.log 2>&1
}