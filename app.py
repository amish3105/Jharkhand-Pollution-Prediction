import os
import csv
import io
import json
import time
import sqlite3
import secrets
import hmac
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import requests
from flask import Flask, jsonify, request, render_template, Response, session, abort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pollution.db")
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

DISTRICTS = {
    "Ranchi": {"lat": 23.3441, "lon": 85.3096, "type": "Capital city"},
    "Jamshedpur": {"lat": 22.8046, "lon": 86.2029, "type": "Industrial city"},
    "Dhanbad": {"lat": 23.7957, "lon": 86.4304, "type": "Coal & mining"},
    "Bokaro": {"lat": 23.6693, "lon": 86.1511, "type": "Industrial city"},
    "Hazaribagh": {"lat": 23.9925, "lon": 85.3637, "type": "Urban / forest"},
    "Deoghar": {"lat": 24.4850, "lon": 86.6948, "type": "Urban centre"},
    "Giridih": {"lat": 24.1900, "lon": 86.3000, "type": "Mining / urban"},
    "Ramgarh": {"lat": 23.6300, "lon": 85.5200, "type": "Mining / industrial"},
    "Chaibasa": {"lat": 22.5600, "lon": 85.8000, "type": "Regional centre"},
    "Dumka": {"lat": 24.2670, "lon": 87.2500, "type": "Regional centre"},
    "Palamu": {"lat": 24.0300, "lon": 84.0700, "type": "Regional centre"},
    "Lohardaga": {"lat": 23.4300, "lon": 84.6800, "type": "Mining / urban"},
}
CACHE = {}
CACHE_TTL = 300

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                district TEXT NOT NULL,
                area TEXT NOT NULL,
                description TEXT NOT NULL,
                contact TEXT,
                status TEXT NOT NULL DEFAULT 'Received',
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


init_db()


def aqi_category(value):
    if value is None:
        return {"label": "Unavailable", "level": "unknown", "advice": "No AQI value is available."}
    value = float(value)
    if value <= 50:
        return {"label": "Good", "level": "good", "advice": "Air quality is satisfactory. Normal outdoor activity is generally suitable."}
    if value <= 100:
        return {"label": "Moderate", "level": "moderate", "advice": "Sensitive people should consider reducing prolonged, heavy outdoor exertion."}
    if value <= 150:
        return {"label": "Unhealthy for sensitive groups", "level": "sensitive", "advice": "Children, older adults and people with heart or lung conditions should limit prolonged outdoor exertion."}
    if value <= 200:
        return {"label": "Unhealthy", "level": "unhealthy", "advice": "Consider limiting prolonged outdoor exertion. Sensitive groups should take extra care."}
    if value <= 300:
        return {"label": "Very unhealthy", "level": "very-unhealthy", "advice": "Reduce outdoor exertion and follow local public-health guidance."}
    return {"label": "Hazardous", "level": "hazardous", "advice": "Avoid outdoor exertion where possible and follow official health advisories."}


def api_call(district, detailed=False):
    if district not in DISTRICTS:
        raise ValueError("Unknown district")
    key = (district, bool(detailed))
    now = time.time()
    cached = CACHE.get(key)
    if cached and now - cached["at"] < CACHE_TTL:
        return cached["data"]

    loc = DISTRICTS[district]
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "current": "us_aqi,pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
        "timezone": "Asia/Kolkata",
        "forecast_days": 3 if detailed else 1,
    }
    if detailed:
        params["hourly"] = "us_aqi,pm2_5,pm10"
        params["past_days"] = 7

    response = requests.get(AIR_URL, params=params, timeout=18)
    response.raise_for_status()
    raw = response.json()
    current = raw.get("current") or {}
    current_time = current.get("time")
    aqi = current.get("us_aqi")
    result = {
        "district": district,
        "district_type": loc["type"],
        "coordinates": {"lat": loc["lat"], "lon": loc["lon"]},
        "current": {
            "time": current_time,
            "us_aqi": aqi,
            "category": aqi_category(aqi),
            "pm2_5": current.get("pm2_5"),
            "pm10": current.get("pm10"),
            "carbon_monoxide": current.get("carbon_monoxide"),
            "nitrogen_dioxide": current.get("nitrogen_dioxide"),
            "sulphur_dioxide": current.get("sulphur_dioxide"),
            "ozone": current.get("ozone"),
        },
        "source": "Open-Meteo Air Quality API (CAMS model-based estimates)",
        "source_url": "https://open-meteo.com/en/docs/air-quality-api",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "timezone": raw.get("timezone", "Asia/Kolkata"),
        "resolution": "Model grid estimate; not a certified ground-monitor reading.",
    }
    if detailed:
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        result["hourly"] = {
            "time": times,
            "us_aqi": hourly.get("us_aqi") or [],
            "pm2_5": hourly.get("pm2_5") or [],
            "pm10": hourly.get("pm10") or [],
        }
    CACHE[key] = {"at": now, "data": result}
    return result


def admin_password_ok(password):
    expected = os.environ.get("ADMIN_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(str(password or ""), expected)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@app.get("/")
def index():
    return render_template("index.html", districts=list(DISTRICTS.keys()))


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "Jharkhand Pollution Intelligence",
        "live_api": "Open-Meteo Air Quality API",
        "admin_configured": bool(os.environ.get("ADMIN_PASSWORD")),
        "data_note": "Air quality values are model-based estimates, not official CPCB station measurements."
    })


@app.get("/api/districts")
def districts():
    return jsonify([{"name": name, **details} for name, details in DISTRICTS.items()])


@app.get("/api/air")
def air():
    district = request.args.get("district", "Ranchi")
    try:
        return jsonify(api_call(district, detailed=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.RequestException:
        return jsonify({"error": "Live air-quality service is temporarily unavailable. Please retry later.", "district": district}), 502
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "The air-quality service returned an unexpected response."}), 502


@app.get("/api/overview")
def overview():
    def one(name):
        try:
            return api_call(name, detailed=False)
        except Exception:
            return {"district": name, "error": "Data unavailable", "current": {"us_aqi": None, "category": aqi_category(None)}}
    with ThreadPoolExecutor(max_workers=6) as pool:
        items = list(pool.map(one, DISTRICTS.keys()))
    available = [x for x in items if x.get("current", {}).get("us_aqi") is not None]
    return jsonify({
        "districts": items,
        "available_count": len(available),
        "total_count": len(items),
        "average_aqi": round(sum(float(x["current"]["us_aqi"]) for x in available) / len(available), 1) if available else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "note": "District values are model-based estimates at approximate district coordinates, not official monitoring-station measurements."
    })


@app.get("/api/export")
def export_csv():
    district = request.args.get("district", "Ranchi")
    try:
        data = api_call(district, detailed=True)
    except Exception:
        return jsonify({"error": "Unable to retrieve live data for export. Please retry."}), 502
    hourly = data.get("hourly", {})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["district", "datetime_Asia_Kolkata", "us_aqi", "pm2_5_ug_m3", "pm10_ug_m3", "data_source"])
    for i, stamp in enumerate(hourly.get("time", [])):
        def at(key):
            arr = hourly.get(key, [])
            return arr[i] if i < len(arr) else ""
        writer.writerow([district, stamp, at("us_aqi"), at("pm2_5"), at("pm10"), "Open-Meteo CAMS model estimate"])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{district.lower()}_air_quality.csv"'}
    )


@app.post("/api/complaints")
def create_complaint():
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "")).strip()
    district = str(payload.get("district", "")).strip()
    area = str(payload.get("area", "")).strip()
    description = str(payload.get("description", "")).strip()
    contact = str(payload.get("contact", "")).strip()[:120]
    allowed_categories = {"Air pollution", "Water pollution", "Industrial emissions", "Waste burning", "Dust / construction", "Other"}
    if category not in allowed_categories or district not in DISTRICTS or not area or len(area) > 160 or len(description) < 15 or len(description) > 2000:
        return jsonify({"error": "Please complete all required fields. Description must be 15–2000 characters."}), 400
    reference = "JPI-" + secrets.token_hex(4).upper()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO complaints (reference, category, district, area, description, contact, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'Received', ?)",
            (reference, category, district, area, description, contact, created_at)
        )
        conn.commit()
    return jsonify({"reference": reference, "status": "Received", "created_at": created_at}), 201


@app.get("/api/complaints/<reference>")
def complaint_status(reference):
    with get_db() as conn:
        row = conn.execute(
            "SELECT reference, category, district, area, status, created_at FROM complaints WHERE reference = ?",
            (reference.upper(),)
        ).fetchone()
    if not row:
        return jsonify({"error": "No complaint found for that reference."}), 404
    return jsonify(dict(row))


@app.post("/api/admin/login")
def admin_login():
    payload = request.get_json(silent=True) or {}
    if not os.environ.get("ADMIN_PASSWORD"):
        return jsonify({"error": "Admin access is disabled. Set the ADMIN_PASSWORD environment variable first."}), 503
    if not admin_password_ok(payload.get("password")):
        return jsonify({"error": "Incorrect admin password."}), 401
    session["is_admin"] = True
    return jsonify({"ok": True})


@app.post("/api/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


def require_admin(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin login required."}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.get("/api/admin/complaints")
@require_admin
def admin_complaints():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT reference, category, district, area, description, contact, status, created_at FROM complaints ORDER BY id DESC LIMIT 300"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.patch("/api/admin/complaints/<reference>")
@require_admin
def update_complaint(reference):
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", ""))
    if status not in {"Received", "Under review", "Action taken", "Closed"}:
        return jsonify({"error": "Invalid status."}), 400
    with get_db() as conn:
        cur = conn.execute("UPDATE complaints SET status = ? WHERE reference = ?", (status, reference.upper()))
        conn.commit()
    if not cur.rowcount:
        return jsonify({"error": "Complaint not found."}), 404
    return jsonify({"ok": True, "reference": reference.upper(), "status": status})


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint not found."}), 404
    return "Page not found", 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
