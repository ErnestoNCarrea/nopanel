#!/bin/bash

# save commited information to noPanel state
# nplib_save_commited 'file'
nplib_commits_save() {
    local COMMITTED=$(nplib_commits_get_committed_filename "$1")
    cp -f $1 $COMMITTED
}

# get where commited information is stored for a commited file
# nplib_commits_get_committed_filename 'file'
nplib_commits_get_committed_filename() {
    local FILENAME=$(basename $1)
    if [[ "$1" == '/etc/nopanel/users.json' ]]; then
        echo $NOPANEL_STATE/committed/${FILENAME}
    else
        echo $NOPANEL_STATE/committed/${param_user}_${FILENAME}
    fi
}

# get keys of elements deleted since last commit
nplib_commits_get_deleted() {
    local COMMITTED=$(nplib_commits_get_committed_filename "$1")
    if [[ ! -s $COMMITTED ]]; then
        # nothing commited, report nothing deleted
        return
    fi

    local FILE1=$(mktemp)
    local FILE2=$(mktemp)

    diff --new-line-format="" --unchanged-line-format="" \
        <(jq --sort-keys --raw-output --compact-output "keys[]" "$COMMITTED") \
        <(jq --sort-keys --raw-output --compact-output "keys[]" "$1")
}

# get keys of elements changed since last commit
nplib_commits_get_changed() {
    local COMMITTED=$(nplib_commits_get_committed_filename "$1")
    if [[ ! -s $COMMITTED ]]; then
        # nothing commited, report everything changed
        jq --raw-output --compact-output "keys[]" "$1"
        return
    fi
    for ITEM_KEY in $(jq --raw-output --compact-output "keys[]" "$1" ); do
        local ITM1=$(jq --raw-output --compact-output ".\"$ITEM_KEY\" // {}" $1)
        local ITM2=$(jq --raw-output --compact-output ".\"$ITEM_KEY\" // {}" $COMMITTED)

        #echo "=== FOR $ITEM_KEY"
        #echo "$ITM1" != "$ITM2"

        if [[ "$ITM1" != "$ITM2" ]]; then
            echo $ITEM_KEY
        fi
    done
}

nplib_commits_get_added() {
    local COMMITTED=$(nplib_commits_get_committed_filename "$1")

    local FILE1=$(mktemp)
    local FILE2=$(mktemp)

    diff --new-line-format="" --unchanged-line-format="" \
        <(jq --sort-keys --raw-output --compact-output "keys[]" "$1") \
        <(jq --sort-keys --raw-output --compact-output "keys[]" "$COMMITTED")
}