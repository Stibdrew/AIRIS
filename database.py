"""
AIRIS database layer.

Plain sqlite3 (no ORM) — schema creation, seed data, and small helper
functions used by the Flask routes in app.py.
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta

from config import Config
import sensor_data

random.seed(42)  # deterministic seed data across restarts


def get_connection():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name  TEXT NOT NULL,
    email         TEXT NOT NULL,
    role          TEXT NOT NULL,
    building      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS restrooms (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,   -- 'A' .. 'F'
    name          TEXT NOT NULL,          -- 'Restroom A'
    floor         TEXT NOT NULL,
    wing          TEXT NOT NULL,
    aqi           INTEGER NOT NULL DEFAULT 0,
    temperature   REAL NOT NULL,
    humidity      REAL NOT NULL,
    voc           REAL NOT NULL,
    co2           REAL NOT NULL,
    occupancy     INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,          -- 'normal' | 'warning'
    condition_note TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensors (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    restroom_id    INTEGER NOT NULL REFERENCES restrooms(id),
    sensor_type    TEXT NOT NULL,     -- VOC | CO2 | Humidity | Temperature
    threshold_value REAL NOT NULL,
    unit           TEXT NOT NULL,     -- ppb | ppm | % | °C
    status         TEXT NOT NULL      -- Online | Offline
);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    restroom_id  INTEGER NOT NULL REFERENCES restrooms(id),
    severity     TEXT NOT NULL,      -- warning | info
    title        TEXT NOT NULL,
    detail       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    display_time TEXT NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    period       TEXT NOT NULL,       -- 'June 2026'
    scope        TEXT NOT NULL,       -- 'All Restrooms' | 'Restroom C'
    generated_on TEXT NOT NULL,       -- 'Jul 1, 2026'
    kind         TEXT NOT NULL DEFAULT 'monthly'  -- monthly | incident
);

CREATE TABLE IF NOT EXISTS settings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    email_alerts   INTEGER NOT NULL DEFAULT 1,
    sms_alerts     INTEGER NOT NULL DEFAULT 0,
    weekly_digest  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_date  TEXT NOT NULL UNIQUE,  -- 'YYYY-MM-DD'
    avg_temp      REAL NOT NULL,
    avg_humidity  REAL NOT NULL,
    avg_voc       REAL NOT NULL,
    avg_co2       REAL NOT NULL,
    alerts_count  INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

# Restroom + sensor baselines now live in sensor_data.py (the single mock
# source). This module only persists them; it no longer defines readings.

ALERT_SEED = [
    # restroom_code, severity, title, detail, display_time, is_read
    ("C", "warning", "Restroom C — High VOC",
     "VOC reading crossed the 130 ppb threshold and is still elevated.", "10:22 AM", 0),
    ("D", "info", "Restroom D — Humidity sensor offline",
     "Humidity sensor stopped reporting; other readings are unaffected.", "9:47 AM", 0),
    ("A", "info", "Restroom A — Threshold updated",
     "Max humidity threshold changed from 70% to 75% by admin@sh.edu.", "9:10 AM", 1),
    ("F", "warning", "Restroom F — Brief VOC spike",
     "VOC exceeded threshold for under 2 minutes, then returned to normal.", "Yesterday, 4:52 PM", 1),
]

REPORT_SEED = [
    ("Monthly Air Quality Summary", "June 2026", "All Restrooms", "Jul 1, 2026", "monthly"),
    ("Monthly Air Quality Summary", "May 2026", "All Restrooms", "Jun 1, 2026", "monthly"),
    ("Restroom C — Incident Report", "May 2026", "Restroom C", "May 14, 2026", "incident"),
]

# Exact rows given in the spec for July 2026
JULY_EXACT = [
    ("2026-07-01", 27.7, 62, 72, 608, 0),
    ("2026-07-02", 27.6, 63, 76, 615, 1),
    ("2026-07-03", 28.4, 66, 94, 688, 2),
    ("2026-07-04", 27.5, 63, 84, 616, 0),
    ("2026-07-05", 27.9, 65, 81, 648, 1),
]


def _synthetic_month(year, month, num_days, overrides=None):
    """Generate a month of plausible historical rows, honoring any exact
    override rows (date -> tuple) supplied for the start of the month."""
    overrides = overrides or {}
    rows = []
    for day in range(1, num_days + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        if date_str in overrides:
            rows.append(overrides[date_str])
            continue
        # gentle wander around the spec's stated monthly averages
        temp = round(27.6 + random.uniform(-1.2, 1.2), 1)
        humidity = round(64 + random.uniform(-6, 6))
        voc = round(78 + random.uniform(-12, 22))
        co2 = round(690 + random.uniform(-60, 120))
        alerts = random.choice([0, 0, 0, 1, 1, 2])
        rows.append((date_str, temp, humidity, voc, co2, alerts))
    return rows


def _seed_historical(conn):
    overrides = {row[0]: row for row in JULY_EXACT}
    rows = []
    rows += _synthetic_month(2026, 6, 30)
    rows += _synthetic_month(2026, 7, 31, overrides=overrides)
    conn.executemany(
        """INSERT OR IGNORE INTO historical_readings
           (reading_date, avg_temp, avg_humidity, avg_voc, avg_co2, alerts_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


SCHEMA_VERSION = "3"  # bump to force a reseed of the sensor-derived tables


def _column_names(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_columns(conn):
    """Add columns introduced after the first release, so an existing
    data/airis.db keeps working instead of throwing OperationalError."""
    existing = _column_names(conn, "restrooms")
    if "aqi" not in existing:
        conn.execute("ALTER TABLE restrooms ADD COLUMN aqi INTEGER NOT NULL DEFAULT 0")
    if "occupancy" not in existing:
        conn.execute("ALTER TABLE restrooms ADD COLUMN occupancy INTEGER NOT NULL DEFAULT 0")


def _stored_version(conn):
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return row[0] if row else None


def _seed_account(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (display_name, email, role, building) VALUES (?, ?, ?, ?)",
            ("SH Building Admin", "admin@sh.edu", "Facility Administrator", "SH Building"),
        )
    user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    if conn.execute("SELECT COUNT(*) FROM settings WHERE user_id = ?", (user_id,)).fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO settings (user_id, email_alerts, sms_alerts, weekly_digest) VALUES (?, 1, 0, 1)",
            (user_id,),
        )


def _seed_sensor_tables(conn):
    """(Re)build restrooms, sensors and alerts from the mock sensor source.

    Wiped and rewritten rather than patched so the database can never drift
    away from sensor_data.py — that module is the single source of truth for
    baseline readings.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM sensors")
    conn.execute("DELETE FROM restrooms")

    restroom_ids = {}
    for r in sensor_data.baseline_readings():
        cur = conn.execute(
            """INSERT INTO restrooms
               (code, name, floor, wing, aqi, temperature, humidity, voc, co2,
                occupancy, status, condition_note, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["code"], r["name"], r["floor"], r["wing"], r["aqi"], r["temperature"],
             r["humidity"], r["voc"], r["co2"], r["occupancy"], r["status"],
             r["condition_note"], now),
        )
        restroom_ids[r["code"]] = cur.lastrowid

        conn.execute(
            """INSERT INTO sensors (restroom_id, sensor_type, threshold_value, unit, status)
               VALUES (?, ?, ?, ?, ?)""",
            (cur.lastrowid, r["sensor_type"], r["threshold_value"],
             r["sensor_unit"], r["sensor_status"]),
        )

    for code, severity, title, detail, display_time, is_read in ALERT_SEED:
        conn.execute(
            """INSERT INTO alerts (restroom_id, severity, title, detail, created_at, display_time, is_read)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (restroom_ids[code], severity, title, detail, now, display_time, is_read),
        )

    for title, period, scope, generated_on, kind in REPORT_SEED:
        exists = conn.execute(
            "SELECT 1 FROM reports WHERE title = ? AND period = ?", (title, period)
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO reports (title, period, scope, generated_on, kind)
                   VALUES (?, ?, ?, ?, ?)""",
                (title, period, scope, generated_on, kind),
            )

    conn.execute("DELETE FROM historical_readings")
    _seed_historical(conn)


def init_db():
    os.makedirs(Config.DATA_DIR, exist_ok=True)

    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_columns(conn)

    needs_seed = (
        _stored_version(conn) != SCHEMA_VERSION
        or conn.execute("SELECT COUNT(*) FROM restrooms").fetchone()[0] == 0
    )

    _seed_account(conn)

    if needs_seed:
        _seed_sensor_tables(conn)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )

    conn.commit()
    conn.close()
