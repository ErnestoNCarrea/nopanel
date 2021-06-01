#!/bin/bash
# Parses command line paramteres into $param_* variables
# © Ernesto N. Carrea / https://www.nopanel.cc

nplib_original_params="$@"

# Search for command file
local cmd_name=''
local cmd_file=''
for arg in "$@"
do
    # FIXME: secutirity (what if $arg is something like ../../../malicious_code)
    if [ -f "$NOPANEL_LIB_CLI/$cmd_file/${arg}" ]; then
        # Look for a nopanel-cli file
        if [ $cmd_name ]; then
            cmd_name="${cmd_name}_${arg}"
            cmd_file=$NOPANEL_LIB_CLI/$cmd_file/${arg}
        else
            cmd_name=$arg
            cmd_file=$NOPANEL_LIB_CLI/${arg}
        fi
        cmd_type='include'
        shift
        break
    elif [ -d "$NOPANEL_LIB_CLI/$cmd_file/${arg}" ]; then
        # Keep looking inside dirs
        if [ $cmd_name ]; then
            cmd_name="${cmd_name}_${arg}"
            cmd_file="${cmd_file}/${arg}"
        else
            cmd_name=$arg
            cmd_file=$arg
        fi
        cmd_type='dir'
        shift
    elif [ -x "$NOPANEL_LIB_CLI/$cmd_file/${arg}" ]; then
        # Look for regular executable file
        if [ $cmd_name ]; then
            cmd_name="${cmd_name}_${arg}"
            cmd_file=$NOPANEL_LIB_CLI/$cmd_file/${arg}
        else
            cmd_name=$arg
            cmd_file=$NOPANEL_LIB_CLI/${arg}
        fi
        cmd_type='executable'
        shift
        break
    elif [ "$cmd_file" ]; then
        # We have a partial path, but component not found
        cmd_type='not-found'
        return 1
        break
    fi
done

# Process the rest of the arguments as --arg or --arg value
# https://brianchildress.co/named-parameters-in-bash/
params=''
for param in "$@"
do
    if [[ $param == *"--"* ]]; then
        # It's a --parameter
        if [ "$param_name" ] && [ ! "${!param_name}" ]; then
            # Previous --arg is empty, so set it to true before continuing
            declare $param_name=1
        fi
        param_name=$(echo "param_${param:2}" | sed 's/-/_/')    # trim --, replace - with _
        # Add param_name to the list of used params (unless it's there already)
        [[ $params =~ (^|[[:space:]])$param_name($|[[:space:]]) ]] || params="$params $param_name"
        last_was='name'
    else
        # Not a --parameter, so it's a value
        if [ "$param_name" ]; then
            if [ "${!param_name}" ]; then
                # Already has value... add to it
                declare $param_name="${!param_name} $param"
            else
                # Doesn't have value... initialize
                declare $param_name="$param"
            fi
        fi
        last_was='value'
    fi
done
# Process trailing --boolean_param
if [ "$last_was" == 'name' ]; then
    declare $param_name=1
fi

# Trim leading space
[ "$params" ] && params="${params:1}"