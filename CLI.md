## noPanel

nopanel [--output-json|--output-text|--output-silent]

nopanel ver
nopanel init

nopanel module apache install
nopanel module apache reload

nopanel module mariadb install
nopanel module mariadb wipe --force

user list
user add --user=USERNAME --password=PASSWORD --email=EMAIL [--shell=SHELL] [--fullname=FULL_NAME] [--force]
user mod --user=USERNAME [--password=PASSWORD] [--email=EMAIL] [--shell=SHELL] [--fullname=FULL_NAME]
user remove --user=USERNAME --force [--no-backup]

web domain list
web domain add --user=USER --domain=DOMAIN [--aliases=ALIASES]
web domain rebuild [--user=USER] [--domain=DOMAIN]

database list
database add --user=USER --db=DBNAME [--dbuser=DBUSER]
database rebuild [--user=USER] [--db=DBNAME]
