# %%
import pandas as pd
import sqlite3
import os
db_path = "./qso.db"

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


# %%
