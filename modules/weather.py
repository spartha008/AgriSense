"""Live weather from Open-Meteo (no API key required) with a labelled
climatological estimate as an offline fallback."""

import datetime as _dt
import json
import math
import threading
import time
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "AgriSense/1.0 (farming advisory demo)"

_CACHE = {}
_CACHE_TTL = 600  # seconds
_LOCK = threading.Lock()


class WeatherError(Exception):
    pass


# --------------------------------------------------------------------------- WMO codes

_WMO = {
    0: ("Clear sky", "\u2600\ufe0f", "good"),
    1: ("Mainly clear", "\U0001f324\ufe0f", "good"),
    2: ("Partly cloudy", "\u26c5", "good"),
    3: ("Overcast", "\u2601\ufe0f", "fair"),
    45: ("Fog", "\U0001f32b\ufe0f", "watch"),
    48: ("Depositing rime fog", "\U0001f32b\ufe0f", "watch"),
    51: ("Light drizzle", "\U0001f326\ufe0f", "fair"),
    53: ("Moderate drizzle", "\U0001f326\ufe0f", "fair"),
    55: ("Dense drizzle", "\U0001f327\ufe0f", "watch"),
    56: ("Light freezing drizzle", "\U0001f327\ufe0f", "watch"),
    57: ("Dense freezing drizzle", "\U0001f327\ufe0f", "watch"),
    61: ("Slight rain", "\U0001f326\ufe0f", "fair"),
    63: ("Moderate rain", "\U0001f327\ufe0f", "watch"),
    65: ("Heavy rain", "\U0001f327\ufe0f", "danger"),
    66: ("Light freezing rain", "\U0001f327\ufe0f", "watch"),
    67: ("Heavy freezing rain", "\U0001f327\ufe0f", "danger"),
    71: ("Slight snow", "\U0001f328\ufe0f", "watch"),
    73: ("Moderate snow", "\U0001f328\ufe0f", "watch"),
    75: ("Heavy snow", "\u2744\ufe0f", "danger"),
    77: ("Snow grains", "\U0001f328\ufe0f", "watch"),
    80: ("Slight rain showers", "\U0001f326\ufe0f", "fair"),
    81: ("Moderate rain showers", "\U0001f327\ufe0f", "watch"),
    82: ("Violent rain showers", "\u26c8\ufe0f", "danger"),
    85: ("Slight snow showers", "\U0001f328\ufe0f", "watch"),
    86: ("Heavy snow showers", "\u2744\ufe0f", "danger"),
    95: ("Thunderstorm", "\u26c8\ufe0f", "danger"),
    96: ("Thunderstorm with hail", "\u26c8\ufe0f", "danger"),
    99: ("Severe thunderstorm with hail", "\u26c8\ufe0f", "danger"),
}


def code_info(code):
    label, icon, level = _WMO.get(int(code) if code is not None else -1,
                                  ("Unknown", "\U0001f321\ufe0f", "fair"))
    return {"code": code, "label": label, "icon": icon, "level": level}


# --------------------------------------------------------------------------- http

def _fetch(url, params, timeout=12):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cache_get(key):
    with _LOCK:
        entry = _CACHE.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _cache_put(key, value):
    with _LOCK:
        _CACHE[key] = (time.time(), value)
    return value


# --------------------------------------------------------------------------- geocoding

def geocode(name, count=6):
    """Resolve a place name to candidate coordinates."""
    name = (name or "").strip()
    if len(name) < 2:
        raise WeatherError("Please enter at least two characters of a place name.")

    key = ("geo", name.lower(), count)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        data = _fetch(GEOCODE_URL, {
            "name": name,
            "count": count,
            "language": "en",
            "format": "json",
        })
    except Exception as exc:  # network failure
        raise WeatherError(
            "Could not reach the location service. Check your internet connection "
            "and try again, or pick a location from the list."
        ) from exc

    results = []
    for row in data.get("results", []) or []:
        results.append({
            "name": row.get("name"),
            "admin1": row.get("admin1") or "",
            "admin2": row.get("admin2") or "",
            "country": row.get("country") or "",
            "country_code": row.get("country_code") or "",
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "timezone": row.get("timezone") or "",
            "elevation": row.get("elevation"),
            "label": ", ".join([p for p in [row.get("name"), row.get("admin1"), row.get("country")] if p]),
        })
    return _cache_put(key, results)


# --------------------------------------------------------------------------- forecast

_HOURLY = [
    "temperature_2m", "relative_humidity_2m", "precipitation", "precipitation_probability",
    "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "et0_fao_evapotranspiration",
    "soil_moisture_3_to_9cm", "is_day",
]
_CURRENT = [
    "temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
    "precipitation", "weather_code", "cloud_cover", "pressure_msl",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "soil_temperature_6cm",
]
_DAILY = [
    "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "precipitation_probability_max", "wind_speed_10m_max", "wind_gusts_10m_max",
    "relative_humidity_2m_mean", "et0_fao_evapotranspiration", "sunrise", "sunset",
    "shortwave_radiation_sum",
]


def _value(block, key, index):
    seq = block.get(key)
    if not seq or index >= len(seq):
        return None
    return seq[index]


def fetch_forecast(latitude, longitude, location_label="", timezone="auto", days=7, past_days=2):
    key = ("fc", round(float(latitude), 3), round(float(longitude), 3), days, past_days)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        data = _fetch(FORECAST_URL, {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(_CURRENT),
            "hourly": ",".join(_HOURLY),
            "daily": ",".join(_DAILY),
            "timezone": timezone,
            "forecast_days": days,
            "past_days": past_days,
            "wind_speed_unit": "kmh",
        })
    except Exception as exc:
        raise WeatherError(
            "Could not reach the weather service. Check your internet connection and try again."
        ) from exc

    normalized = _normalize(data, location_label, latitude, longitude)
    return _cache_put(key, normalized)


def _normalize(data, location_label, latitude, longitude):
    current_in = data.get("current") or {}
    hourly_in = data.get("hourly") or {}
    daily_in = data.get("daily") or {}

    now = current_in.get("time")
    try:
        now_dt = _dt.datetime.fromisoformat(now)
    except Exception:
        now_dt = _dt.datetime.now()

    current_code = current_in.get("weather_code")
    current = {
        "time": now,
        "temperature": current_in.get("temperature_2m"),
        "feels_like": current_in.get("apparent_temperature"),
        "humidity": current_in.get("relative_humidity_2m"),
        "precipitation": current_in.get("precipitation"),
        "cloud_cover": current_in.get("cloud_cover"),
        "pressure": current_in.get("pressure_msl"),
        "wind_speed": current_in.get("wind_speed_10m"),
        "wind_direction": current_in.get("wind_direction_10m"),
        "wind_gusts": current_in.get("wind_gusts_10m"),
        "is_day": bool(current_in.get("is_day")),
        "soil_temperature": current_in.get("soil_temperature_6cm"),
        "soil_moisture": current_in.get("soil_moisture_3_to_9cm"),
        "et0": current_in.get("et0_fao_evapotranspiration"),
        "weather": code_info(current_code),
    }

    # ---- hourly (next 48 h from now) -------------------------------------
    times = hourly_in.get("time") or []
    hourly = []
    for i, stamp in enumerate(times):
        try:
            stamp_dt = _dt.datetime.fromisoformat(stamp)
        except Exception:
            continue
        if stamp_dt < now_dt.replace(minute=0, second=0, microsecond=0):
            continue
        if len(hourly) >= 48:
            break
        hourly.append({
            "time": stamp,
            "hour": stamp_dt.strftime("%H:%M"),
            "day": stamp_dt.strftime("%a"),
            "temperature": _value(hourly_in, "temperature_2m", i),
            "humidity": _value(hourly_in, "relative_humidity_2m", i),
            "precipitation": _value(hourly_in, "precipitation", i),
            "precipitation_probability": _value(hourly_in, "precipitation_probability", i),
            "wind_speed": _value(hourly_in, "wind_speed_10m", i),
            "wind_gusts": _value(hourly_in, "wind_gusts_10m", i),
            "cloud_cover": _value(hourly_in, "cloud_cover", i),
            "et0": _value(hourly_in, "et0_fao_evapotranspiration", i),
            "soil_moisture": _value(hourly_in, "soil_moisture_3_to_9cm", i),
            "is_day": bool(_value(hourly_in, "is_day", i)),
        })

    if hourly:
        current["et0"] = hourly[0].get("et0")
        current["soil_moisture"] = current.get("soil_moisture") or hourly[0].get("soil_moisture")

    # ---- daily ------------------------------------------------------------
    dates = daily_in.get("time") or []
    today = now_dt.date()
    daily, past_daily = [], []
    for i, date_str in enumerate(dates):
        try:
            date_obj = _dt.date.fromisoformat(date_str)
        except Exception:
            continue
        row = {
            "date": date_str,
            "weekday": date_obj.strftime("%a"),
            "day": date_obj.day,
            "month": date_obj.strftime("%b"),
            "is_today": date_obj == today,
            "temp_max": _value(daily_in, "temperature_2m_max", i),
            "temp_min": _value(daily_in, "temperature_2m_min", i),
            "precipitation_sum": _value(daily_in, "precipitation_sum", i) or 0,
            "precipitation_probability_max": _value(daily_in, "precipitation_probability_max", i),
            "wind_max": _value(daily_in, "wind_speed_10m_max", i),
            "wind_gusts_max": _value(daily_in, "wind_gusts_10m_max", i),
            "humidity_mean": _value(daily_in, "relative_humidity_2m_mean", i),
            "et0": _value(daily_in, "et0_fao_evapotranspiration", i),
            "sunrise": _value(daily_in, "sunrise", i),
            "sunset": _value(daily_in, "sunset", i),
            "radiation": _value(daily_in, "shortwave_radiation_sum", i),
            "weather": code_info(_value(daily_in, "weather_code", i)),
        }
        (daily if date_obj >= today else past_daily).append(row)

    rain_past_3d = round(sum(d["precipitation_sum"] or 0 for d in past_daily[-3:]), 1)
    rain_next_7d = round(sum(d["precipitation_sum"] or 0 for d in daily[:7]), 1)
    et0_next_7d = round(sum(d["et0"] or 0 for d in daily[:7]), 1)

    return {
        "ok": True,
        "source": "open-meteo",
        "source_label": "Open-Meteo live forecast",
        "estimated": False,
        "location": {
            "label": location_label or data.get("timezone", ""),
            "latitude": data.get("latitude", latitude),
            "longitude": data.get("longitude", longitude),
            "elevation": data.get("elevation"),
            "timezone": data.get("timezone", ""),
            "timezone_abbreviation": data.get("timezone_abbreviation", ""),
        },
        "current": current,
        "hourly": hourly,
        "daily": daily,
        "past_daily": past_daily,
        "summary": {
            "rain_past_3d_mm": rain_past_3d,
            "rain_next_7d_mm": rain_next_7d,
            "et0_next_7d_mm": et0_next_7d,
            "water_balance_7d_mm": round(rain_next_7d - et0_next_7d, 1),
        },
        "fetched_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- offline estimate

def _climate_normals(latitude, month):
    """Very rough climatological normals used only when the network is unavailable."""
    north = max(0.0, min(1.0, (float(latitude) - 12.0) / 18.0))
    base = 28.0 - 3.0 * north
    amplitude = 2.5 + 6.0 * north
    temp_mean = base + amplitude * math.cos(2 * math.pi * (month - 5) / 12.0)

    monsoon = math.exp(-((month - 7.5) / 2.0) ** 2)
    humidity = 45.0 + 10.0 * (1.0 - north) + 40.0 * monsoon

    rain_peak = 6.0 + 3.0 * north
    daily_rain = 0.3 + rain_peak * monsoon
    if north < 0.4:  # peninsular India gets a northeast monsoon too
        daily_rain += 3.0 * math.exp(-((month - 10.5) / 1.4) ** 2)

    et0 = 1.8 + 0.14 * (temp_mean - 12.0) - 0.012 * (humidity - 50.0)
    return {
        "temp_mean": round(temp_mean, 1),
        "humidity": round(min(95.0, max(25.0, humidity)), 0),
        "rain_mm": round(max(0.0, daily_rain), 1),
        "et0": round(min(7.5, max(1.2, et0)), 1),
    }


def estimate_forecast(latitude, longitude, location_label="", reason=""):
    """Labelled offline fallback built from seasonal climate normals."""
    today = _dt.date.today()
    days = []
    for offset in range(7):
        date_obj = today + _dt.timedelta(days=offset)
        normals = _climate_normals(latitude, date_obj.month)
        # small deterministic day-to-day wobble so the series looks natural
        wobble = math.sin((date_obj.toordinal() % 29) / 29.0 * 2 * math.pi)
        temp = normals["temp_mean"] + 2.0 * wobble
        rain = max(0.0, round(normals["rain_mm"] * (1.0 + 0.6 * wobble), 1))
        rain_prob = int(max(0, min(95, normals["humidity"] - 15 + 25 * wobble)))
        code = 61 if rain > 4 else (80 if rain > 1.5 else (3 if rain_prob > 60 else 2))
        days.append({
            "date": date_obj.isoformat(),
            "weekday": date_obj.strftime("%a"),
            "day": date_obj.day,
            "month": date_obj.strftime("%b"),
            "is_today": offset == 0,
            "temp_max": round(temp + 5.0, 1),
            "temp_min": round(temp - 5.0, 1),
            "precipitation_sum": rain,
            "precipitation_probability_max": rain_prob,
            "wind_max": round(9 + 7 * abs(wobble), 1),
            "wind_gusts_max": round(18 + 10 * abs(wobble), 1),
            "humidity_mean": normals["humidity"],
            "et0": normals["et0"],
            "sunrise": None,
            "sunset": None,
            "radiation": None,
            "weather": code_info(code),
        })

    first = days[0]
    noon_temp = round((first["temp_max"] + first["temp_min"]) / 2, 1)
    current = {
        "time": _dt.datetime.now().isoformat(timespec="minutes"),
        "temperature": noon_temp,
        "feels_like": round(noon_temp + (first["humidity_mean"] - 60) / 20.0, 1),
        "humidity": first["humidity_mean"],
        "precipitation": 0,
        "cloud_cover": 50,
        "pressure": 1010,
        "wind_speed": round(first["wind_max"] * 0.6, 1),
        "wind_direction": 225,
        "wind_gusts": round(first["wind_gusts_max"] * 0.6, 1),
        "is_day": True,
        "soil_temperature": round(noon_temp - 1, 1),
        "soil_moisture": None,
        "et0": first["et0"],
        "weather": first["weather"],
    }

    hourly = []
    for d in days[:3]:
        for hour in range(0, 24, 3):
            warm = math.sin((hour - 6) / 24.0 * 2 * math.pi)
            hourly.append({
                "time": f"{d['date']}T{hour:02d}:00",
                "hour": f"{hour:02d}:00",
                "day": d["weekday"],
                "temperature": round((d["temp_max"] + d["temp_min"]) / 2 + warm * (d["temp_max"] - d["temp_min"]) / 2, 1),
                "humidity": d["humidity_mean"],
                "precipitation": round(d["precipitation_sum"] / 8.0, 1),
                "precipitation_probability": d["precipitation_probability_max"],
                "wind_speed": d["wind_max"] * 0.7,
                "wind_gusts": d["wind_gusts_max"] * 0.7,
                "cloud_cover": 50,
                "et0": round(max(0.0, d["et0"] / 8.0 * (1 + warm)), 2) if 6 <= hour <= 18 else 0.0,
                "soil_moisture": None,
                "is_day": 6 <= hour <= 18,
            })

    return {
        "ok": True,
        "source": "estimate",
        "source_label": "Offline climate-normal estimate (not a live forecast)",
        "estimated": True,
        "estimate_reason": reason,
        "location": {
            "label": location_label,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "elevation": None,
            "timezone": "local",
            "timezone_abbreviation": "",
        },
        "current": current,
        "hourly": hourly,
        "daily": days,
        "past_daily": [],
        "summary": {
            "rain_past_3d_mm": None,
            "rain_next_7d_mm": round(sum(d["precipitation_sum"] for d in days), 1),
            "et0_next_7d_mm": round(sum(d["et0"] for d in days), 1),
            "water_balance_7d_mm": round(sum(d["precipitation_sum"] - d["et0"] for d in days), 1),
        },
        "fetched_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }


def get_weather(location=None, latitude=None, longitude=None, label=""):
    """Main entry point. Uses coordinates if given, otherwise geocodes the name."""
    if latitude is None or longitude is None:
        if not location:
            raise WeatherError("Provide a place name or coordinates.")
        matches = geocode(location, count=1)
        if not matches:
            raise WeatherError(f"No location found for '{location}'. Try a nearby town or district.")
        best = matches[0]
        latitude, longitude = best["latitude"], best["longitude"]
        label = label or best["label"]

    try:
        return fetch_forecast(latitude, longitude, location_label=label)
    except WeatherError as exc:
        return estimate_forecast(latitude, longitude, location_label=label, reason=str(exc))


def effective_rainfall(rain_mm):
    """USDA-style effective rainfall approximation."""
    rain_mm = float(rain_mm or 0)
    if rain_mm <= 0:
        return 0.0
    if rain_mm <= 25:
        return round(rain_mm * 0.8, 1)
    if rain_mm <= 75:
        return round(0.8 * rain_mm - 0.2 * (rain_mm - 25), 1)
    return round(0.6 * rain_mm, 1)


def compass(direction):
    if direction is None:
        return ""
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((float(direction) % 360) / 22.5 + 0.5) % 16
    return points[index]
