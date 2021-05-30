#!/bin/bash

nopanel_domain_idn() {
    idn -t --quiet -a $1
}

nopanel_domain_aliases_idn() {
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