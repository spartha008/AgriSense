"""Irrigation planning based on FAO-56 style water balance (Kc x ET0)."""

import datetime as _dt
import math

from . import data_store
from .weather import effective_rainfall

# available water capacity in mm per metre of soil
SOIL_AWC = {
    "sand": 60,
    "sandy loam": 110,
    "loam": 150,
    "silt loam": 170,
    "clay loam": 180,
    "clay": 200,
    "black (vertisol)": 190,
}

SOIL_NOTES = {
    "sand": "Sandy soil holds little water - irrigate little and often.",
    "sandy loam": "Sandy loam drains fast; frequent light irrigations work best.",
    "loam": "Loam is the easiest to manage - moderate depths at moderate intervals.",
    "silt loam": "Silt loam holds good moisture but crusts; avoid heavy flooding.",
    "clay loam": "Clay loam holds a lot of water; irrigate less often but thoroughly.",
    "clay": "Heavy clay needs longer intervals and careful drainage - it waterlogs easily.",
    "black (vertisol)": "Black soil swells and cracks; avoid flooding and check drainage.",
}

EFFICIENCY = {
    "drip": 0.90,
    "sprinkler": 0.75,
    "raingun": 0.70,
    "furrow": 0.60,
    "flood": 0.50,
}

METHOD_LABEL = {
    "drip": "Drip irrigation",
    "sprinkler": "Sprinkler irrigation",
    "raingun": "Rain gun",
    "furrow": "Furrow / ridge irrigation",
    "flood": "Flood / basin irrigation",
}

STAGES = [
    {"id": "establishment", "name": "Establishment / nursery", "kc": 0.45, "root": 0.35},
    {"id": "vegetative", "name": "Vegetative growth", "kc": 0.80, "root": 0.70},
    {"id": "flowering", "name": "Flowering / reproductive", "kc": 1.10, "root": 1.00},
    {"id": "filling", "name": "Fruit / grain filling", "kc": 1.00, "root": 1.00},
    {"id": "maturity", "name": "Maturity / ripening", "kc": 0.70, "root": 0.95},
]

CRITICAL_STAGES = {"flowering", "filling"}

KC_MID = {"very high": 1.25, "high": 1.15, "medium": 1.05, "low": 0.95}
DEPLETION_FRACTION = {"very high": 0.35, "high": 0.40, "medium": 0.50, "low": 0.60}

ROOT_DEPTH = {
    "Cereal": 0.9, "Millet": 0.9, "Pulse": 0.7, "Oilseed / Pulse": 0.8,
    "Oilseed": 0.8, "Fibre": 1.0, "Cash crop": 1.2, "Vegetable": 0.5, "Fruit": 0.9,
}

AREA_IN_M2 = {"acre": 4046.86, "hectare": 10000.0}


def stage_by_id(stage_id):
    for s in STAGES:
        if s["id"] == stage_id:
            return s
    return None


def plan(payload):
    payload = payload or {}

    crop = data_store.crop(payload.get("crop_id"))
    crop_name = crop["name"] if crop else "General crop"
    category = crop.get("category", "Cereal") if crop else "Cereal"
    water_need = (crop or {}).get("water_requirement", "medium")

    stage = stage_by_id(payload.get("stage")) or stage_by_id("vegetative")

    # ---- area -------------------------------------------------------------
    unit = (payload.get("area_unit") or "acre").lower()
    if unit not in AREA_IN_M2:
        unit = "acre"
    try:
        area = float(payload.get("area") or 1)
    except (TypeError, ValueError):
        area = 1.0
    area = max(0.01, min(area, 10000.0))
    area_m2 = area * AREA_IN_M2[unit]

    # ---- soil -------------------------------------------------------------
    soil_type = (payload.get("soil_type") or "loam").strip().lower()
    if soil_type not in SOIL_AWC:
        soil_type = "loam"
    method = (payload.get("method") or "furrow").strip().lower()
    if method not in EFFICIENCY:
        method = "furrow"
    efficiency = EFFICIENCY[method]

    # ---- climate inputs ---------------------------------------------------
    warnings = []
    et0 = payload.get("et0")
    try:
        et0 = float(et0) if et0 is not None and et0 != "" else None
    except (TypeError, ValueError):
        et0 = None
    if et0 is None or et0 <= 0:
        et0 = 4.0
        warnings.append("No ET\u2080 was supplied, so a typical value of 4.0 mm/day was assumed. "
                        "Load live weather for a location-specific figure.")

    try:
        rain_forecast = float(payload.get("rain_forecast_mm") or 0)
    except (TypeError, ValueError):
        rain_forecast = 0.0
    try:
        rain_recent = float(payload.get("rain_recent_mm") or 0)
    except (TypeError, ValueError):
        rain_recent = 0.0

    horizon = max(1.0, float(payload.get("horizon_days") or 7))
    pe_total = effective_rainfall(rain_forecast)
    pe_daily = pe_total / horizon

    # ---- crop water use ---------------------------------------------------
    kc_mid = KC_MID.get(water_need, 1.05)
    kc = round(kc_mid * stage["kc"], 2)
    etc = kc * et0  # crop evapotranspiration, mm/day

    net_daily = etc - pe_daily
    deficit = net_daily > 0.05

    # ---- soil water reservoir --------------------------------------------
    full_root = ROOT_DEPTH.get(category, 0.9)
    root_depth = round(full_root * stage["root"], 2)
    awc = SOIL_AWC[soil_type]
    taw = round(awc * root_depth, 1)                       # total available water, mm
    p = DEPLETION_FRACTION.get(water_need, 0.5)
    raw = round(p * taw, 1)                                # readily available water, mm

    # ---- current depletion ------------------------------------------------
    try:
        days_since = float(payload.get("last_irrigation_days_ago"))
    except (TypeError, ValueError):
        days_since = None

    if days_since is None:
        depletion = round(0.5 * raw, 1)
        warnings.append("Last irrigation date was not given, so the soil is assumed to be about "
                        "half-depleted.")
    else:
        depletion = days_since * etc - effective_rainfall(rain_recent)
        depletion = max(0.0, min(taw, depletion))
        depletion = round(depletion, 1)

    soil_moisture_pct = round(max(0.0, (1 - depletion / taw) * 100)) if taw else 0

    # ---- scheduling -------------------------------------------------------
    consumption = max(0.05, etc - pe_daily)

    if not deficit:
        days_to_irrigation = None
        net_depth = 0.0
        gross_depth = 0.0
        interval_days = None
        status = "no_irrigation"
    else:
        if depletion >= raw:
            days_to_irrigation = 0.0
            status = "irrigate_now"
        else:
            days_to_irrigation = (raw - depletion) / consumption
            days_to_irrigation = round(max(0.0, min(days_to_irrigation, 30.0)), 1)
            status = "scheduled"

        net_depth = raw
        gross_depth = round(net_depth / efficiency, 1)
        interval_days = round(raw / consumption, 1)

    gross_m3 = round(gross_depth * area_m2 / 1000.0, 1)
    net_m3 = round(net_depth * area_m2 / 1000.0, 1)
    per_acre_m3 = round(gross_depth * AREA_IN_M2["acre"] / 1000.0, 1)

    today = _dt.date.today()
    next_date = None
    if days_to_irrigation is not None:
        next_date = (today + _dt.timedelta(days=int(math.floor(days_to_irrigation)))).isoformat()

    # ---- 10-day forward schedule -----------------------------------------
    schedule = []
    running = depletion
    step_consumption = max(0.05, etc - pe_daily)
    for offset in range(10):
        day = today + _dt.timedelta(days=offset)
        irrigate_today = False
        if deficit and running >= raw - 0.01:
            irrigate_today = True
            running = 0.0
        pct = round(max(0.0, (1 - running / taw) * 100)) if taw else 0
        schedule.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%a"),
            "day": day.day,
            "month": day.strftime("%b"),
            "depletion_mm": round(running, 1),
            "moisture_pct": pct,
            "irrigate": irrigate_today,
            "irrigation_mm": round(raw, 1) if irrigate_today else 0,
        })
        running = min(taw, running + step_consumption)

    # ---- advice -----------------------------------------------------------
    advice = []
    if not deficit:
        advice.append(f"Forecast rainfall covers the water demand of about {round(etc, 1)} mm/day. "
                      "Skip irrigation for now and re-check after the rain.")
    elif status == "irrigate_now":
        advice.append(f"Soil moisture at the root zone is below the safe threshold. Irrigate now with "
                      f"about {net_depth} mm net ({gross_depth} mm gross) of water.")
    else:
        advice.append(f"Next irrigation in about {days_to_irrigation} day(s): "
                      f"{net_depth} mm net / {gross_depth} mm gross of water.")

    advice.append(f"Crop water use (ETc) is about {round(etc, 1)} mm/day at the "
                  f"{stage['name'].lower()} stage (Kc {kc}, ET\u2080 {round(et0, 1)} mm/day).")

    if interval_days is not None:
        advice.append(f"At the current demand, the interval between irrigations should be about "
                      f"{interval_days} day(s).")

    if stage["id"] in CRITICAL_STAGES:
        advice.append("This is a critical water-sensitive stage - do not let the soil dry beyond the "
                      "safe threshold. Protect this stage before any other operation.")

    advice.append(SOIL_NOTES[soil_type])
    advice.append(f"With {METHOD_LABEL[method].lower()} (about {int(efficiency * 100)}% efficient), "
                  f"about {gross_m3} m\u00b3 of water is needed per application for {area:g} {unit}(s).")

    if method in ("flood", "furrow"):
        advice.append("Switching to drip or sprinkler could cut this water need by 25-40% and usually "
                      "improves yield as well.")
    if method == "sprinkler":
        advice.append("Run sprinklers in the early morning so foliage dries during the day - "
                      "evening wetting invites blight and leaf spot.")

    if crop:
        for tip in (crop.get("irrigation", {}).get("tips") or [])[:2]:
            advice.append(tip)

    if interval_days is not None and interval_days <= 2:
        warnings.append("The irrigation interval is very short. On light soils, split the depth into "
                        "smaller, more frequent applications to avoid deep percolation losses.")

    if rain_forecast >= 25:
        advice.append(f"About {round(rain_forecast, 1)} mm of rain is forecast; the effective portion "
                      f"is roughly {round(pe_total, 1)} mm, which has already been credited.")

    if not crop:
        warnings.append("No crop was selected, so generic medium-water-need parameters were used. "
                        "Pick a crop for a stage-accurate plan.")

    best_time = "Early morning (6-9 am) is the most efficient irrigation time."

    return {
        "crop": {
            "id": crop["id"] if crop else None,
            "name": crop_name,
            "category": category,
            "water_requirement": water_need,
        },
        "stage": stage,
        "inputs": {
            "area": area,
            "area_unit": unit,
            "area_m2": round(area_m2, 1),
            "soil_type": soil_type,
            "method": method,
            "method_label": METHOD_LABEL[method],
            "efficiency_pct": int(efficiency * 100),
            "et0": round(et0, 2),
            "rain_forecast_mm": round(rain_forecast, 1),
            "rain_recent_mm": round(rain_recent, 1),
            "horizon_days": horizon,
        },
        "water_use": {
            "kc": kc,
            "etc_mm_day": round(etc, 2),
            "effective_rain_mm_day": round(pe_daily, 2),
            "effective_rain_total_mm": round(pe_total, 1),
            "net_demand_mm_day": round(max(0.0, net_daily), 2),
            "deficit": deficit,
        },
        "soil": {
            "type": soil_type,
            "awc_mm_per_m": awc,
            "root_depth_m": root_depth,
            "taw_mm": taw,
            "depletion_fraction": p,
            "raw_mm": raw,
            "current_depletion_mm": depletion,
            "moisture_pct": soil_moisture_pct,
        },
        "recommendation": {
            "status": status,
            "days_to_irrigation": days_to_irrigation,
            "next_irrigation_date": next_date,
            "net_depth_mm": round(net_depth, 1),
            "gross_depth_mm": round(gross_depth, 1),
            "interval_days": interval_days,
            "net_volume_m3": net_m3,
            "gross_volume_m3": gross_m3,
            "gross_volume_per_acre_m3": per_acre_m3,
            "gross_volume_litres": int(gross_m3 * 1000),
            "best_time": best_time,
        },
        "schedule": schedule,
        "advice": advice,
        "warnings": warnings,
    }


def options():
    """Option lists for the irrigation planner UI."""
    return {
        "soils": [{"id": k, "label": k.title(), "awc": v, "note": SOIL_NOTES[k]} for k, v in SOIL_AWC.items()],
        "methods": [{"id": k, "label": METHOD_LABEL[k], "efficiency": int(v * 100)} for k, v in EFFICIENCY.items()],
        "stages": [{"id": s["id"], "name": s["name"]} for s in STAGES],
        "area_units": [{"id": "acre", "label": "Acre"}, {"id": "hectare", "label": "Hectare"}],
    }
