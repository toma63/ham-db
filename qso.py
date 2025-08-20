#!/usr/bin/env python3

import argparse
import adif_io
import pandas as pd
import sqlite3

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
        cursor.execute(f"SELECT * FROM callsign WHERE callsign = ?", (callsign,))
        results = cursor.fetchall()
        if len(results) > 0:
            callsign_id = results[0][0]
        else:
            raise CallSignMissing(f"Callsign {callsign} not found.")
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
    except sqlite3.IntegrityError:
        print(f"{df_row_dict['callsign']} is already in the database.")

def qso_df_by_callsign(callsign, db_path):
    "Given a callsign string, return a DataFrame with all of the associated qso's."
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # get the callsign_id
        cursor.execute(f"SELECT * FROM callsign WHERE callsign = ?", (callsign,))
        results = cursor.fetchall()
        if len(results) > 0:
            callsign_id = results[0][0]
        else:
            raise CallSignMissing(f"Callsign {callsign} not found.")
        
        # Now get all the qso's by that callsign and return a DataFrame
        sql = f"SELECT * FROM qso WHERE callsign_id = {callsign_id}"
        df = pd.read_sql_query(sql, conn)
        return df
    
def prompt_for_qsos(db_path):
    "Prompt for and add new qso's.  Prompt for callsign details if a new callsign"

def prompt_for_callsign(db_path):
    "Prompt for and add a new callsign. Returns the callsign_id."

# handle command line arguments
def main():
    parser = argparse.ArgumentParser(
        description="A ham radio logger."
    )
    # Required positional argument: a number
    #parser.add_argument("number", type=int, help="An integer number to be used in calculation")
    
    # database location, defaults to ./qso.db
    parser.add_argument("-d", "--db_file", default='./qso.db', help="database file location, defaults to ./qso.db")

    # Optional flag: uppercase
    parser.add_argument("-u", "--uppercase", action="store_true", help="Print the result in uppercase")

    args = parser.parse_args()

    # Perform a simple calculation
    result = calculate(args.number, args.multiplier)
    result_str = f"The result is {result}"

    # Print result
    if args.uppercase:
        print(result_str.upper())
    else:
        print(result_str)

    exit(0)

if __name__ == "__main__":
    main()
