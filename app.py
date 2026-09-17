"""
AIRIS — Ambient Indoor Response & Intelligence System
Flask + Jinja2 + SQLite reference implementation.
"""

import csv
import io
from datetime import datetime, date, timedelta
from calendar import monthrange

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, send_file, jsonify, session
)

from config import Config
import database as db
import sensor_data

app = Flask(__name__)
app.config.from_object(Config)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

db.init_db()

NAV_SECTIONS = [
    {
        "heading": "MONITORING",
        "items": [
            {"label": "Dashboard", "endpoint": "dashboard", "icon": "grid"},
            {"label": "Live Monitoring", "endpoint": "live_monitoring", "icon": "pulse"},
            {"label": "Restrooms", "endpoint": "restrooms", "icon": "door"},
            {"label": "Alerts", "endpoint": "alerts", "icon": "bell"},
        ],
    },
    {
        "heading": "MANAGEMENT",
        "items": [
            {"label": "Reports", "endpoint": "reports", "icon": "doc"},
            {"label": "Historical Data Set", "endpoint": "historical", "icon": "chart"},
            {"label": "Sensor Configuration", "endpoint": "sensors", "icon": "gear"},
        ],
    },
]

MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# Endpoints reachable without an authenticated session.
PUBLIC_ENDPOINTS = {"login", "static"}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@app.before_request
def require_login():
    """Gate every route except login/static behind a session check.

    This is the single source of truth for access control — it runs before
    any view function, so a page can't be reached (including via the
    browser's Back/Forward cache) without `session['logged_in']` being set.
    """
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get("logged_in"):
        if request.path.startswith("/api/"):
            # JSON callers get a status code they can act on rather than a
            # login page they'd try (and fail) to parse.
            return jsonify({"error": "unauthenticated"}), 401
        return redirect(url_for("login", next=request.path))
    return None


@app.after_request
def add_no_cache_headers(response):
    """Prevent the browser from serving cached authenticated pages.

    Without this, pressing Back after logout can render a page straight
    from the browser's back-forward cache instead of re-requesting it —
    which would skip the before_request check above entirely.
    """
    if request.endpoint not in ("static",):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            session.permanent = remember
            next_url = request.form.get("next") or url_for("dashboard")
            return redirect(next_url)

        error = "Invalid credentials — try again"

    return render_template("login.html", next=request.args.get("next", ""), error=error)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _sensor_config():
    """Editable sensor configuration, keyed by restroom code."""
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT sensors.*, restrooms.code AS restroom_code "
        "FROM sensors JOIN restrooms ON restrooms.id = sensors.restroom_id"
    ).fetchall()
    conn.close()
    return {row["restroom_code"]: row for row in rows}


def _whole(value):
    """Render a REAL column that holds a whole number as an integer."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return value


def _threshold_label(value, unit):
    """'130.0' + 'ppb' -> '130 ppb'. Units that read as suffixes (%, °C) stay
    tight against the number."""
    number = int(value) if float(value).is_integer() else value
    spacer = "" if unit in ("%", "°C") else " "
    return f"{number}{spacer}{unit}"


def _apply_sensor_config(readings):
    """Overlay the admin-editable thresholds onto a live reading set."""
    config = _sensor_config()
    for r in readings:
        sensor = config.get(r["code"])
        if not sensor:
            continue
        r["sensor_type"] = sensor["sensor_type"]
        r["threshold_value"] = sensor["threshold_value"]
        r["sensor_unit"] = sensor["unit"]
        r["sensor_status"] = sensor["status"]
        current = {
            "VOC": r["voc"], "CO2": r["co2"],
            "Humidity": r["humidity"], "Temperature": r["temperature"],
        }.get(sensor["sensor_type"], 0)
        r["current_for_sensor"] = current
        r["over_threshold"] = current > sensor["threshold_value"]
        r["threshold_label"] = _threshold_label(
            sensor["threshold_value"], sensor["unit"]
        )
    return readings


def _persist_readings(readings):
    """Write the latest snapshot back to SQLite so reports and exports see the
    same numbers the dashboard is showing."""
    conn = db.get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in readings:
        conn.execute(
            """UPDATE restrooms SET aqi = ?, temperature = ?, humidity = ?, voc = ?,
               co2 = ?, occupancy = ?, status = ?, condition_note = ?, updated_at = ?
               WHERE code = ?""",
            (r["aqi"], r["temperature"], r["humidity"], r["voc"], r["co2"],
             r["occupancy"], r["status"], r["condition_note"], now, r["code"]),
        )
    conn.commit()
    conn.close()


def get_snapshot(persist=True):
    """Current readings + building summary, ready for templates or JSON."""
    snap = sensor_data.snapshot()
    _apply_sensor_config(snap["restrooms"])
    if persist:
        _persist_readings(snap["restrooms"])
    return snap


def get_restrooms_with_sensors():
    return get_snapshot()["restrooms"]


def get_alert_counts(conn):
    total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    warning = conn.execute("SELECT COUNT(*) FROM alerts WHERE severity='warning'").fetchone()[0]
    info = conn.execute("SELECT COUNT(*) FROM alerts WHERE severity='info'").fetchone()[0]
    unread = conn.execute("SELECT COUNT(*) FROM alerts WHERE is_read=0").fetchone()[0]
    return {"all": total, "warning": warning, "info": info, "unread": unread}


def _account():
    """The profile shown in the header dropdown and on Profile & Settings."""
    try:
        conn = db.get_connection()
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        conn.close()
        return dict(user) if user else None
    except Exception:  # database not ready yet — header still renders
        return None


@app.context_processor
def inject_globals():
    account = _account() if session.get("logged_in") else None
    return {
        "nav_sections": NAV_SECTIONS,
        "building_name": Config.BUILDING_NAME,
        "now": datetime.now(),
        "current_user_name": session.get("username", "").upper() or None,
        "account": account,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    snap = get_snapshot()
    restrooms = snap["restrooms"]
    summary = snap["summary"]

    conn = db.get_connection()
    alert_counts = get_alert_counts(conn)
    sensors_online = conn.execute("SELECT COUNT(*) FROM sensors WHERE status='Online'").fetchone()[0]
    sensors_total = conn.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]

    recent_alerts = conn.execute(
        "SELECT alerts.*, restrooms.name AS restroom_name FROM alerts "
        "JOIN restrooms ON restrooms.id = alerts.restroom_id "
        "ORDER BY alerts.id DESC LIMIT 4"
    ).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        active="dashboard",
        summary=summary,
        restrooms=restrooms,
        alert_counts=alert_counts,
        sensors_online=sensors_online,
        sensors_total=sensors_total,
        recent_alerts=recent_alerts,
        last_updated=snap["updated_at"],
        snapshot=snap,
    )


@app.route("/api/readings")
def api_readings():
    """Live reading feed polled by the dashboard and Live Monitoring.

    This is the seam for real hardware: swap sensor_data.snapshot() for a
    real source and the front end keeps working unchanged.
    """
    snap = get_snapshot(persist=False)
    return jsonify(snap)


@app.route("/live-monitoring")
def live_monitoring():
    snap = get_snapshot()
    return render_template(
        "live_monitoring.html", active="live_monitoring",
        restrooms=snap["restrooms"], summary=snap["summary"], snapshot=snap,
    )


@app.route("/restrooms")
def restrooms():
    snap = get_snapshot()
    return render_template(
        "restrooms.html", active="restrooms",
        restrooms=snap["restrooms"], summary=snap["summary"], snapshot=snap,
    )


@app.route("/alerts")
def alerts():
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT alerts.*, restrooms.name AS restroom_name FROM alerts "
        "JOIN restrooms ON restrooms.id = alerts.restroom_id "
        "ORDER BY alerts.id ASC"
    ).fetchall()
    counts = get_alert_counts(conn)
    conn.close()
    return render_template("alerts.html", active="alerts", alerts=rows, counts=counts)


@app.route("/alerts/mark-read/<int:alert_id>", methods=["POST"])
def mark_alert_read(alert_id):
    conn = db.get_connection()
    conn.execute("UPDATE alerts SET is_read = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True})
    return redirect(url_for("alerts"))


@app.route("/reports")
def reports():
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
    conn.close()
    restroom_codes = ["All Restrooms"] + [f"Restroom {c}" for c in "ABCDEF"]
    return render_template("reports.html", active="reports", reports=rows, restroom_codes=restroom_codes)


@app.route("/reports/generate", methods=["POST"])
def generate_report():
    period = request.form.get("period", "").strip() or "July 2026"
    scope = request.form.get("scope", "").strip() or "All Restrooms"
    kind = "incident" if scope != "All Restrooms" else "monthly"
    title = "Monthly Air Quality Summary" if kind == "monthly" else f"{scope} — Incident Report"
    today = datetime.now()
    generated_on = f"{MONTH_NAMES[today.month][:3]} {today.day}, {today.year}"

    conn = db.get_connection()
    conn.execute(
        "INSERT INTO reports (title, period, scope, generated_on, kind) VALUES (?, ?, ?, ?, ?)",
        (title, period, scope, generated_on, kind),
    )
    conn.commit()
    conn.close()
    flash(f"Report generated: {title} · {period} · {scope}", "success")
    return redirect(url_for("reports"))


@app.route("/reports/download/<int:report_id>")
def download_report(report_id):
    conn = db.get_connection()
    report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    restrooms_list = conn.execute("SELECT * FROM restrooms ORDER BY code").fetchall()
    conn.close()
    if not report:
        flash("That report could not be found.", "error")
        return redirect(url_for("reports"))

    buf = io.StringIO()
    buf.write(f"{report['title']}\n")
    buf.write(f"Period: {report['period']}\n")
    buf.write(f"Scope: {report['scope']}\n")
    buf.write(f"Generated: {report['generated_on']}\n")
    buf.write(f"Building: {Config.BUILDING_NAME}\n")
    buf.write("-" * 60 + "\n\n")

    if report["scope"] == "All Restrooms":
        buf.write(
            f"{'Restroom':<14}{'Temp (C)':<10}{'Humidity':<10}"
            f"{'VOC (ppb)':<12}{'CO2 (ppm)':<10}{'Status':<10}\n"
        )
        for r in restrooms_list:
            buf.write(
                f"{r['name']:<14}{r['temperature']:<10.1f}{_whole(r['humidity']):<10}"
                f"{_whole(r['voc']):<12}{_whole(r['co2']):<10}{r['status'].title():<10}\n"
            )
    else:
        target = next((r for r in restrooms_list if r["name"] == report["scope"]), None)
        if target:
            buf.write(f"Restroom: {target['name']} ({target['floor']} · {target['wing']})\n")
            buf.write(f"Temperature: {target['temperature']:.1f} C\n")
            buf.write(f"Humidity: {_whole(target['humidity'])}%\n")
            buf.write(f"VOC: {_whole(target['voc'])} ppb\n")
            buf.write(f"CO2: {_whole(target['co2'])} ppm\n")
            buf.write(f"AQI: {_whole(target['aqi'])}\n")
            buf.write(f"Occupancy: {_whole(target['occupancy'])}\n")
            buf.write(f"Status: {target['status'].title()}\n")
            buf.write(f"Note: {target['condition_note']}\n")

    buf.write("\nGenerated by AIRIS — Ambient Indoor Response & Intelligence System.\n")

    file_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"AIRIS_{report['title'].replace(' ', '_').replace('—', '-')}_{report['period'].replace(' ', '_')}.txt"
    return send_file(file_bytes, as_attachment=True, download_name=filename, mimetype="text/plain")


@app.route("/historical")
def historical():
    year = request.args.get("year", type=int, default=2026)
    month = request.args.get("month", type=int, default=7)
    month = max(1, min(12, month))

    conn = db.get_connection()
    prefix = f"{year:04d}-{month:02d}-"
    rows = conn.execute(
        "SELECT * FROM historical_readings WHERE reading_date LIKE ? ORDER BY reading_date ASC",
        (prefix + "%",),
    ).fetchall()
    conn.close()

    def day_aqi(r):
        return sensor_data.aqi_from_averages(
            r["avg_temp"], r["avg_humidity"], r["avg_voc"], r["avg_co2"]
        )

    chart_points = [{"label": r["reading_date"][-2:], "aqi": day_aqi(r)} for r in rows]

    if rows:
        avg_temp = round(sum(r["avg_temp"] for r in rows) / len(rows), 1)
        avg_humidity = round(sum(r["avg_humidity"] for r in rows) / len(rows))
        avg_voc = round(sum(r["avg_voc"] for r in rows) / len(rows))
        alerts_total = sum(r["alerts_count"] for r in rows)
    else:
        avg_temp = avg_humidity = avg_voc = alerts_total = 0

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template(
        "historical.html",
        active="historical",
        rows=rows,
        chart_points=chart_points,
        avg_temp=avg_temp,
        avg_humidity=avg_humidity,
        avg_voc=avg_voc,
        alerts_total=alerts_total,
        month_label=f"{MONTH_NAMES[month]} {year}",
        year=year, month=month,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
    )


@app.route("/historical/export.csv")
def export_historical_csv():
    year = request.args.get("year", type=int, default=2026)
    month = request.args.get("month", type=int, default=7)

    conn = db.get_connection()
    prefix = f"{year:04d}-{month:02d}-"
    rows = conn.execute(
        "SELECT * FROM historical_readings WHERE reading_date LIKE ? ORDER BY reading_date ASC",
        (prefix + "%",),
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Avg Temp (C)", "Avg Humidity (%)", "Avg VOC (ppb)", "Avg CO2 (ppm)", "Alerts"])
    for r in rows:
        writer.writerow([
            r["reading_date"], round(r["avg_temp"], 1), _whole(r["avg_humidity"]),
            _whole(r["avg_voc"]), _whole(r["avg_co2"]), r["alerts_count"],
        ])

    file_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"AIRIS_historical_{year:04d}-{month:02d}.csv"
    return send_file(file_bytes, as_attachment=True, download_name=filename, mimetype="text/csv")


@app.route("/sensors")
def sensors():
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT sensors.*, restrooms.name AS restroom_name, restrooms.code AS restroom_code "
        "FROM sensors JOIN restrooms ON restrooms.id = sensors.restroom_id "
        "ORDER BY restrooms.code ASC"
    ).fetchall()
    conn.close()
    return render_template("sensors.html", active="sensors", sensors=rows)


@app.route("/sensors/save/<int:sensor_id>", methods=["POST"])
def save_sensor(sensor_id):
    value = request.form.get("threshold_value", type=float)
    conn = db.get_connection()
    if value is None:
        flash("Enter a valid numeric threshold.", "error")
    else:
        conn.execute("UPDATE sensors SET threshold_value = ? WHERE id = ?", (value, sensor_id))
        conn.commit()
        flash("Threshold updated.", "success")
    conn.close()
    return redirect(url_for("sensors"))


@app.route("/settings")
def settings():
    conn = db.get_connection()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    prefs = conn.execute("SELECT * FROM settings WHERE user_id = ?", (user["id"],)).fetchone()
    conn.close()
    return render_template("settings.html", active="settings", user=user, prefs=prefs)


@app.route("/settings/save", methods=["POST"])
def save_settings():
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip()
    email_alerts = 1 if request.form.get("email_alerts") else 0
    sms_alerts = 1 if request.form.get("sms_alerts") else 0
    weekly_digest = 1 if request.form.get("weekly_digest") else 0

    conn = db.get_connection()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    if display_name and email:
        conn.execute(
            "UPDATE users SET display_name = ?, email = ? WHERE id = ?",
            (display_name, email, user["id"]),
        )
    conn.execute(
        "UPDATE settings SET email_alerts = ?, sms_alerts = ?, weekly_digest = ? WHERE user_id = ?",
        (email_alerts, sms_alerts, weekly_digest, user["id"]),
    )
    conn.commit()
    conn.close()
    flash("Settings saved.", "success")
    return redirect(url_for("settings"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("login"))


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
