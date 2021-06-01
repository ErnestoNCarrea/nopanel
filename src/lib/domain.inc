#!/bin/bash

# nplib_domains_set 'domain' 'key' 'value'
nplib_domains_set() {
    osal_json_set "$NOPANEL_HOME/$param_user/nopanel/domains.json" ".\"${1}\".\"${2}\" = \"$3\""
}

# nplib_domains_get 'domain' 'key'
nplib_domains_get() {
    osal_json_get "$NOPANEL_HOME/$param_user/nopanel/domains.json" ".\"$1\".\"$2\" // \"\""
}

# nplib_domains_list ['user']
nplib_domains_list() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_HOME/$param_user/nopanel/domains.json" ".[] | select(.user == \"$1\") | .name"
    else
        osal_json_get "$NOPANEL_HOME/$param_user/nopanel/domains.json" "keys[]"
    fi
}

# nplib_domains_list_json ['user']
nplib_domains_list_json() {
    if [[ "$1" ]]; then
        osal_json_get "$NOPANEL_HOME/$param_user/nopanel/domains.json" "with_entries(select(.value.user == \"$1\"))"
    else
        osal_json_get "$NOPANEL_HOME/$param_user/nopanel/domains.json" "."
    fi
}

# nplib_domains_list 'domain' 'key'
nplib_domains_exists() {
    [[ $(nplib_domains_get "$1" 'name') ]]
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