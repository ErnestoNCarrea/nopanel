#!/bin/bash

nplib_domain_get() {
    osal_json_get "$NOPANEL_ETC/domains.json" ".domains[] | select(.user == \"$param_user\") | .name"
}

nplib_domain_get_json() {
    osal_json_get "$NOPANEL_ETC/domains.json" "[.domains[] | select(.user == \"$param_user\")]"
}

nplib_domain_idn() {
    idn -t --quiet -a $1
}

nplib_domain_aliases_idn() {
    i=1
    local res=""
    for domain_alias in ${1//,/ }; do
        local domain_alias_idn=$(idn -t --quiet -a $domain_alias)
        if [[ "$res" ]]; then
            res="$res $domain_alias_idn"
        else
            res="$domain_alias_idn"
        fi
    done
    echo $res
}