# ham-db
A command line app for managing ham radio contacts in a sqlite database

## Usage
usage: qso.py [-h] [-d DB_FILE] [-q] [-ac] [-cd] [-ld LOAD_DB_FROM_ADI]

A ham radio logger.

options:
  * -h, --help:              show this help message and exit
  * -d, --db_file DB_FILE:   database file location, defaults to ./qso.db
  * -q, --qso_mode:          Interactive prompt for new qso's
  * -ac, --add_callsign:     Interactive prompt for one new callsign
  * -u, --update             Interactive prompt for one column
  * -cd, --create_db:        create a new database at the specified location, defaults to ./qso.db
  * -ld, --load_db_from_adi ADI_FILE: loads a database from the specified ADI_FILE location
