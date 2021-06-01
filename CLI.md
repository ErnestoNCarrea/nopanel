## noPanel

### noPanel command line interface

nopanel [--output-json|--output-text|--output-silent]

ver
init

module apache install
module apache reload

module mariadb install
module mariadb wipe --force

user list
user add --user=USERNAME --password=PASSWORD [--email=EMAIL] [--shell=SHELL] [--fullname=FULL_NAME] [--force]
user mod --user=USERNAME [--password=PASSWORD] [--email=EMAIL] [--shell=SHELL] [--fullname=FULL_NAME]
user remove --user=USERNAME --force [--delete [--no-backup]]
user commit

web domain list
web domain add --user=USER --domain=DOMAIN [--aliases=ALIASES]
web domain rebuild [--user=USER] [--domain=DOMAIN]

database list
database add --user=USER --db=DBNAME [--dbuser=DBUSER]
database rebuild [--user=USER] [--db=DBNAME]

module php-fpm info
module php-fpm install
module php-fpm add [--version MAJOR.MINOR]
module php-fpm install

### BYOJ (Bring Your Own Json)

~/nopanel/domains.json
~/nopanel/databases.json
