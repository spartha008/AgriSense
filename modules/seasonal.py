"""Seasonal calendar, reminders and tip filtering."""

import datetime as _dt

from . import data_store

SEASONS = [
    (6, 10, "Kharif", "Monsoon season - sow with the rains and manage drainage."),
    (11, 12, "Rabi", "Winter season - cool-weather crops and the most reliable irrigation window."),
    (1, 3, "Rabi", "Winter to early summer - finish rabi harvest and protect grain filling."),
    (4, 5, "Zaid", "Summer season - high water demand, mulch and irrigate carefully."),
]


def season_for(month):
    for start, end, name, note in SEASONS:
        if start <= end and start <= month <= end:
            return name, note
        if start > end and (month >= start or month <= end):
            return name, note
    return "Kharif", "Monsoon season."


def current(month=None):
    today = _dt.date.today()
    month = int(month) if month else today.month
    month = max(1, min(12, month))

    info = data_store.month_info(month)
    name, note = season_for(month)

    days_in_month = ((_dt.date(today.year + (1 if month == 12 else 0), (month % 12) + 1, 1)
                      - _dt.date(today.year, month, 1)).days)
    if today.month == month:
        day = today.day
        days_left = days_in_month - day + 1
    else:
        day = None
        days_left = None

    return {
        "month": month,
        "month_name": info["name"] if info else _dt.date(2000, month, 1).strftime("%B"),
        "season": name,
        "season_note": note,
        "focus": info.get("focus", "") if info else "",
        "sow": info.get("sow", []) if info else [],
        "care": info.get("care", []) if info else [],
        "watch": info.get("watch", []) if info else [],
        "irrigation_hint": info.get("irrigation_hint", "") if info else "",
        "day_of_month": day,
        "days_in_month": days_in_month,
        "days_left": days_left,
        "is_current_month": today.month == month,
        "today": today.isoformat(),
        "next_month": data_store.month_info(month % 12 + 1)["name"] if data_store.month_info(month % 12 + 1) else "",
    }


def tips(category=None, query=None, limit=None):
    items = data_store.tips()
    if category:
        wanted = category.strip().lower()
        items = [t for t in items if t["category"].lower() == wanted]
    if query:
        needle = query.strip().lower()
        items = [t for t in items
                 if needle in t["title"].lower() or needle in t["body"].lower()
                 or needle in t["category"].lower()]
    if limit:
        items = items[: int(limit)]
    return items


def calendar():
    out = []
    for m in data_store.seasonal():
        name, _ = season_for(m["month"])
        out.append({
            "month": m["month"],
            "name": m["name"],
            "season": name,
            "focus": m["focus"],
            "sow_count": len(m.get("sow", [])),
            "watch_count": len(m.get("watch", [])),
        })
    return out
