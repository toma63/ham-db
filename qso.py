#!/usr/bin/env python3
import argparse
import os
import adif_io
import pandas as pd
import sqlite3
import questionary
from datetime import datetime, timezone
import requests
import xml.etree.ElementTree as ET

# Important TODOs:
#  - single source for schema details
#  - injection attack safety

# Query QRZ.com XML API for a callsign and return info as a dict

# QRZ.com login: returns session key
def qrz_login(username="YOUR_USERNAME", password="YOUR_PASSWORD"):
    """
    Log in to QRZ.com XML API and return session key.
    """
    QRZ_BASE_URL = "https://xmldata.qrz.com/xml/current/"
    login_url = f"{QRZ_BASE_URL}?username={username};password={password}"
    headers = {"User-Agent": "Mozilla/5.0"}
    login_resp = requests.get(login_url, headers=headers)
    if login_resp.status_code != 200:
        raise Exception(f"QRZ.com login failed: {login_resp.text}")
    login_xml = ET.fromstring(login_resp.text)
    ns = {'qrz': 'http://xmldata.qrz.com'}
    session_elem = login_xml.find('qrz:Session', ns)
    key_elem = session_elem.find('qrz:Key', ns) if session_elem is not None else None
    session_key = key_elem.text if key_elem is not None else None
    if not session_key:
        raise Exception(f"Could not obtain QRZ.com session key: {login_resp.text}")
    return session_key

# QRZ.com callsign query: uses session key
def qrz_query_callsign(callsign, session_key):
    """
    Query QRZ.com XML API for a callsign using session key, return info as dict.
    """
    QRZ_BASE_URL = "https://xmldata.qrz.com/xml/current/"
    query_url = f"{QRZ_BASE_URL}?s={session_key};callsign={callsign}"
    headers = {"User-Agent": "Mozilla/5.0"}
    query_resp = requests.get(query_url, headers=headers)
    if query_resp.status_code != 200:
        raise Exception(f"QRZ.com callsign query failed: {query_resp.text}")
    query_xml = ET.fromstring(query_resp.text)
    ns = {'qrz': 'http://xmldata.qrz.com'}
    callsign_data = {}
    cs_elem = query_xml.find('qrz:Callsign', ns)
    if cs_elem is not None:
        for child in cs_elem:
            # Strip namespace from tag
            tag = child.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            callsign_data[tag] = child.text
    else:
        raise Exception(f"No callsign data found in QRZ.com response: {query_resp.text}")
    return callsign_data

# create a new empty database
def create_new_db(db_path):
    "Create a new empty database at the db_path location."
    if os.path.exists(db_path):
        answer = input("The database exists.  Do you want to recreate it (y/n)?")
    if answer.lower() != 'y':
        exit(0)
    os.remove(db_path)

    with sqlite3.connect("./qso.db",isolation_level='IMMEDIATE') as conn:    
        conn = sqlite3.connect("./qso.db",isolation_level='IMMEDIATE')
        conn.execute("PRAGMA foreign_keys = 1")
        cursor = conn.cursor()
        # Create tables
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS callsign (
            callsign_id INTEGER PRIMARY KEY,          
            callsign TEXT NOT NULL UNIQUE,
            name TEXT,
            location TEXT,
            rig TEXT,
            grid TEXT,
            comment TEXT,
            last_contact TEXT
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS qso (
            qso_id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            band TEXT,
            frequency REAL,
            callsign_id INTEGER,
            mode TEXT,
            comment TEXT,
            qso TEXT,
            rst_sent TEXT,
            rst_rcvd TEXT,
            FOREIGN KEY(callsign_id) REFERENCES callsign(callsign_id),
            UNIQUE(callsign_id, date, time)
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS net (
            net_id INTEGER PRIMARY KEY,
            net_name TEXT,
            frequency REAL,
            comment TEXT
        )
        """)


# convert an adi file to a DataFrame
def adi_to_df(adi_file):
    "Read an adi file, convert to a DataFrame and return it."
        # Read the ADIF file into a string
    with open(adi_file, "r", encoding="ISO-8859-1") as f:
        adif_text = f.read()

    # parse the string (header - second value, is unused)
    qsos, _ = adif_io.read_from_string(adif_text)

    # convert to a DataFrame
    df = pd.DataFrame(qsos) 

    return df


# custom exception class
class CallSignMissing(Exception):
    """Custom exception for a missing callsign."""
    pass


# Load QSO's from adi
# skip entries which already exist
# all of the callsigns referenced in qso's should be defined in the adi
def load_from_adi(adi_file, db_path):
    "Load qso's and associated callsigns from adi, don't replace existing ones."
    
    # convert to a DataFrame
    df = adi_to_df(adi_file)

    # Remove unused columns
        # Remove unused columns
    retain_qso = ['CALL', # call to look up callsign id
                  'COMMENT', # combine COMMENT and NOTES for comment field
                  'NOTES', 
                  'BAND', # band
                  'FREQ', # frequency
                  'MODE', # mode
                  'QSO_DATE', # date
                  'RST_RCVD', # rst_rcvd
                  'RST_SENT', # rst_sent
                  'TIME_ON'] # time zulu
    qso_df = df[retain_qso].copy()
    # column combination and renaming
    qso_df[['COMMENT', 'NOTES']] = qso_df[['COMMENT', 'NOTES']].fillna('')
    qso_df.loc[:, 'comment'] = qso_df['COMMENT'] + ' ' + qso_df['NOTES']
    qso_df.drop(['COMMENT', 'NOTES'], axis=1, inplace=True)
    qso_df.rename(columns={'CALL': 'callsign', # use to get callsign_id (create or lookup)
                   'BAND': 'band',
                   'FREQ': 'frequency',
                   'MODE': 'mode',
                   'QSO_DATE': 'date',
                   'TIME_ON': 'time',
                   'RST_RCVD': 'rst_rcvd',
                   'RST_SENT': 'rst_sent'}, inplace=True)
    qso_df['qso'] = 'True' # everything from QRZ is a qso, not just heard
    qso_df['comment'].str.strip() # clean up if COMMENT or NOTES was empty

    retain_callsign = ['CALL', 
                       'QTH', # QTH, STATE and COUNTRY combined with comma, save as location
                       'STATE',
                       'COUNTRY', 
                       'GRIDSQUARE', # grid
                       'NAME'] # name
    callsign_df = df[retain_callsign].copy()
    callsign_df[['QTH', 'STATE', 'COUNTRY']] = callsign_df[['QTH', 'STATE', 'COUNTRY']].fillna('')
    callsign_df.loc[:, 'location'] = callsign_df['QTH'] + ' ' + callsign_df['STATE'] + ' ' + callsign_df['COUNTRY']
    callsign_df.drop(['QTH', 'STATE', 'COUNTRY'], axis=1, inplace=True)
    callsign_df['location'].str.strip() # in case either is missing
    callsign_df['rig'] = ''
    callsign_df['comment'] = ''
    callsign_df.rename(columns={'GRIDSQUARE': 'grid',
                        'CALL': 'callsign',
                        'NAME': 'name'}, inplace=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = 1") # This turns on the foreign key constraint
        cursor = conn.cursor()

        # Insert data into the qso and callsign tables
        # callsigns first
        for row_dict in callsign_df.to_dict(orient="records"):
            add_callsign(cursor, row_dict)
        conn.commit()

        # Now load all the qso's
        # reference the callsign id's which should already exist
        for row_dict in qso_df.to_dict(orient="records"):
            add_qso(cursor, row_dict)
        conn.commit()

    return(callsign_df, qso_df)


def add_qso(cursor, df_row_dict):
    "Add a single qso to the database based on a row dict"
    try:
        # get the callsign_id
        callsign = df_row_dict['callsign']
        callsign_id = get_or_create_callsign(cursor, callsign)
        # replace the callsign with the callsign_id
        del df_row_dict['callsign']
        df_row_dict['callsign_id'] = callsign_id

        columns = ', '.join(df_row_dict.keys())
        placeholders = ', '.join(['?'] * len(df_row_dict))
        sql = f"INSERT INTO qso ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(df_row_dict.values()))
    except CallSignMissing:
        print(f"The callsign {callsign} does not exist. Exiting.")
        exit(1)
    except sqlite3.IntegrityError:
        print(f"qso for {callsign}, {df_row_dict['date']}, {df_row_dict['time']} is already in the database.")


def add_callsign(cursor, df_row_dict):
    "Add a single callsign to the database based on a row dict"
    try:
        columns = ', '.join(df_row_dict.keys())
        placeholders = ', '.join(['?'] * len(df_row_dict))
        sql = f"INSERT INTO callsign ({columns}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(df_row_dict.values()))
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"{df_row_dict['callsign']} is already in the database.")


def get_callsign_id(cursor, callsign):
    "return a callsign_id or raise a CallSignMissing exception"
    cursor.execute(f'SELECT * FROM callsign WHERE callsign="{callsign}"')
    results = cursor.fetchall()
    if len(results) > 0:
        callsign_id = results[0][0]
        return callsign_id
    else:
        raise CallSignMissing(f"Callsign {callsign} not found")
    

def qso_df_by_callsign(callsign, db_path):
    "Given a callsign string, return a DataFrame with all of the associated qso's."
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # get the callsign_id
        try:
            callsign_id = get_callsign_id(cursor, callsign)
            
            # Now get all the qso's by that callsign and return a DataFrame
            sql = f"SELECT * FROM qso WHERE callsign_id = {callsign_id}" # fix injection hazard
            df = pd.read_sql_query(sql, conn)
            return df
        except CallSignMissing as e:
            print(str(e))
            raise SystemExit("Please enter a valid callsign")


def get_callsign_df(callsign, db_path):
    "Return a DataFrame given a callsign"
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # get the callsign_id
        try:
            callsign_id = get_callsign_id(cursor, callsign)
            
            sql = f'SELECT * FROM callsign WHERE callsign_id={callsign_id}'
            df = pd.read_sql_query(sql, conn)
            return df
        except CallSignMissing as e:
            print(str(e))
            raise SystemExit("Please enter a valid callsign")

def print_callsign_and_qsos(callsign, db_path):
    "print callsign info and associated qsos given a callsign"
    print(get_callsign_df(callsign, db_path))
    print(qso_df_by_callsign(callsign, db_path))

def get_or_create_callsign(cursor, callsign):
    """
    Given a callsign string and a database cursor, return the callsign_id.
    Prompt for and create the callsign entry if it doesn't exist. 
    """
    # check for the callsign
    # get the callsign_id
    cursor.execute(f"SELECT * FROM callsign WHERE callsign = ?", (callsign,))
    results = cursor.fetchall()
    if len(results) > 0:
        return results[0][0] # callsign_id
    else:
        return prompt_for_callsign(cursor, callsign)


def prompt_for_qsos(cursor):
    "Prompt for and add new qso's.  Prompt for callsign details if a new callsign"
    
    def is_float(val):
        try:
            float(val)
            return True
        except ValueError:
            return "Please enter a valid float."
    
    get_more = True

    while get_more:
        current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        current_time = datetime.now(timezone.utc).strftime("%H%M")

        answers = questionary.form(
            callsign = questionary.text("callsign:"),
            frequency = questionary.text("frequency:", validate=is_float),
            date = questionary.text("date:", default=current_date),
            time = questionary.text("time:", default=current_time),
            band = questionary.select("band:", choices=["20m", "40m", "17m", "15m", "12m", "10m", "80m", "2m", "70cm", "6m", "160m"]),
            mode = questionary.select("mode:", choices=["SSB", "FT8", "FT4", "FM"]),
            rst_sent = questionary.text("rst sent:", default='5/9'),
            rst_rcvd = questionary.text("rst rcvd:", default='5/9'),
            qso = questionary.confirm("qso?"),
            comment = questionary.text("comment:", default=''),
        ).ask()

        get_more = questionary.confirm("another qso?").ask()
        answers['frequency'] = float(answers['frequency'])

        add_qso(cursor, answers)


def prompt_for_callsign(cursor, callsign=None):
    "Prompt for and add a new callsign. Returns the callsign_id."
    
    # if callsign isn't supplied, prompt for it
    if callsign == None:
        callsign = questionary.text("callsign:").ask()
    else:
        print(f'Creating new callsign entry for {callsign}')
    
    answers = questionary.form(
        name = questionary.text("name:"),
        location = questionary.text("location:"),
        rig = questionary.text("rig:"),
        grid = questionary.text("grid:"),
        comment = questionary.text("comment:")
    ).ask()
    answers['callsign'] = callsign

    # insert the database entry, returns the callsign_id
    return add_callsign(cursor, answers)


def get_column_type(cursor, table, column):
    "get a column type given a table and column"
    try:
        sql = f"PRAGMA table_info({table})"
        cursor.execute(sql)
        column_info = {col[1]: col[2] for col in cursor.fetchall()}
        return column_info.get(column)
    except sqlite3.OperationalError:
        print(f'Bad table or column: {sql}')


def prompt_for_update(cursor):
    "Prompt for and add an update to one column"

    answers = questionary.form(
        table = questionary.text("table:"),
        column = questionary.text("column:"),
        where = questionary.text("WHERE (column=value):"),
        new_value = questionary.text("new value:")
    ).ask()

    # confirm
    val = answers['new_value']
    confirmation_prompt = f' {answers["table"]}, setting {answers["column"]}={val} WHERE {answers["where"]}' # fix injection hazard
    if not questionary.confirm(f'are you sure you want to update table:{confirmation_prompt}:').ask():
        print('canceling update')
        return
    
    # Update the database entry
    try:
        if get_column_type(cursor, answers['table'], answers['column']) != 'REAL':
            val = f'"{val}"'
        sql = f'UPDATE {answers["table"]} SET {answers["column"]}={val} WHERE {answers["where"]}'
        cursor.execute(sql)
        return cursor.lastrowid
    except sqlite3.OperationalError:
        print(f"Invalid operation: {sql}")


def run_db_connection(db_path, db_update_function):
    """
    Open a connection to the database at db_path,
    then call db_update_function, passing a cursor as the single argument.
    The connection is committed after the function returns.
    """
    with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = 1")
            cursor = conn.cursor()
            db_update_function(cursor)
            conn.commit()


# handle command line arguments
def main():
    parser = argparse.ArgumentParser(
        description="A ham radio logger."
    )
    
    # optional database location, defaults to ./qso.db
    parser.add_argument("-d", "--db_file", default='./qso.db', help="database file location, defaults to ./qso.db")

    # prompt for qsos
    parser.add_argument("-q", "--qso_mode", action="store_true", help="Interactive prompt for new qso's")

    # add a callsign
    parser.add_argument("-ac", "--add_callsign", action="store_true", help="Interactive prompt for one new callsign")

     # prompt for an update
    parser.add_argument("-u", "--update", action="store_true", help="Interactive prompt for one column")

     # print callsign and qso information for one callsign
    parser.add_argument("-cq", "--callsign_qsos", help="Print callsign and qso information for one callsign")

   # create a new database
    parser.add_argument("-cd", "--create_db", action="store_true", help="create a new database at the specified location, defaults to ./qso.db")

    # load a database from an adi file
    parser.add_argument("-ld", "--load_db_from_adi", help="loads a database from the specified adi file location")

    args = parser.parse_args()

    db_path = args.db_file
    if args.create_db:
        create_new_db(db_path)
    
    if args.load_db_from_adi:
        load_from_adi(args.load_db_from_adi, db_path)

    if args.qso_mode:
        run_db_connection(db_path, prompt_for_qsos)
    elif args.add_callsign:
        run_db_connection(db_path, prompt_for_callsign)
    elif args.update:
        run_db_connection(db_path, prompt_for_update)
    elif args.callsign_qsos:
        print_callsign_and_qsos(args.callsign_qsos, db_path)

    exit(0)

if __name__ == "__main__":
    main()

# %%
import sqlite3
with sqlite3.connect("./qso.db") as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sqlite_master WHERE type="table"')
    result = cursor.fetchall()
    print(result)


# %%
