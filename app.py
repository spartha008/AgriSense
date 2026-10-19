"""AgriSense - Intelligent Farming Assistant.

Flask application exposing a JSON API plus the single-page front end.

Run:
    python app.py
"""

import datetime as _dt

from flask import Flask, jsonify, render_template, request

from modules import advisory, data_store, disease, irrigation, seasonal, weather as wx

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB uploads
app.config["JSON_SORT_KEYS"] = False

MAX_IMAGE_BYTES = 12 * 1024 * 1024

# a few well known farming locations for quick selection
DEMO_LOCATIONS = [
    {"label": "Nagpur, Maharashtra, India", "latitude": 21.1458, "longitude": 79.0882},
    {"label": "Nashik, Maharashtra, India", "latitude": 19.9975, "longitude": 73.7898},
    {"label": "Ludhiana, Punjab, India", "latitude": 30.9010, "longitude": 75.8573},
    {"label": "Guntur, Andhra Pradesh, India", "latitude": 16.3067, "longitude": 80.4365},
    {"label": "Coimbatore, Tamil Nadu, India", "latitude": 11.0168, "longitude": 76.9558},
    {"label": "Patna, Bihar, India", "latitude": 25.5941, "longitude": 85.1376},
    {"label": "Jaipur, Rajasthan, India", "latitude": 26.9124, "longitude": 75.7873},
    {"label": "Nairobi, Kenya", "latitude": -1.2921, "longitude": 36.8219},
    {"label": "Iowa, United States", "latitude": 41.8780, "longitude": -93.0977},
    {"label": "Punjab, Pakistan", "latitude": 31.1704, "longitude": 72.7097},
]


# --------------------------------------------------------------------------- helpers

def _to_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def ok(payload, **extra):
    body = {"ok": True}
    body.update(payload)
    body.update(extra)
    return jsonify(body)


def fail(message, status=400, **extra):
    body = {"ok": False, "error": message}
    body.update(extra)
    return jsonify(body), status


# --------------------------------------------------------------------------- pages

@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------- meta

@app.route("/api/health")
def health():
    return ok({"status": "healthy", "time": _dt.datetime.now().isoformat(timespec="seconds")})


@app.route("/api/overview")
def overview():
    month = seasonal.current()
    tips = seasonal.tips(limit=4)
    crops = [data_store.crop_summary(c) for c in data_store.crops()]
    return ok({
        "stats": data_store.stats(),
        "seasonal": month,
        "tips": tips,
        "crops": crops,
        "locations": DEMO_LOCATIONS,
        "disease_types": data_store.pathogen_types(),
    })


# --------------------------------------------------------------------------- crops

@app.route("/api/crops")
def list_crops():
    query = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    items = data_store.crops()
    if category:
        items = [c for c in items if c.get("category", "").lower() == category]
    if query:
        def hit(c):
            blob = " ".join([
                c["name"], c.get("local_names", ""), c.get("scientific", ""),
                c.get("category", ""), c.get("season", ""), c.get("soil", ""),
            ]).lower()
            return query in blob
        items = [c for c in items if hit(c)]
    categories = sorted({c.get("category", "") for c in data_store.crops()})
    return ok({"crops": [data_store.crop_summary(c) for c in items], "categories": categories})


@app.route("/api/crops/<crop_id>")
def crop_detail(crop_id):
    item = data_store.crop(crop_id)
    if not item:
        return fail(f"Unknown crop '{crop_id}'.", 404)
    diseases = [data_store.disease_summary(d) for d in data_store.diseases_for_crop(crop_id)]
    payload = dict(item)
    payload["disease_details"] = diseases
    return ok({"crop": payload})


# --------------------------------------------------------------------------- diseases

@app.route("/api/diseases")
def list_diseases():
    items = data_store.search_diseases(
        query=request.args.get("q", ""),
        crop_id=request.args.get("crop") or None,
        pathogen_type=request.args.get("type") or None,
    )
    return ok({
        "diseases": [data_store.disease_summary(d) for d in items],
        "count": len(items),
        "types": data_store.pathogen_types(),
    })


@app.route("/api/diseases/<disease_id>")
def disease_detail(disease_id):
    item = data_store.disease(disease_id)
    if not item:
        return fail(f"Unknown disease '{disease_id}'.", 404)
    return ok({"disease": item})


@app.route("/api/disease/meta")
def disease_meta():
    return ok({
        "crops": [data_store.crop_summary(c) for c in data_store.crops()],
        "types": data_store.pathogen_types(),
        "symptoms": disease.symptom_options(),
        "tags": disease.tag_reference(),
    })


@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    crop_id = request.form.get("crop_id") or None
    symptoms = request.form.getlist("symptoms")
    if len(symptoms) == 1 and "," in symptoms[0]:
        symptoms = [s.strip() for s in symptoms[0].split(",") if s.strip()]

    image_bytes = None
    filename = ""
    upload = request.files.get("image")
    if upload and upload.filename:
        filename = upload.filename
        data = upload.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return fail("The image is larger than 12 MB. Please upload a smaller photo.", 413)
        if data:
            image_bytes = data

    if not image_bytes and not symptoms:
        return fail("Upload a leaf image or select at least one symptom.", 400)

    result = disease.analyze(image_bytes, crop_id=crop_id, symptoms=symptoms, filename=filename)
    if not result.get("ok") and result.get("quality_flags") and not image_bytes:
        return fail("Could not analyse the request.", 400, detail=result)
    return jsonify(result)


# --------------------------------------------------------------------------- weather

@app.route("/api/locations")
def locations():
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return ok({"locations": DEMO_LOCATIONS})
    try:
        results = wx.geocode(query, count=6)
    except wx.WeatherError as exc:
        return fail(str(exc), 502, fallback=DEMO_LOCATIONS)
    return ok({"locations": results})


@app.route("/api/weather")
def get_weather():
    location = (request.args.get("location") or "").strip()
    latitude = _to_float(request.args.get("lat"))
    longitude = _to_float(request.args.get("lon"))
    label = (request.args.get("label") or location).strip()
    crop_id = request.args.get("crop") or None
    stage = request.args.get("stage") or None

    if latitude is None or longitude is None:
        if not location:
            return fail("Provide a location name or latitude/longitude.")
        try:
            matches = wx.geocode(location, count=1)
        except wx.WeatherError as exc:
            return fail(str(exc), 502)
        if not matches:
            return fail(f"No location found for '{location}'.", 404)
        best = matches[0]
        latitude, longitude, label = best["latitude"], best["longitude"], best["label"]

    forecast = wx.get_weather(latitude=latitude, longitude=longitude, label=label)

    crop = data_store.crop(crop_id)
    crop_name = crop["name"] if crop else None
    result = advisory.build_advisory(forecast, crop_name=crop_name, crop_stage=stage)

    # irrigation defaults derived from the same forecast
    et0_today = None
    today = next((d for d in forecast["daily"] if d["is_today"]), None)
    if today and today.get("et0") is not None:
        et0_today = today["et0"]
    elif forecast["daily"]:
        et0_today = forecast["daily"][0].get("et0")

    result["irrigation_defaults"] = {
        "et0": et0_today,
        "rain_forecast_mm": forecast["summary"].get("rain_next_7d_mm"),
        "rain_recent_mm": forecast["summary"].get("rain_past_3d_mm"),
        "horizon_days": 7,
    }
    result["forecast"] = forecast
    return jsonify(result)


# --------------------------------------------------------------------------- irrigation

@app.route("/api/irrigation/options")
def irrigation_options():
    return ok({
        "options": irrigation.options(),
        "crops": [data_store.crop_summary(c) for c in data_store.crops()],
    })


@app.route("/api/irrigation", methods=["POST"])
def irrigation_plan():
    payload = request.get_json(silent=True) or {}
    result = irrigation.plan(payload)
    return ok({"plan": result})


# --------------------------------------------------------------------------- seasonal & tips

@app.route("/api/seasonal")
def seasonal_info():
    month = request.args.get("month")
    month = int(month) if month and month.isdigit() else None
    return ok({
        "current": seasonal.current(month),
        "calendar": seasonal.calendar(),
    })


@app.route("/api/tips")
def tips():
    category = request.args.get("category")
    query = request.args.get("q")
    limit = request.args.get("limit")
    items = seasonal.tips(category=category, query=query,
                          limit=int(limit) if limit and limit.isdigit() else None)
    return ok({"tips": items, "categories": data_store.tip_categories()})


# --------------------------------------------------------------------------- errors

@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return fail("Endpoint not found.", 404)
    return render_template("index.html"), 404


@app.errorhandler(413)
def too_large(_):
    return fail("The uploaded file is too large (limit 12 MB).", 413)


@app.errorhandler(500)
def server_error(exc):
    app.logger.exception("Unhandled error: %s", exc)
    return fail("Something went wrong on the server. Please try again.", 500)


if __name__ == "__main__":
    print("AgriSense running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
