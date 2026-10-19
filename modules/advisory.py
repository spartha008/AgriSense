"""Turns a weather forecast into practical, prioritised farm advisories."""

from . import weather as wx

LEVEL_RANK = {"good": 0, "info": 1, "watch": 2, "warning": 3, "danger": 4}

CROP_SENSITIVITY = {
    "rice": {"names": ["rice", "paddy"], "waterlog": "high", "note": "Rice tolerates standing water but not flash floods during transplanting."},
    "wheat": {"names": ["wheat"], "waterlog": "high", "note": "Wheat is very sensitive to waterlogging in the first 30 days."},
    "maize": {"names": ["maize", "corn"], "waterlog": "high", "note": "Maize dies quickly in stagnant water - drain within 24 hours."},
    "cotton": {"names": ["cotton"], "waterlog": "medium", "note": "Cotton dislikes both waterlogging and long dry spells at flowering."},
    "tomato": {"names": ["tomato"], "waterlog": "high", "note": "Tomato foliage should stay dry - overhead irrigation invites blight."},
    "potato": {"names": ["potato"], "waterlog": "high", "note": "Potato tubers rot in waterlogged soil and greening follows exposure to light."},
    "onion": {"names": ["onion"], "waterlog": "medium", "note": "Stop irrigation 15-20 days before harvest for good bulb curing."},
    "groundnut": {"names": ["groundnut", "peanut"], "waterlog": "high", "note": "Groundnut pegging and pod filling must never be waterlogged."},
    "banana": {"names": ["banana"], "waterlog": "high", "note": "Banana needs steady moisture; strong wind needs propping."},
}


def _mk(level, title, message, action, icon="\u26a0\ufe0f", tag="general"):
    return {"level": level, "title": title, "message": message, "action": action,
            "icon": icon, "tag": tag}


def _crop_key(crop_name):
    if not crop_name:
        return None
    name = str(crop_name).lower()
    for key, meta in CROP_SENSITIVITY.items():
        if any(n in name for n in meta["names"]):
            return key
    return None


# --------------------------------------------------------------------------- disease risk

def fungal_risk(temp_mean, humidity, rain_prob, rain_mm):
    """0-100 index for fungal/bacterial disease pressure on a given day."""
    if temp_mean is None:
        return None
    humidity = 60 if humidity is None else humidity
    rain_prob = 0 if rain_prob is None else rain_prob
    rain_mm = 0 if rain_mm is None else rain_mm

    temp_factor = max(0.0, 1.0 - abs(float(temp_mean) - 24.0) / 14.0)
    humidity_factor = max(0.0, min(1.0, (float(humidity) - 55.0) / 40.0))
    wet_factor = max(0.0, min(1.0, (float(rain_prob) / 100.0) * 0.6 + min(float(rain_mm) / 20.0, 1.0) * 0.4))

    index = 100.0 * (0.35 * temp_factor + 0.35 * humidity_factor + 0.30 * wet_factor)
    return int(round(min(100.0, index)))


def _risk_level(index):
    if index is None:
        return "info", "No data"
    if index >= 70:
        return "danger", "Very high disease risk"
    if index >= 55:
        return "warning", "High disease risk"
    if index >= 40:
        return "watch", "Moderate disease risk"
    return "good", "Low disease risk"


# --------------------------------------------------------------------------- spray windows

def spray_windows(hourly, limit=4):
    windows = []
    current = None

    for hour in hourly:
        temp = hour.get("temperature")
        wind = hour.get("wind_speed")
        prob = hour.get("precipitation_probability") or 0
        rain = hour.get("precipitation") or 0
        humidity = hour.get("humidity") or 0
        hh = int((hour.get("hour") or "00:00").split(":")[0])

        suitable = (
            temp is not None and 10 <= temp <= 32
            and wind is not None and wind < 12
            and prob < 30 and rain < 0.2
            and humidity < 90
            and 6 <= hh <= 18
        )
        key = (hour.get("day"), hour.get("date") if "date" in hour else hour.get("time", "")[:10])

        if suitable:
            if current is None:
                current = {
                    "day": hour.get("day"),
                    "date": hour.get("time", "")[:10],
                    "start": hour.get("hour"),
                    "end": hour.get("hour"),
                    "hours": 1,
                    "avg_wind": wind,
                    "avg_temp": temp,
                    "avg_prob": prob,
                    "key": key,
                }
            elif current["key"] == key:
                current["end"] = hour.get("hour")
                current["hours"] += 1
                current["avg_wind"] = (current["avg_wind"] + wind) / 2
                current["avg_temp"] = (current["avg_temp"] + temp) / 2
                current["avg_prob"] = (current["avg_prob"] + prob) / 2
            else:
                if current["hours"] >= 2:
                    windows.append(current)
                current = None
        else:
            if current is not None and current["hours"] >= 2:
                windows.append(current)
            current = None

    if current is not None and current["hours"] >= 2:
        windows.append(current)

    windows.sort(key=lambda w: (-w["hours"], w["avg_prob"]))
    out = []
    for w in windows[:limit]:
        out.append({
            "day": w["day"],
            "date": w["date"],
            "window": f"{w['start']} - {w['end']}",
            "hours": w["hours"],
            "wind_kmh": round(w["avg_wind"], 1),
            "temp_c": round(w["avg_temp"], 1),
            "rain_chance": round(w["avg_prob"]),
            "reason": (f"Wind {round(w['avg_wind'], 1)} km/h, "
                       f"rain chance {round(w['avg_prob'])}%, "
                       f"{round(w['avg_temp'], 1)} \u00b0C"),
        })
    return out


# --------------------------------------------------------------------------- main

def build_advisory(forecast, crop_name=None, crop_stage=None):
    current = forecast.get("current") or {}
    daily = forecast.get("daily") or []
    hourly = forecast.get("hourly") or []
    alerts = []

    ckey = _crop_key(crop_name)
    crop_meta = CROP_SENSITIVITY.get(ckey) if ckey else None

    # ---------------- current-conditions alerts ----------------
    temp = current.get("temperature")
    humidity = current.get("humidity")
    wind = current.get("wind_speed")
    gusts = current.get("wind_gusts")
    rain_now = current.get("precipitation") or 0
    code = (current.get("weather") or {}).get("code")

    if rain_now and rain_now >= 7.5:
        alerts.append(_mk("danger", "Heavy rain right now",
                          f"About {round(rain_now, 1)} mm of rain has just fallen.",
                          "Open drainage channels and check low-lying patches. Postpone spraying and "
                          "fertiliser application until the soil drains.", "\U0001f327\ufe0f", "rain"))

    today = next((d for d in daily if d.get("is_today")), daily[0] if daily else None)
    if today:
        tmin = today.get("temp_min")
        tmax = today.get("temp_max")
        if tmin is not None and tmin <= 4:
            alerts.append(_mk("danger", "Frost risk tonight",
                              f"Minimum temperature is forecast near {round(tmin, 1)} \u00b0C.",
                              "Give a light irrigation in the evening, use straw or dry grass mulch, "
                              "and cover nurseries. Smoke in the upwind corner of the field only where "
                              "permitted.", "\u2744\ufe0f", "cold"))
        elif tmin is not None and tmin <= 8:
            alerts.append(_mk("watch", "Cold night ahead",
                              f"Minimum near {round(tmin, 1)} \u00b0C may slow growth.",
                              "Avoid late-evening irrigation and keep young plants covered overnight.", "\U0001f321\ufe0f", "cold"))
        if tmax is not None and tmax >= 40:
            alerts.append(_mk("danger", "Heat wave conditions",
                              f"Maximum temperature is forecast near {round(tmax, 1)} \u00b0C.",
                              "Irrigate early morning or after sunset, apply mulch, and avoid any field "
                              "operation between 11 am and 4 pm.", "\U0001f525", "heat"))
        elif tmax is not None and tmax >= 37:
            alerts.append(_mk("warning", "Hot day ahead",
                              f"Maximum temperature near {round(tmax, 1)} \u00b0C.",
                              "Irrigate in the early morning and delay spraying to the cooler evening.", "\u2600\ufe0f", "heat"))

    if gusts is not None and gusts >= 45:
        alerts.append(_mk("warning", "Strong gusty winds",
                          f"Gusts up to {round(gusts)} km/h are likely.",
                          "Do not spray. Stake tall crops and young plants, and secure shade nets and "
                          "polyhouse structures.", "\U0001f32c\ufe0f", "wind"))
    elif wind is not None and wind >= 25:
        alerts.append(_mk("watch", "Windy conditions",
                          f"Wind around {round(wind)} km/h.",
                          "Postpone spraying and dusting operations and protect any light structures.", "\U0001f343", "wind"))

    if code in (45, 48):
        alerts.append(_mk("watch", "Fog and low visibility",
                          "Foggy conditions reduce photosynthesis and keep leaves wet.",
                          "Do not spray while leaves are wet. Watch for late blight and downy mildew in "
                          "foggy spells.", "\U0001f32b\ufe0f", "disease"))

    if code in (95, 96, 99):
        alerts.append(_mk("danger", "Thunderstorm activity",
                          "Thunderstorms with possible hail are forecast.",
                          "Secure your equipment, keep livestock sheltered, and inspect the field for "
                          "lodging and waterlogging afterwards.", "\u26c8\ufe0f", "storm"))

    risk_now = fungal_risk(
        (today or {}).get("temp_max") and ((today["temp_max"] + (today["temp_min"] or today["temp_max"])) / 2) or temp,
        humidity,
        (today or {}).get("precipitation_probability_max"),
        (today or {}).get("precipitation_sum"),
    )
    if risk_now is not None and risk_now >= 60:
        alerts.append(_mk("warning", "High fungal disease pressure",
                          f"Disease-favourable weather (index {risk_now}/100): warm, humid with wet leaves.",
                          "Consider a preventive bio-fungicide or copper spray on susceptible crops such as "
                          "tomato, potato, chilli, grape or onion. Keep the canopy open.", "\U0001f344", "disease"))

    if humidity is not None and humidity < 30 and temp is not None and temp > 32:
        alerts.append(_mk("watch", "Dry heat stress",
                          "Very low humidity with high temperature increases water loss from plants.",
                          "Mulch the root zone and irrigate in the early morning to reduce evaporation.", "\U0001f4a7", "heat"))

    # ---------------- forecast alerts ----------------
    dry_streak = 0
    best_dry = 0
    heavy_days, hot_days, cold_days, windy_days = [], [], [], []
    for d in daily[:7]:
        p = d.get("precipitation_sum") or 0
        if p < 2:
            dry_streak += 1
            best_dry = max(best_dry, dry_streak)
        else:
            dry_streak = 0
        if p >= 50:
            heavy_days.append(d)
        if (d.get("temp_max") or 0) >= 38:
            hot_days.append(d)
        if (d.get("temp_min") or 99) <= 6:
            cold_days.append(d)
        if (d.get("wind_max") or 0) >= 40:
            windy_days.append(d)

    if heavy_days:
        d = heavy_days[0]
        total = round(sum(x.get("precipitation_sum") or 0 for x in heavy_days), 1)
        alerts.append(_mk("danger", f"Heavy rain expected ({d['weekday']} {d['day']} {d['month']})",
                          f"About {total} mm of rain is forecast over {len(heavy_days)} day(s).",
                          "Drain excess water, postpone fertiliser and pesticide application, and harvest "
                          "any mature crop before the rain if possible.", "\U0001f327\ufe0f", "rain"))
    elif any((d.get("precipitation_sum") or 0) >= 20 for d in daily[:7]):
        d = next(x for x in daily[:7] if (x.get("precipitation_sum") or 0) >= 20)
        alerts.append(_mk("watch", f"Good rain likely ({d['weekday']} {d['day']} {d['month']})",
                          f"About {round(d.get('precipitation_sum') or 0, 1)} mm is forecast.",
                          "Skip the next irrigation and avoid spraying for 24 hours around the rain.", "\U0001f326\ufe0f", "rain"))

    if best_dry >= 5:
        alerts.append(_mk("watch", "Dry spell ahead",
                          f"{best_dry} consecutive days with less than 2 mm of rain forecast.",
                          "Plan your irrigation schedule now, mulching the root zone to conserve moisture. "
                          "Protect the crop's critical stage first.", "\U0001f4a7", "drought"))

    if len(hot_days) >= 3:
        alerts.append(_mk("danger", "Heat wave spell",
                          f"{len(hot_days)} days forecast above 38 \u00b0C.",
                          "Irrigate at dawn, mulch heavily, provide shade for nurseries, and avoid all "
                          "midday field work.", "\U0001f525", "heat"))

    if len(cold_days) >= 2:
        alerts.append(_mk("warning", "Cold wave spell",
                          f"{len(cold_days)} nights forecast below 6 \u00b0C.",
                          "Protect frost-sensitive crops, vegetables and nurseries and light-irrigate on "
                          "the coldest nights.", "\u2744\ufe0f", "cold"))

    if windy_days:
        alerts.append(_mk("watch", "Windy days in the forecast",
                          f"Wind up to {round(max(x.get('wind_max') or 0 for x in windy_days))} km/h.",
                          "Plan sprays around the calm windows shown below and stake tall crops.", "\U0001f32c\ufe0f", "wind"))

    # ---------------- crop-specific ----------------
    if crop_meta:
        sensitive = crop_meta["waterlog"] == "high"
        if heavy_days and sensitive:
            alerts.append(_mk("warning", f"{crop_name}: waterlogging risk",
                              crop_meta["note"],
                              "Check drainage today and open channels before the rain arrives.", "\U0001f33e", "crop"))
        if best_dry >= 5:
            alerts.append(_mk("info", f"{crop_name}: irrigation planning",
                              f"A {best_dry}-day dry spell is likely.",
                              crop_meta["note"] + " Irrigate before the soil moisture runs down.", "\U0001f4a7", "crop"))
        if crop_stage:
            alerts.append(_mk("info", f"{crop_name} at {crop_stage} stage",
                              "Stage-specific water demand has been applied in the irrigation planner.",
                              "Open the irrigation planner to get a depth, interval and volume for this stage.",
                              "\U0001f331", "crop"))

    # ---------------- disease-risk series ----------------
    risk_series = []
    for d in daily[:7]:
        mid = None
        if d.get("temp_max") is not None and d.get("temp_min") is not None:
            mid = (d["temp_max"] + d["temp_min"]) / 2
        idx = fungal_risk(mid, d.get("humidity_mean"),
                          d.get("precipitation_probability_max"), d.get("precipitation_sum"))
        level, label = _risk_level(idx)
        risk_series.append({
            "date": d["date"], "weekday": d["weekday"], "day": d["day"], "month": d["month"],
            "index": idx, "level": level, "label": label,
        })

    # ---------------- per-day summary ----------------
    day_advice = []
    for d in daily[:7]:
        notes = []
        level = "good"
        icon = d["weather"]["icon"]
        p = d.get("precipitation_sum") or 0
        tmax = d.get("temp_max")
        tmin = d.get("temp_min")
        wmax = d.get("wind_max") or 0

        if p >= 50:
            notes.append("Heavy rain - drain fields, no spraying or fertiliser.")
            level = "danger"
        elif p >= 20:
            notes.append("Meaningful rain - skip irrigation, avoid spraying.")
            level = "watch"
        elif p >= 5:
            notes.append("Light rain - useful for germination, still avoid spraying.")
            level = _level_max(level, "info")
        if tmax is not None and tmax >= 38:
            notes.append("Heat stress risk - irrigate early morning and mulch.")
            level = _level_max(level, "warning")
        if tmin is not None and tmin <= 6:
            notes.append("Cold/frost risk - protect sensitive crops at night.")
            level = _level_max(level, "warning")
        if wmax >= 40:
            notes.append("Strong winds - stake tall crops, postpone spraying.")
            level = _level_max(level, "watch")
        if d.get("et0") is not None and d["et0"] >= 6:
            notes.append(f"High water demand (ET\u2080 {round(d['et0'], 1)} mm).")
            level = _level_max(level, "info")
        if not notes:
            notes.append("Good working conditions - suitable for field operations.")

        day_advice.append({
            "date": d["date"], "weekday": d["weekday"], "day": d["day"], "month": d["month"],
            "is_today": d.get("is_today", False),
            "icon": icon, "label": d["weather"]["label"],
            "temp_max": tmax, "temp_min": tmin,
            "rain": round(p, 1),
            "rain_chance": d.get("precipitation_probability_max"),
            "wind": round(wmax, 1),
            "et0": round(d["et0"], 1) if d.get("et0") is not None else None,
            "level": level,
            "notes": notes,
        })

    windows = spray_windows(hourly)

    # ---------------- overall score & headline ----------------
    score = 100
    for a in alerts:
        score -= {"danger": 22, "warning": 12, "watch": 6, "info": 0, "good": 0}[a["level"]]
    score = max(5, min(100, score))

    if score >= 80:
        headline = "Good field-working conditions this week."
        summary_level = "good"
    elif score >= 60:
        headline = "Mostly workable, but plan around the alerts below."
        summary_level = "watch"
    elif score >= 40:
        headline = "Challenging weather - prioritise protection of the standing crop."
        summary_level = "warning"
    else:
        headline = "Difficult conditions ahead - focus on damage control."
        summary_level = "danger"

    alerts.sort(key=lambda a: -LEVEL_RANK.get(a["level"], 0))

    water = forecast.get("summary") or {}
    balance = water.get("water_balance_7d_mm")
    if balance is not None:
        if balance < -40:
            alerts.append(_mk("watch", "Water deficit building up",
                              f"Forecast rain is about {abs(balance)} mm less than crop water demand over "
                              "the next 7 days.",
                              "This is a net irrigation deficit week - plan your schedule accordingly.",
                              "\U0001f4a7", "water"))
        elif balance > 60:
            alerts.append(_mk("info", "Surplus rainfall week",
                              f"About {balance} mm more rain than crop demand is expected.",
                              "Skip irrigation and check drainage. Watch for nutrient leaching on sandy soils.",
                              "\U0001f326\ufe0f", "water"))

    return {
        "score": score,
        "headline": headline,
        "level": summary_level,
        "alerts": alerts,
        "daily": day_advice,
        "spray_windows": windows,
        "disease_risk": risk_series,
        "water_balance": water,
        "crop": crop_name,
        "crop_stage": crop_stage,
    }


def _level_max(a, b):
    return a if LEVEL_RANK.get(a, 0) >= LEVEL_RANK.get(b, 0) else b
