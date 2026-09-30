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
#       | 'dns_fail' / 'dns_ok' (DNS down while raw internet works)
_SCHEMA = """CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,            -- local time, ISO 8601, seconds
    kind TEXT NOT NULL,
    network TEXT NOT NULL DEFAULT '',
    downtime INTEGER             -- seconds, only on 'recovered'
)"""

# The Activity page's text lines, kept so they survive a restart.
_ACTIVITY_SCHEMA = """CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,            -- local time, ISO 8601, seconds
    msg TEXT NOT NULL
)"""


def clock(dt):
    """12-hour time without seconds, e.g. 10:02AM / 9:05PM."""
    return dt.strftime("%I:%M%p").lstrip("0")


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute(_SCHEMA)
    con.execute(_ACTIVITY_SCHEMA)
    return con


def add(kind, network="", downtime=None):
    with closing(_connect()) as con, con:
        con.execute("INSERT INTO events (ts, kind, network, downtime) VALUES (?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), kind, network, downtime))


def last_drop():
    """When the most recent internet drop happened, or None if none is recorded."""
    with closing(_connect()) as con:
        row = con.execute("SELECT ts FROM events WHERE kind='drop' ORDER BY id DESC LIMIT 1").fetchone()
    return datetime.fromisoformat(row[0]) if row else None


def log_add(msg):
    with closing(_connect()) as con, con:
        con.execute("INSERT INTO activity (ts, msg) VALUES (?,?)",
                    (datetime.now().isoformat(timespec="seconds"), msg))


def log_today():
    """[(time, message)] of today's Activity lines, oldest first."""
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with closing(_connect()) as con:
        rows = con.execute("SELECT ts, msg FROM activity WHERE ts >= ? ORDER BY id",
                           (midnight.isoformat(timespec="seconds"),)).fetchall()
    return [(datetime.fromisoformat(ts), msg) for ts, msg in rows]


def prune_log(days=30):
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with closing(_connect()) as con, con:
        con.execute("DELETE FROM activity WHERE ts < ?", (since,))


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
