## noPanel

A panel-less web panel.

noPanel is a multi-user, CLI-only web server manager, with Apache, Let's Encrypt, MariaDB and multi-version PHP support.

Written entirely in Bash, with minimal dependencies.

### noPanel command line interface

```bash
nopanel [--output json|plain] [--interactive [yes|no]] SUB_COMMAND
```

Where SUB_COMMAND is:

```bash
[n]     ver
[id]    init
[Ri]    commit

[n]     module list

[Rid]   module apache install
[Rnd]   module apache reload

[Rid]   module mariadb install
[Rid]   module mariadb upgrade
[Rid]   module mariadb wipe --force

[n]     user list
[c]     user add --user USERNAME --password PASSWORD [--email EMAIL] [--login ssh|sftp|no] \
            [--fullname FULL_NAME] [--admin [yes|no]]
[ic]    user mod --user USERNAME [--password PASSWORD] [--email EMAIL] [--login ssh|sftp|no] \
            [--fullname FULL_NAME] [--admin [yes|no]]
[c]     user remove --user USERNAME --force [--delete [--no-backup]]
[Ri]    user commit [--user USER]

[Ri]    web commit
[n]     web domain list --user USER
[c]     web domain add --user USER --domain DOMAIN [--aliases ALIASES] [--php VERSION|no] [--ssl le|custom|self|no]
[ic]    web domain mod --user USER --domain DOMAIN [--aliases ALIASES] [--php VERSION|no] [--ssl le|custom|self|no]
[c]     web domain remove --user USER --domain DOMAIN --force
[Ri]    web domain commit [--user USER] [--domain DOMAIN]

[n]     database list
[c]     database add --user USER --db DBNAME [--dbuser DBUSER] --password PASSWORD
[ic]    database mod --user USER --db DBNAME [--dbuser DBUSER] [--password PASSWORD]
[c]     database remove --user USER --db DBNAME
[Ri]    database commit [--user USER] [--db DBNAME]

[n]     module php-fpm info
[Ri]    module php-fpm install
[Ri]    module php-fpm add [--version MAJOR.MINOR]
[Ri]    module php-fpm del [--version MAJOR.MINOR]
```

Ref.:
[n] Causes no change
[R] Needs root always
[i] Idempotent
[d] May disrupt service
[c] Takes effect on commit

### BYOJ (Bring Your Own Json)

/etc/nopanel/users.json (root only)
~/.nopanel/domains.json
~/.nopanel/databases.json

Just edit and then run `nopanel commit --reload` to apply changes.