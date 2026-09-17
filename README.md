# AIRIS - Air Quality Monitoring Dashboard

AIRIS (Ambient Indoor Response and Intelligence System) is a web dashboard that monitors air quality across 6 restrooms in a building. It tracks temperature, humidity, VOC, CO2, and occupancy, and shows live-updating stats and alerts.

Built with: Python (Flask) + SQLite + plain HTML/CSS/JavaScript. No React, no Node.js, no build tools - just run one Python file.

Quick Start: install Python 3, then run python -m venv venv, then .\venv\Scripts\Activate.ps1, then pip install -r requirements.txt, then python app.py. Open http://127.0.0.1:5000 in your browser.

Login: username admin, password airis2025 (set in config.py).

The sensor readings on this dashboard are simulated, not real data - this is a demo/prototype. They all live in one file, sensor_data.py, and drift gently over time so the dashboard feels live.
