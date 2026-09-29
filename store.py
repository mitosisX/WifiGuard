"""SQLite event history (drops, reconnects, recoveries). One short-lived connection per call,
so it is safe to use from both the monitor thread and the GUI thread."""
import csv
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "history.db")

# kind: 'drop' | 'auto' (automatic reconnect) | 'manual' (reconnect button) | 'recovered'
_SCHEMA = """CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,            -- local time, ISO 8601, seconds
    kind TEXT NOT NULL,
    network TEXT NOT NULL DEFAULT '',
    downtime INTEGER             -- seconds, only on 'recovered'
)"""


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute(_SCHEMA)
    return con


def add(kind, network="", downtime=None):
    with closing(_connect()) as con, con:
        con.execute("INSERT INTO events (ts, kind, network, downtime) VALUES (?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), kind, network, downtime))


def reconnects_per_day(days=14):
    """[(date, automatic reconnects)] for the last `days` days, oldest first, zeros included."""
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    with closing(_connect()) as con:
        rows = con.execute("SELECT substr(ts,1,10), COUNT(*) FROM events "
                           "WHERE kind='auto' AND ts >= ? GROUP BY 1", (start.isoformat(),)).fetchall()
    counts = dict(rows)
    return [(start + timedelta(days=i), counts.get((start + timedelta(days=i)).isoformat(), 0))
            for i in range(days)]


def today_count():
    return reconnects_per_day(1)[0][1]


def average_downtime(days=30):
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with closing(_connect()) as con:
        (avg,) = con.execute("SELECT AVG(downtime) FROM events WHERE kind='recovered' AND ts >= ?",
                             (since,)).fetchone()
    return avg


def recent(limit=200):
    with closing(_connect()) as con:
        return con.execute("SELECT ts, kind, network, downtime FROM events "
                           "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def clear():
    with closing(_connect()) as con, con:
        con.execute("DELETE FROM events")


def export_csv(path):
    with closing(_connect()) as con:
        rows = con.execute("SELECT ts, kind, network, downtime FROM events ORDER BY id").fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "network", "downtime_seconds"])
        w.writerows(rows)
    return len(rows)
