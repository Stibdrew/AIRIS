# AIRIS — Ambient Indoor Response & Intelligence System

A Flask + Jinja2 + SQLite reference implementation of the AIRIS indoor
environmental monitoring dashboard for the SH Building.

## Stack

- Python 3 + Flask (routing, templating)
- Jinja2 (server-rendered HTML, reusable macros for sidebar/header/cards/badges/tables)
- Vanilla JavaScript (sidebar toggle, alert filtering, live-reading simulation, AQI chart — no build step, no CDN dependency)
- SQLite (`data/airis.db`, created and seeded automatically on first run)

No React, no Node, no external CSS/JS frameworks — everything runs from `python app.py`.

## Project structure

```
airis-flask2/
├── app.py                      routes, request handling, /api/readings
├── config.py                   paths and constants
├── sensor_data.py              MOCK sensor source — all current readings
├── database.py                 schema + seed data (seeded from sensor_data)
├── templates/
│   ├── base.html                shell: sidebar + header + flash messages
│   ├── components/
│   │   └── macros.html          sidebar, topbar, page_banner, metric_card,
│   │                            status_badge, metric_card, restroom_card,
│   │                            notification_card, toggle, icon
│   ├── dashboard.html
│   ├── live_monitoring.html
│   ├── restrooms.html
│   ├── alerts.html
│   ├── reports.html
│   ├── historical.html
│   ├── sensors.html
│   ├── settings.html
│   ├── login.html
│   └── 404.html
├── static/
│   ├── css/style.css            all design tokens + layout + components
│   └── js/app.js                sidebar, account dropdown, hover detail,
│                                live reading poller, alert filters, chart
├── data/
│   └── airis.db                 created automatically on first run
├── requirements.txt
└── README.md
```

## Setup (Windows, VS Code)

```powershell
mkdir C:\projects\airis-flask
cd C:\projects\airis-flask
# copy these files here, then:
code .
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** — it redirects to `/dashboard`. Stop the server with `Ctrl+C`.

In VS Code, press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one
inside `.\venv\`, or the Run button will use the wrong Python.

## Setup (macOS/Linux)

```bash
cd airis-flask2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded ... execution policies` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again |
| `'python' is not recognized` | Install from python.org with **Add Python to PATH** ticked, or use `py -3` |
| `ModuleNotFoundError: No module named 'flask'` | Venv isn't active — the prompt should start with `(venv)` |
| `Address already in use` / port 5000 busy | Change `port=5000` at the bottom of `app.py`, or stop the other process |
| `TemplateNotFound` | You're running from the wrong folder — `app.py` must sit beside `templates/` |
| CSS changes don't show | Hard refresh with `Ctrl+F5` |
| Want a clean database | Stop the server, delete `data/airis.db`, restart — it reseeds automatically |

## Routes

| Route | Purpose |
|---|---|
| `/` | Redirects to `/dashboard` |
| `/dashboard` | Building averages, restroom status grid, alert summary, sensor status, recent notifications |
| `/live-monitoring` | Per-restroom readings table; values nudge every 4s client-side for online sensors |
| `/restrooms` | Restroom cards: readings, sensor status, threshold status |
| `/alerts` | Notification centre with working All / Warning / Info / Unread filters and mark-as-read |
| `/reports` | Generate a report (period + scope) and download any report as a text summary |
| `/historical` | Monthly averages, a daily AQI bar chart, a daily readings table, month navigation, CSV export |
| `/sensors` | Per-restroom threshold editor — each row saves independently |
| `/settings` | Profile fields and notification toggles, saved to SQLite |
| `/login` | Sign in (`admin` / `airis2025`, set in `config.py`) |
| `/api/readings` | JSON feed of current readings + building summary |
| `/logout` | Clears the session and redirects to `/login` |

## Database

SQLite tables, created and seeded automatically on first run if `data/airis.db`
doesn't exist or is empty:

- **users** — the single admin profile shown on Settings
- **restrooms** — A–F, with current readings and status
- **sensors** — one threshold-monitoring sensor per restroom
- **alerts** — the 4 seeded notifications (2 warning, 2 info, 2 unread)
- **reports** — the 3 seeded reports; `Generate Report` adds rows here
- **settings** — notification preferences for the admin user
- **historical_readings** — June and July 2026, one row per day (July 1–5
  match the spec's exact figures; the rest are generated to hover around the
  stated monthly averages)

To connect real sensors, replace `sensor_data.snapshot()` with your live data
source (MQTT subscriber, an HTTP ingest route, or a serial/GPIO reader) and
keep the returned shape. The templates, the JS and `/api/readings` all consume
that one function, so nothing else needs to change. Thresholds and sensor
online/offline state stay in SQLite because they're editable from the Sensor
Configuration page.

`SCHEMA_VERSION` in `database.py` guards the reading-derived tables: bump it
and the next start rewrites restrooms, sensors, alerts and historical rows
from `sensor_data.py` while leaving your user profile, settings and generated
reports alone.

## Notes on decisions

- **Mock sensor data lives in `sensor_data.py`.** It is the single source of
  truth for every current reading (AQI, temperature, humidity, VOC, CO2,
  occupancy) plus the warning thresholds. Routes, templates and
  `database.py`'s seed all read from it, so no reading values are hardcoded
  in components. Values drift gently around their baselines and are pulled
  back toward them, so they stay plausible over a long session. To connect
  real hardware, replace `snapshot()` — keep the returned shape and nothing
  else has to change.
- **`/api/readings`** returns that same snapshot as JSON. The dashboard,
  Restrooms and Live Monitoring pages poll it every 4 seconds and repaint
  in place. It requires a session and returns `401` without one; the poller
  stops and redirects to `/login` on a 401.
- **Profile & Settings and Log Out are in the header, not the sidebar.** The
  avatar in the top right opens an account dropdown (click to toggle, click
  outside or press Escape to close). Log Out POSTs to `/logout`, which clears
  the session; `before_request` gates every non-public route and
  `after_request` sends no-store headers so the browser's Back button can't
  render a cached authenticated page.
- **Hover detail** is one shared `position: fixed` panel created in
  `app.js` and appended to `<body>`, so it can't be clipped by a scroll
  container and never shifts the layout. Stat cards and restroom cards opt
  in with `data-tip`; the panel flips above the anchor when there's no room
  below and clamps to the viewport edges.
- **Restroom D**'s Humidity sensor is **Offline**, so its humidity value
  holds still while its other readings keep moving. Its air-quality status
  is still **Normal** — sensor health and air quality are separate things,
  and the offline state is shown by the red sensor chip and in the hover
  detail rather than by the status badge.
- **The AQI chart** is drawn from a JSON data attribute in
  `static/js/app.js` — no charting library or CDN script, so the app works
  with no internet connection.
- **AQI is derived**, not stored independently: it's each restroom's
  baseline AQI adjusted by how far its VOC/CO2/humidity/temperature have
  moved from their baselines, so it can never disagree with the readings
  next to it.
- **This is a separate build from the earlier React/Vite AIRIS project.**
  The restroom data here (temperatures, VOC readings, etc.) was written
  fresh from *this* spec's numbers (sensor thresholds, alert log) rather than
  reconciled with the React version's mock data — the two currently disagree
  on exact reading values for some restrooms.
#   A I R I S  
 