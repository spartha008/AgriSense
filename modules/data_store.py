"""Loads and indexes the JSON knowledge base in /data."""

import json
import os
import threading

_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_lock = threading.Lock()
_cache = {}


def _load(filename):
    with _lock:
        if filename not in _cache:
            path = os.path.join(_BASE, filename)
            with open(path, encoding="utf-8") as fh:
                _cache[filename] = json.load(fh)
        return _cache[filename]


# --------------------------------------------------------------------------- crops

def crops():
    """Full crop records, alphabetical by name."""
    return sorted(_load("crops.json"), key=lambda c: c["name"])


def crop_ids():
    return [c["id"] for c in crops()]


def crop(crop_id):
    if not crop_id:
        return None
    crop_id = str(crop_id).strip().lower()
    for item in _load("crops.json"):
        if item["id"] == crop_id:
            return item
    return None


def crop_summary(item):
    """Small payload for list views."""
    return {
        "id": item["id"],
        "name": item["name"],
        "local_names": item.get("local_names", ""),
        "emoji": item.get("emoji", "\U0001f331"),
        "category": item.get("category", ""),
        "season": item.get("season", ""),
        "scientific": item.get("scientific", ""),
        "water_requirement": item.get("water_requirement", "medium"),
        "duration_days": item.get("duration_days", ""),
        "soil_ph": item.get("soil_ph", ""),
    }


# --------------------------------------------------------------------------- diseases

def diseases():
    return sorted(_load("diseases.json"), key=lambda d: d["name"])


def disease(disease_id):
    if not disease_id:
        return None
    disease_id = str(disease_id).strip().lower()
    for item in _load("diseases.json"):
        if item["id"] == disease_id:
            return item
    return None


def diseases_for_crop(crop_id):
    if not crop_id:
        return diseases()
    crop_id = str(crop_id).strip().lower()
    return [d for d in diseases() if crop_id in d.get("crop_ids", [])]


def search_diseases(query="", crop_id=None, pathogen_type=None):
    """Free-text + faceted search over the disease catalogue."""
    items = diseases_for_crop(crop_id)
    if pathogen_type:
        wanted = pathogen_type.strip().lower()
        items = [d for d in items if d.get("pathogen_type", "").lower() == wanted]

    query = (query or "").strip().lower()
    if not query:
        return items

    terms = [t for t in query.replace(",", " ").split() if t]

    def score(item):
        haystack = " ".join([
            item["name"],
            item.get("pathogen", ""),
            item.get("pathogen_type", ""),
            " ".join(item.get("symptoms", [])),
            " ".join(item.get("crops", [])),
            item.get("overview", ""),
        ]).lower()
        hits = sum(1 for t in terms if t in haystack)
        if query in item["name"].lower():
            hits += 3
        return hits

    scored = [(score(d), d) for d in items]
    return [d for s, d in sorted(scored, key=lambda p: (-p[0], p[1]["name"])) if s > 0]


def disease_summary(item):
    return {
        "id": item["id"],
        "name": item["name"],
        "crops": item.get("crops", []),
        "crop_ids": item.get("crop_ids", []),
        "pathogen_type": item.get("pathogen_type", ""),
        "pathogen": item.get("pathogen", ""),
        "severity": item.get("severity", "medium"),
        "overview": item.get("overview", ""),
        "symptom_count": len(item.get("symptoms", [])),
    }


def pathogen_types():
    return sorted({d.get("pathogen_type", "Other") for d in diseases()})


# --------------------------------------------------------------------------- tips & season

def tips():
    return _load("tips.json")


def tip_categories():
    seen = []
    for t in tips():
        if t["category"] not in seen:
            seen.append(t["category"])
    return seen


def seasonal():
    return sorted(_load("seasonal.json"), key=lambda m: m["month"])


def month_info(month_number):
    month_number = int(month_number)
    for m in seasonal():
        if m["month"] == month_number:
            return m
    return None


def stats():
    return {
        "crops": len(crops()),
        "diseases": len(diseases()),
        "tips": len(tips()),
        "months": len(seasonal()),
    }
