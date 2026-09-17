"""
AIRIS — centralized MOCK sensor data source.
=============================================

Everything the dashboard shows about *current* air quality comes from this
module. The values here are SIMULATED for the project build — they are not
real sensor readings.

Why it's a separate module
--------------------------
Templates, routes and the seed data all read from here, so there are no
reading values hardcoded inside components. To connect real hardware later
you only need to replace ONE function:

    snapshot()  ->  {"restrooms": [...], "summary": {...}, "updated_at": "..."}

Point it at an MQTT subscriber, an HTTP ingest table, or a serial/GPIO
reader that returns the same dict shape and the whole UI follows — no
template or JavaScript changes required.

Reading shape (one per restroom)
--------------------------------
    code, name, floor, wing,
    aqi, temperature, humidity, voc, co2, occupancy,
    status, condition_note, last_updated,
    sensor_type, threshold_value, sensor_unit, sensor_status, over_threshold
"""

import random
import threading
from collections import deque
from datetime import datetime

# ---------------------------------------------------------------------------
# Baseline readings (MOCK)
# ---------------------------------------------------------------------------
# These are the "at rest" values every restroom is simulated around. Live
# values wander gently near them and are pulled back toward them, so the
# dashboard stays plausible instead of drifting off over a long session.

RESTROOM_PROFILES = [
    {
        "code": "A", "name": "Restroom A", "floor": "1F", "wing": "East Wing",
        "aqi": 92, "temperature": 26.8, "humidity": 61, "voc": 72, "co2": 680,
        "occupancy": 1,
        "sensor": {"type": "VOC", "threshold": 130, "unit": "ppb", "status": "Online"},
    },
    {
        "code": "B", "name": "Restroom B", "floor": "2F", "wing": "East Wing",
        "aqi": 88, "temperature": 27.2, "humidity": 64, "voc": 81, "co2": 720,
        "occupancy": 2,
        "sensor": {"type": "CO2", "threshold": 900, "unit": "ppm", "status": "Online"},
    },
    {
        "code": "C", "name": "Restroom C", "floor": "2F", "wing": "West Wing",
        "aqi": 34, "temperature": 29.1, "humidity": 72, "voc": 145, "co2": 980,
        "occupancy": 3,
        "sensor": {"type": "VOC", "threshold": 130, "unit": "ppb", "status": "Online"},
    },
    {
        "code": "D", "name": "Restroom D", "floor": "2F", "wing": "West Wing",
        "aqi": 90, "temperature": 27.0, "humidity": 60, "voc": 68, "co2": 650,
        "occupancy": 0,
        # Humidity sensor is offline — its humidity value holds instead of moving.
        "sensor": {"type": "Humidity", "threshold": 75, "unit": "%", "status": "Offline"},
    },
    {
        "code": "E", "name": "Restroom E", "floor": "3F", "wing": "East Wing",
        "aqi": 85, "temperature": 26.9, "humidity": 63, "voc": 75, "co2": 700,
        "occupancy": 1,
        "sensor": {"type": "Temperature", "threshold": 30, "unit": "°C", "status": "Online"},
    },
    {
        "code": "F", "name": "Restroom F", "floor": "3F", "wing": "West Wing",
        "aqi": 85, "temperature": 27.4, "humidity": 65, "voc": 79, "co2": 740,
        "occupancy": 1,
        "sensor": {"type": "CO2", "threshold": 900, "unit": "ppm", "status": "Online"},
    },
]

# Warning thresholds used to derive a restroom's overall status. Kept here so
# the dashboard, the restroom cards and the alert copy all agree.
WARN = {
    "voc": 130,       # ppb
    "co2": 900,       # ppm
    "humidity": 75,   # %
    "temperature": 30,  # °C
    "aqi": 50,        # below this is a warning
}

# How far each field may wander from baseline, and how big one step can be.
# Deliberately small: a monitoring dashboard that jumps around reads as broken.
DRIFT = {
    # field:        (max distance from baseline, max change per tick)
    "temperature":  (0.4, 0.15),
    "humidity":     (2.5, 0.9),
    "voc":          (9.0, 3.5),
    "co2":          (30.0, 12.0),
}

PULL = 0.28  # mean reversion strength — keeps values orbiting the baseline

_lock = threading.Lock()
_state = None
_aqi_history = deque(maxlen=6)


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------

def _penalty(temperature, humidity, voc, co2):
    """Air-quality penalty from the raw readings.

    Only ever used as a *difference* against a restroom's baseline penalty,
    so its absolute scale doesn't matter — it just makes AQI move coherently
    with VOC/CO2/humidity/temperature instead of wandering independently.
    """
    return (
        max(0.0, voc - 50) / 2.2
        + max(0.0, co2 - 600) / 14.0
        + max(0.0, humidity - 65) * 0.6
        + max(0.0, temperature - 28) * 2.0
    )


def aqi_for(profile, temperature, humidity, voc, co2):
    """AQI for a live reading, anchored to the restroom's baseline AQI."""
    base = _penalty(
        profile["temperature"], profile["humidity"], profile["voc"], profile["co2"]
    )
    now = _penalty(temperature, humidity, voc, co2)
    return int(max(0, min(100, round(profile["aqi"] - (now - base)))))


def aqi_from_averages(temperature, humidity, voc, co2):
    """Standalone AQI estimate — used by the historical page, which has no
    per-restroom baseline to anchor to."""
    return int(max(5, min(100, round(100 - _penalty(temperature, humidity, voc, co2)))))


def status_for(aqi, temperature, humidity, voc, co2):
    if (
        voc > WARN["voc"]
        or co2 > WARN["co2"]
        or humidity > WARN["humidity"]
        or temperature > WARN["temperature"]
        or aqi < WARN["aqi"]
    ):
        return "warning"
    return "normal"


def note_for(reading, profile):
    """Human-readable condition line, derived rather than hardcoded so it
    stays true when the simulated values move."""
    sensor = profile["sensor"]
    if reading["voc"] > WARN["voc"]:
        return f"VOC {reading['voc']} ppb — above the {WARN['voc']} ppb threshold"
    if reading["co2"] > WARN["co2"]:
        return f"CO₂ {reading['co2']} ppm — above the {WARN['co2']} ppm threshold"
    if reading["humidity"] > WARN["humidity"]:
        return f"Humidity {reading['humidity']}% — above the {WARN['humidity']}% threshold"
    if reading["temperature"] > WARN["temperature"]:
        return f"Temperature {reading['temperature']}°C — above the {WARN['temperature']}°C threshold"
    if sensor["status"] == "Offline":
        return f"{sensor['type']} sensor offline — holding last known value"
    return "Within all thresholds"


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _fresh_state():
    state = {}
    for p in RESTROOM_PROFILES:
        state[p["code"]] = {
            "temperature": p["temperature"],
            "humidity": p["humidity"],
            "voc": float(p["voc"]),
            "co2": float(p["co2"]),
            "occupancy": p["occupancy"],
            "updated": datetime.now(),
        }
    return state


def _held_field(profile):
    """The field whose sensor is offline — it must not move."""
    if profile["sensor"]["status"] == "Offline":
        return {
            "VOC": "voc", "CO2": "co2",
            "Humidity": "humidity", "Temperature": "temperature",
        }.get(profile["sensor"]["type"])
    return None


def _step(current, baseline, field):
    span, jump = DRIFT[field]
    nxt = current + random.uniform(-jump, jump) + (baseline - current) * PULL
    return max(baseline - span, min(baseline + span, nxt))


def _advance(state):
    for p in RESTROOM_PROFILES:
        s = state[p["code"]]
        held = _held_field(p)

        for field in ("temperature", "humidity", "voc", "co2"):
            if field == held:
                continue
            s[field] = _step(s[field], p[field], field)

        # Occupancy moves rarely and by one person at a time.
        if random.random() < 0.22:
            s["occupancy"] = max(0, min(4, s["occupancy"] + random.choice([-1, 1])))

        s["updated"] = datetime.now()
    return state


def _reading(profile, s):
    temperature = round(s["temperature"], 1)
    humidity = int(round(s["humidity"]))
    voc = int(round(s["voc"]))
    co2 = int(round(s["co2"]))
    aqi = aqi_for(profile, temperature, humidity, voc, co2)
    sensor = profile["sensor"]

    current_for_sensor = {
        "VOC": voc, "CO2": co2, "Humidity": humidity, "Temperature": temperature,
    }.get(sensor["type"], 0)

    reading = {
        "code": profile["code"],
        "name": profile["name"],
        "floor": profile["floor"],
        "wing": profile["wing"],
        "aqi": aqi,
        "temperature": temperature,
        "humidity": humidity,
        "voc": voc,
        "co2": co2,
        "occupancy": s["occupancy"],
        "status": status_for(aqi, temperature, humidity, voc, co2),
        "sensor_type": sensor["type"],
        "threshold_value": sensor["threshold"],
        "sensor_unit": sensor["unit"],
        "sensor_status": sensor["status"],
        "current_for_sensor": current_for_sensor,
        "over_threshold": current_for_sensor > sensor["threshold"],
        "last_updated": s["updated"].strftime("%I:%M %p").lstrip("0"),
        "held_field": _held_field(profile),
    }
    reading["condition_note"] = note_for(reading, profile)
    return reading


def _summarise(readings):
    def stat(field, ndigits=0):
        values = [r[field] for r in readings]
        avg = sum(values) / len(values)
        return {
            "avg": round(avg, ndigits) if ndigits else int(round(avg)),
            "min": min(values),
            "max": max(values),
            "count": len(values),
        }

    summary = {
        "aqi": stat("aqi"),
        "temperature": stat("temperature", 1),
        "humidity": stat("humidity"),
        "voc": stat("voc"),
        "co2": stat("co2"),
        "occupancy": stat("occupancy"),
    }
    summary["occupancy"]["total"] = sum(r["occupancy"] for r in readings)
    summary["aqi"]["trend"] = _trend(summary["aqi"]["avg"])
    summary["per_restroom"] = {r["code"]: r["aqi"] for r in readings}
    summary["warnings"] = sum(1 for r in readings if r["status"] == "warning")
    return summary


def _trend(current_avg):
    """Compare the current average AQI against the recent window."""
    if len(_aqi_history) < 3:
        _aqi_history.append(current_avg)
        return "Steady"
    reference = sum(_aqi_history) / len(_aqi_history)
    _aqi_history.append(current_avg)
    delta = current_avg - reference
    if delta > 1.2:
        return "Improving"
    if delta < -1.2:
        return "Declining"
    return "Steady"


# ---------------------------------------------------------------------------
# Public API — the single seam to swap for real sensors
# ---------------------------------------------------------------------------

def snapshot(advance=True):
    """Current readings for all monitored restrooms.

    Replace the body of this function to read from real hardware/an API;
    keep the returned shape and nothing else needs to change.
    """
    global _state
    with _lock:
        if _state is None:
            _state = _fresh_state()
        elif advance:
            _advance(_state)
        readings = [_reading(p, _state[p["code"]]) for p in RESTROOM_PROFILES]

    return {
        "restrooms": readings,
        "summary": _summarise(readings),
        "updated_at": datetime.now().strftime("%I:%M %p").lstrip("0"),
    }


def baseline_readings():
    """The at-rest values, with no simulation applied — used to seed SQLite."""
    now = datetime.now()
    out = []
    for p in RESTROOM_PROFILES:
        s = {
            "temperature": p["temperature"], "humidity": p["humidity"],
            "voc": float(p["voc"]), "co2": float(p["co2"]),
            "occupancy": p["occupancy"], "updated": now,
        }
        out.append(_reading(p, s))
    return out
