"""Crop disease catalogue plus an offline, explainable leaf-image analyzer.

The analyzer is a colour and texture heuristic, not a trained classifier. It is
deliberately transparent: every score it produces is reported so a user can see
exactly why it reached a conclusion.
"""

import colorsys
import io
import math

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from . import data_store

# --------------------------------------------------------------------------- tags

TAG_LABELS = {
    "healthy_green": "Uniform healthy green tissue",
    "orange_pustules": "Orange/rust-coloured pustules",
    "yellow_pustules": "Yellow pustules or powdery yellow spots",
    "white_powder": "White powdery surface growth",
    "gray_fuzz": "Grey/fuzzy mould growth",
    "gray_center_brown_margin": "Lesions with a pale centre and dark margin",
    "concentric_rings": "Target-board / concentric rings in lesions",
    "dark_water_soaked": "Large dark water-soaked patches",
    "dark_necrotic_spots": "Dark necrotic spots",
    "black_spots": "Hard black spots / sclerotia",
    "yellow_margin": "Yellowing concentrated along the margins",
    "uniform_chlorosis": "Widespread uniform yellowing (chlorosis)",
    "mosaic_mottle": "Mottled light/dark green mosaic pattern",
    "vein_clearing": "Cleared or yellowed veins",
    "purple_blotch": "Purple-brown blotches",
    "leaf_curl": "Curled, puckered or distorted leaf shape",
    "patchy_wilting": "Patches of wilted, browned tissue",
    "silvery_streaks": "Silvery or streaky pale areas",
    "yellow_halo_spots": "Spots surrounded by a yellow halo",
}

# symptom questionnaire -> tag boosts
SYMPTOM_BOOSTS = {
    "powdery_white": {"white_powder": 0.65},
    "orange_pustules": {"orange_pustules": 0.75, "yellow_pustules": 0.30},
    "yellow_stripes_margin": {"yellow_margin": 0.75, "silvery_streaks": 0.25},
    "concentric_rings": {"concentric_rings": 0.75, "yellow_halo_spots": 0.30},
    "water_soaked_dark": {"dark_water_soaked": 0.75, "gray_fuzz": 0.20},
    "grey_center_brown_margin": {"gray_center_brown_margin": 0.75},
    "yellow_halo_spots": {"yellow_halo_spots": 0.65, "concentric_rings": 0.20},
    "black_spots": {"black_spots": 0.65, "dark_necrotic_spots": 0.20},
    "purple_blotch": {"purple_blotch": 0.75},
    "curled_leaves": {"leaf_curl": 0.75, "mosaic_mottle": 0.20},
    "mosaic_mottle": {"mosaic_mottle": 0.75, "vein_clearing": 0.30},
    "wilting_green_leaves": {"patchy_wilting": 0.75, "dark_water_soaked": 0.20},
    "uniform_yellowing": {"uniform_chlorosis": 0.75},
    "white_downy_underside": {"gray_fuzz": 0.65, "white_powder": 0.25},
    "stem_lesion": {"dark_necrotic_spots": 0.40, "gray_center_brown_margin": 0.20},
    "stunted_growth": {"patchy_wilting": 0.25, "uniform_chlorosis": 0.25},
    "healthy": {"healthy_green": 0.85},
}

SYMPTOM_OPTIONS = [
    {"id": "healthy", "label": "Leaves look healthy and evenly green"},
    {"id": "powdery_white", "label": "White powdery growth on the surface"},
    {"id": "white_downy_underside", "label": "White/grey fuzzy growth on the leaf underside"},
    {"id": "orange_pustules", "label": "Small orange/brown raised pustules"},
    {"id": "black_spots", "label": "Hard black specks, difficult to rub off"},
    {"id": "concentric_rings", "label": "Spots with concentric rings (target board)"},
    {"id": "grey_center_brown_margin", "label": "Diamond or oval spots, pale centre with dark border"},
    {"id": "yellow_halo_spots", "label": "Brown spots surrounded by a yellow halo"},
    {"id": "water_soaked_dark", "label": "Large dark water-soaked patches"},
    {"id": "purple_blotch", "label": "Purple-brown blotches on leaves"},
    {"id": "yellow_stripes_margin", "label": "Yellow/white stripes along the leaf margin"},
    {"id": "uniform_yellowing", "label": "Leaves uniformly yellow, starting from older leaves"},
    {"id": "mosaic_mottle", "label": "Mottled patches of light and dark green"},
    {"id": "curled_leaves", "label": "Leaves curled, puckered or cupped"},
    {"id": "wilting_green_leaves", "label": "Whole plant wilting while leaves are still green"},
    {"id": "stem_lesion", "label": "Dark lesions or rotting at the stem base"},
    {"id": "stunted_growth", "label": "Stunted, bushy growth with small leaves"},
]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _ramp(x, lo, hi):
    if hi == lo:
        return 0.0
    return _clamp((x - lo) / (hi - lo))


def _boost(base, amount):
    return 1.0 - (1.0 - base) * (1.0 - amount)


# --------------------------------------------------------------------------- pixels

def _classify(h, s, v):
    """Colour class of a single pixel. Background is resolved separately."""
    if v < 0.22:
        return "dark"
    if s < 0.18 and v > 0.55:
        return "white"
    if 70 <= h <= 175 and s > 0.15:
        return "green"
    if 45 <= h < 70 and s > 0.18:
        return "yellow"
    if 20 <= h < 40 and s > 0.62 and v > 0.50:
        return "orange"
    if 280 <= h <= 345 and s > 0.12:
        return "purple"
    if h < 45:
        return "brown"
    return "other"


def _flat_or_sky(h, s, v):
    """Pixels that *could* be a plain background: near-white, near-grey or sky."""
    if s < 0.14 and v > 0.62:
        return True
    if 190 <= h <= 278 and s > 0.20 and v > 0.35:
        return True
    return False


def _analyze_pixels(rgb_image, size=200):
    """Classify every pixel, then resolve the background.

    Background is whatever flat/sky-like colour region touches the image border.
    Flood filling from the border means a white powdery mildew patch *inside*
    the leaf is still measured as mildew, while a white studio backdrop is not.
    """
    img = rgb_image.resize((size, size), Image.LANCZOS)
    pixels = list(img.getdata())
    n = size * size

    cache = {}
    grid = [None] * n
    hsv = [None] * n
    flat = bytearray(n)

    for i, (r, g, b) in enumerate(pixels):
        key = (r, g, b)
        entry = cache.get(key)
        if entry is None:
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            h *= 360.0
            entry = (h, s, v, _classify(h, s, v), 1 if _flat_or_sky(h, s, v) else 0)
            cache[key] = entry
        h, s, v, cls, is_flat = entry
        grid[i] = cls
        hsv[i] = (h, s, v)
        flat[i] = is_flat

    # flood fill background inward from every border pixel
    background = bytearray(n)
    queue = []
    for i in range(size):
        for idx in (i, (size - 1) * size + i, i * size, i * size + size - 1):
            if flat[idx] and not background[idx]:
                background[idx] = 1
                queue.append(idx)

    head = 0
    while head < len(queue):
        idx = queue[head]
        head += 1
        x, y = idx % size, idx // size
        if x > 0:
            nxt = idx - 1
            if flat[nxt] and not background[nxt]:
                background[nxt] = 1
                queue.append(nxt)
        if x < size - 1:
            nxt = idx + 1
            if flat[nxt] and not background[nxt]:
                background[nxt] = 1
                queue.append(nxt)
        if y > 0:
            nxt = idx - size
            if flat[nxt] and not background[nxt]:
                background[nxt] = 1
                queue.append(nxt)
        if y < size - 1:
            nxt = idx + size
            if flat[nxt] and not background[nxt]:
                background[nxt] = 1
                queue.append(nxt)

    counts = {k: 0 for k in ("green", "yellow", "orange", "brown", "dark",
                             "white", "purple", "other", "background")}
    analyzed = 0
    very_dark = 0
    sat_sum = val_sum = 0.0

    for i in range(n):
        if background[i]:
            grid[i] = "background"
            counts["background"] += 1
            continue
        counts[grid[i]] += 1
        analyzed += 1
        sat_sum += hsv[i][1]
        val_sum += hsv[i][2]
        if hsv[i][2] < 0.13:
            very_dark += 1

    return grid, hsv, pixels, counts, analyzed, very_dark, sat_sum, val_sum, size


def _blobs(grid, size, lesion_classes=("brown", "dark", "orange", "purple")):
    """Connected components of lesion pixels on a coarser grid."""
    step = max(1, size // 100)
    w = size // step
    mask = [[False] * w for _ in range(w)]
    for j in range(w):
        for i in range(w):
            mask[j][i] = grid[(j * step) * size + (i * step)] in lesion_classes

    seen = [[False] * w for _ in range(w)]
    sizes = []
    largest = 0
    for j in range(w):
        for i in range(w):
            if not mask[j][i] or seen[j][i]:
                continue
            stack = [(i, j)]
            seen[j][i] = True
            area = 0
            while stack:
                x, y = stack.pop()
                area += 1
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < w and mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            sizes.append(area)
            largest = max(largest, area)

    total = sum(sizes)
    meaningful = [s for s in sizes if s >= 3]
    return {
        "count": len(meaningful),
        "avg_size": (sum(meaningful) / len(meaningful)) if meaningful else 0.0,
        "largest": largest,
        "contiguity": (largest / total) if total else 0.0,
        "coverage": total / float(w * w),
    }


def _compute_metrics(grid, hsv, pixels, counts, analyzed, very_dark, sat_sum, val_sum, size):
    total = float(size * size)
    a = float(analyzed) or 1.0

    metrics = {
        "coverage": analyzed / total,
        "green": counts["green"] / a,
        "yellow": counts["yellow"] / a,
        "orange": counts["orange"] / a,
        "brown": counts["brown"] / a,
        "dark": counts["dark"] / a,
        "white": counts["white"] / a,
        "purple": counts["purple"] / a,
        "other": counts["other"] / a,
        "very_dark": very_dark / a,
        "saturation": sat_sum / a,
        "value": val_sum / a,
    }
    metrics["lesion"] = metrics["brown"] + metrics["dark"] + metrics["orange"] + metrics["purple"]
    metrics["chlorosis"] = metrics["yellow"]

    # yellow halo: chorotic pixels touching a lesion pixel
    yellow_adjacent = 0
    yellow_total = 0
    for j in range(size):
        for i in range(size):
            idx = j * size + i
            if grid[idx] != "yellow":
                continue
            yellow_total += 1
            found = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = i + dx, j + dy
                    if 0 <= nx < size and 0 <= ny < size:
                        if grid[ny * size + nx] in ("brown", "dark", "orange", "purple"):
                            found = True
                            break
                if found:
                    break
            if found:
                yellow_adjacent += 1
    metrics["halo_index"] = (yellow_adjacent / yellow_total) if yellow_total else 0.0

    # margin vs centre yellowing
    band = max(2, int(size * 0.18))
    border_y = border_n = centre_y = centre_n = 0
    for j in range(size):
        for i in range(size):
            edge = i < band or j < band or i >= size - band or j >= size - band
            is_yellow = grid[j * size + i] == "yellow"
            if edge:
                border_n += 1
                border_y += 1 if is_yellow else 0
            else:
                centre_n += 1
                centre_y += 1 if is_yellow else 0
    border_rate = (border_y / border_n) if border_n else 0.0
    centre_rate = (centre_y / centre_n) if centre_n else 0.0
    metrics["margin_ratio"] = (border_rate + 0.005) / (centre_rate + 0.005)

    # mottle: variation of "greenness" within the green tissue only. A leaf with
    # separate yellow/brown lesions is not mottled; a mosaic leaf is.
    greenness = []
    lesion_values = []
    for i in range(size * size):
        cls = grid[i]
        if cls == "green":
            r, g, b = pixels[i]
            greenness.append(g - (r + b) / 2.0)
        elif cls in ("brown", "dark", "orange", "purple"):
            lesion_values.append(hsv[i][2])

    if len(greenness) > 40:
        mean = sum(greenness) / len(greenness)
        var = sum((x - mean) ** 2 for x in greenness) / len(greenness)
        metrics["mottle_index"] = min(1.0, math.sqrt(var) / 34.0)
    else:
        metrics["mottle_index"] = 0.0

    if len(lesion_values) > 30:
        mean = sum(lesion_values) / len(lesion_values)
        var = sum((x - mean) ** 2 for x in lesion_values) / len(lesion_values)
        metrics["ring_index"] = min(1.0, math.sqrt(var) / 0.16)
    else:
        metrics["ring_index"] = 0.0

    # silhouette fill ratio (a crude curl/crumple proxy)
    xs = [i % size for i in range(size * size) if grid[i] != "background"]
    ys = [i // size for i in range(size * size) if grid[i] != "background"]
    if xs:
        bw = max(xs) - min(xs) + 1
        bh = max(ys) - min(ys) + 1
        metrics["fill_ratio"] = analyzed / float(max(1, bw * bh))
    else:
        metrics["fill_ratio"] = 0.0

    # very dark spots restricted to small blobs (black specks)
    metrics["dark_share"] = (counts["dark"] / a) if a else 0.0
    return metrics


def _texture_metrics(rgb_image, size=200):
    img = rgb_image.convert("L").resize((size, size), Image.LANCZOS)
    blurred = img.filter(ImageFilter.GaussianBlur(1.6))
    diff = ImageChops.difference(img, blurred)
    stat = ImageStat.Stat(diff)
    sharpness = stat.mean[0]

    # edge density from a simple gradient
    px = list(img.getdata())
    strong = 0
    pairs = 0
    for j in range(0, size, 2):
        row = j * size
        for i in range(0, size - 2, 2):
            a = px[row + i]
            b = px[row + i + 2]
            pairs += 1
            if abs(a - b) > 28:
                strong += 1
    return {"sharpness": sharpness, "edge_density": (strong / pairs) if pairs else 0.0}


# --------------------------------------------------------------------------- scoring

def _tag_scores(metrics, blobs, texture):
    m = metrics
    spot_count = blobs["count"]
    blob_size = blobs["avg_size"]
    contiguity = blobs["contiguity"]

    tags = {}
    tags["healthy_green"] = (0.55 * _ramp(m["green"], 0.55, 0.85)
                             * (1 - _ramp(m["lesion"], 0.03, 0.18))
                             * (1 - _ramp(m["chlorosis"], 0.08, 0.30)))
    tags["orange_pustules"] = (_ramp(m["orange"], 0.012, 0.09)
                               * (1 - _ramp(blob_size, 8, 45))
                               * _ramp(m["green"] + m["orange"] + m["yellow"], 0.25, 0.7)
                               * _ramp(spot_count, 2, 45))
    tags["yellow_pustules"] = (_ramp(m["orange"] * 0.6 + m["yellow"] * 0.4, 0.02, 0.16)
                               * _ramp(spot_count, 2, 45)
                               * (1 - _ramp(blob_size, 10, 50)))
    tags["white_powder"] = (_ramp(m["white"], 0.05, 0.32)
                            * (1 - _ramp(m["dark"], 0.05, 0.28)))
    tags["gray_fuzz"] = (_ramp(m["white"], 0.04, 0.28)
                         * _ramp(m["lesion"], 0.015, 0.25)
                         * (1 - _ramp(m["orange"], 0.02, 0.14)))
    pale = m["white"] * 0.6 + m["yellow"] * 0.4
    tags["gray_center_brown_margin"] = (_ramp(m["brown"], 0.02, 0.22)
                                        * _ramp(spot_count, 2, 55)
                                        * (1 - _ramp(blob_size, 14, 60))
                                        * _ramp(pale, 0.02, 0.28))
    tags["concentric_rings"] = (_ramp(m["brown"], 0.025, 0.20)
                                * _ramp(m["ring_index"], 0.05, 0.34)
                                * _ramp(spot_count, 2, 40)
                                * (1 - _ramp(m["very_dark"], 0.05, 0.25)))
    tags["dark_water_soaked"] = (_ramp(m["dark"], 0.06, 0.38)
                                 * _ramp(contiguity, 0.30, 0.72)
                                 * (1 - _ramp(m["saturation"], 0.42, 0.70)))
    tags["dark_necrotic_spots"] = (_ramp(m["dark"], 0.02, 0.22)
                                   * _ramp(spot_count, 3, 50)
                                   * (1 - _ramp(blob_size, 28, 70)))
    tags["black_spots"] = _ramp(m["very_dark"], 0.015, 0.14) * _ramp(spot_count, 2, 35)
    tags["yellow_margin"] = _ramp(m["margin_ratio"], 1.25, 2.6) * _ramp(m["chlorosis"], 0.04, 0.28)
    tags["uniform_chlorosis"] = (_ramp(m["chlorosis"], 0.10, 0.48)
                                 * (1 - _ramp(spot_count, 10, 45))
                                 * (1 - _ramp(m["dark"], 0.05, 0.25)))
    tags["mosaic_mottle"] = (_ramp(m["mottle_index"], 0.09, 0.34)
                             * _ramp(m["green"] + m["chlorosis"], 0.30, 0.80)
                             * (1 - _ramp(m["dark"], 0.03, 0.20))
                             * (1 - _ramp(blob_size, 16, 60)))
    tags["vein_clearing"] = (0.7 * _ramp(m["green"], 0.30, 0.70)
                             * _ramp(m["chlorosis"], 0.06, 0.30)
                             * (1 - _ramp(spot_count, 12, 50)))
    tags["purple_blotch"] = _ramp(m["purple"], 0.008, 0.06) * _ramp(m["brown"] + m["purple"], 0.02, 0.24)
    tags["leaf_curl"] = 0.8 * _ramp(0.62 - m["fill_ratio"], 0.0, 0.16)
    tags["patchy_wilting"] = (_ramp(m["brown"], 0.12, 0.48)
                              * (1 - _ramp(m["green"], 0.15, 0.55))
                              * (1 - _ramp(spot_count, 18, 60)))
    tags["silvery_streaks"] = (0.85 * _ramp(m["white"], 0.03, 0.20)
                               * _ramp(texture["edge_density"], 0.06, 0.24)
                               * (1 - _ramp(spot_count, 20, 60)))
    tags["yellow_halo_spots"] = (_ramp(m["brown"] + m["dark"], 0.012, 0.16)
                                 * _ramp(m["halo_index"], 0.04, 0.34)
                                 * _ramp(spot_count, 1, 40))

    return {k: round(_clamp(v), 3) for k, v in tags.items()}


def _apply_symptoms(tags, symptoms):
    for symptom in symptoms or []:
        boosts = SYMPTOM_BOOSTS.get(symptom)
        if not boosts:
            continue
        for tag, amount in boosts.items():
            tags[tag] = round(_boost(tags.get(tag, 0.0), amount), 3)
    if "healthy" in (symptoms or []):
        for tag in ("orange_pustules", "dark_necrotic_spots", "gray_center_brown_margin",
                    "concentric_rings", "dark_water_soaked", "patchy_wilting", "purple_blotch",
                    "black_spots", "yellow_halo_spots", "white_powder"):
            tags[tag] = round(tags.get(tag, 0.0) * 0.35, 3)
    return tags


# --------------------------------------------------------------------------- matching

def _severity_from_lesion(lesion_pct):
    if lesion_pct is None:
        return {"level": "unknown", "label": "Cannot assess"}
    if lesion_pct < 2:
        return {"level": "none", "label": "Essentially clean"}
    if lesion_pct < 8:
        return {"level": "low", "label": "Light infection"}
    if lesion_pct < 20:
        return {"level": "moderate", "label": "Moderate infection"}
    if lesion_pct < 40:
        return {"level": "high", "label": "Heavy infection"}
    return {"level": "severe", "label": "Severe infection"}


def _match(tags, crop_id, top_n=4):
    candidates = data_store.diseases_for_crop(crop_id)
    if not candidates:
        candidates = data_store.diseases()

    scored = []
    for item in candidates:
        sigs = item.get("visual_signatures") or []
        if not sigs:
            continue
        vals = [tags.get(s, 0.0) for s in sigs]
        mean = sum(vals) / len(vals)
        peak = max(vals)
        score = 0.55 * mean + 0.45 * peak
        if item.get("severity") == "high":
            score += 0.02
        # light concave curve so a clear winner reads as a useful percentage
        score = score ** 0.75
        scored.append((score, mean, peak, item))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, mean, peak, item in scored[:top_n]:
        mgmt = item.get("management", {})
        results.append({
            "id": item["id"],
            "name": item["name"],
            "pathogen_type": item.get("pathogen_type", ""),
            "pathogen": item.get("pathogen", ""),
            "crops": item.get("crops", []),
            "severity": item.get("severity", "medium"),
            "overview": item.get("overview", ""),
            "match_pct": int(round(_clamp(score, 0, 1) * 100)),
            "matched_signatures": [{"tag": s, "label": TAG_LABELS.get(s, s), "score": int(tags.get(s, 0) * 100)}
                                   for s in (item.get("visual_signatures") or [])],
            "look_alike": item.get("look_alike", []),
            "actions": {
                "cultural": (mgmt.get("cultural") or [])[:3],
                "organic": (mgmt.get("organic") or [])[:3],
                "chemical": (mgmt.get("chemical") or [])[:2],
                "prevention": (item.get("prevention") or [])[:2],
            },
            "image_cues": item.get("image_cues", ""),
        })
    return results


def _pseudo_matches(tags, top_n, metrics=None):
    """Disorder / healthy entries that are not in the disease catalogue."""
    out = []
    if tags.get("healthy_green", 0) >= 0.35:
        out.append({
            "id": "healthy",
            "name": "No clear disease signature",
            "pathogen_type": "Assessment",
            "pathogen": "-",
            "crops": [],
            "severity": "low",
            "overview": "The leaf looks predominantly healthy and uniformly green with little "
                        "necrotic or chlorotic tissue. Keep scouting weekly - early detection is "
                        "far cheaper than late treatment.",
            "match_pct": int(round(tags["healthy_green"] * 100)),
            "matched_signatures": [{"tag": "healthy_green", "label": TAG_LABELS["healthy_green"],
                                    "score": int(tags["healthy_green"] * 100)}],
            "look_alike": [],
            "actions": {
                "cultural": ["Continue weekly scouting, especially on the lower leaf surface.",
                             "Keep the crop well nourished and avoid excess nitrogen."],
                "organic": ["Maintain bio-fungicide cover in humid spells on susceptible crops."],
                "chemical": [],
                "prevention": ["Rotate crops and remove crop residue after harvest."],
            },
            "image_cues": "",
        })
    mottle = (metrics or {}).get("mottle_index", 0.0)
    if tags.get("uniform_chlorosis", 0) >= 0.4 and mottle < 0.40:
        out.append({
            "id": "nutrient-deficiency",
            "name": "Possible nutrient deficiency (chlorosis)",
            "pathogen_type": "Disorder",
            "pathogen": "-",
            "crops": [],
            "severity": "medium",
            "overview": "Widespread, fairly even yellowing without distinct spots or lesions usually "
                        "points to a nutrient problem rather than a pathogen. Nitrogen deficiency "
                        "starts on older lower leaves; iron and zinc deficiency on the younger leaves.",
            "match_pct": int(round(tags["uniform_chlorosis"] * 100)),
            "matched_signatures": [{"tag": "uniform_chlorosis", "label": TAG_LABELS["uniform_chlorosis"],
                                    "score": int(tags["uniform_chlorosis"] * 100)}],
            "look_alike": ["Viral yellows", "Waterlogging-induced yellowing"],
            "actions": {
                "cultural": ["Check whether yellowing starts on old leaves (nitrogen) or young leaves "
                             "(iron/zinc/magnesium).",
                             "Get a soil test before applying fertiliser.",
                             "Check the field for waterlogging, which also causes yellowing."],
                "organic": ["Apply well-decomposed compost or a foliar seaweed extract."],
                "chemical": ["Correct the specific deficiency with a soil or foliar application "
                             "(urea 2% for nitrogen, zinc sulphate 0.5% for zinc, ferrous sulphate 0.5% for iron)."],
                "prevention": ["Follow soil-test-based fertiliser recommendations."],
            },
            "image_cues": "",
        })
    return out[:top_n]


# --------------------------------------------------------------------------- main entry

def analyze(image_bytes, crop_id=None, symptoms=None, filename=""):
    result = {
        "ok": False,
        "mode": "image" if image_bytes else "symptoms",
        "crop_id": crop_id,
        "image": {},
        "metrics": {},
        "tags": [],
        "matches": [],
        "quality_flags": [],
        "severity": {"level": "unknown", "label": "Cannot assess", "lesion_pct": None},
        "assessment": "",
        "disclaimer": (
            "This is an offline, explainable image heuristic, not a laboratory diagnosis. "
            "Always confirm with your local agriculture extension officer before applying "
            "any pesticide."
        ),
    }

    symptoms = symptoms or []
    tags = {}
    metrics = {}
    lesion_pct = None

    if image_bytes:
        try:
            raw = Image.open(io.BytesIO(image_bytes))
            raw = ImageOps.exif_transpose(raw)
            rgb = raw.convert("RGB")
        except Exception:
            result["quality_flags"].append("The uploaded file could not be read as an image.")
            return result

        width, height = rgb.size
        if min(width, height) < 120:
            result["quality_flags"].append("The image is quite small; use a close-up of at least "
                                           "500 x 500 pixels for a reliable reading.")

        grid, hsv, pixels, counts, analyzed, very_dark, sat_sum, val_sum, size = _analyze_pixels(rgb)
        blobs = _blobs(grid, size)
        metrics = _compute_metrics(grid, hsv, pixels, counts, analyzed, very_dark, sat_sum, val_sum, size)
        texture = _texture_metrics(rgb)
        metrics.update(texture)

        if metrics["coverage"] < 0.25:
            result["quality_flags"].append("Only a small part of the image looks like plant tissue. "
                                           "Fill the frame with a single leaf against a plain background.")
        if texture["sharpness"] < 2.2:
            result["quality_flags"].append("The image looks soft or out of focus; a sharper photo "
                                           "will give a more reliable result.")

        tags = _tag_scores(metrics, blobs, texture)
        lesion_pct = round(metrics["lesion"] * 100, 1)

        result["image"] = {
            "width": width,
            "height": height,
            "filename": filename,
            "leaf_coverage_pct": round(metrics["coverage"] * 100, 1),
            "sharpness": round(texture["sharpness"], 2),
            "spot_count": blobs["count"],
            "average_spot_size_pct": round(blobs["avg_size"], 2),
        }
        result["metrics"] = {
            "healthy_green_pct": round(metrics["green"] * 100, 1),
            "chlorosis_pct": round(metrics["chlorosis"] * 100, 1),
            "lesion_pct": lesion_pct,
            "necrosis_pct": round(metrics["dark"] * 100, 1),
            "rust_pct": round(metrics["orange"] * 100, 1),
            "white_powder_pct": round(metrics["white"] * 100, 1),
            "purple_pct": round(metrics["purple"] * 100, 1),
            "mottle_index": round(metrics["mottle_index"] * 100, 1),
            "ring_index": round(metrics["ring_index"] * 100, 1),
            "yellow_margin_ratio": round(metrics["margin_ratio"], 2),
            "edge_density": round(texture["edge_density"] * 100, 1),
        }
    else:
        tags = {k: 0.0 for k in TAG_LABELS}

    tags = _apply_symptoms(tags, symptoms)
    tags = {k: round(_clamp(v), 3) for k, v in tags.items()}

    matches = _match(tags, crop_id, top_n=4)
    pseudo = _pseudo_matches(tags, top_n=2, metrics=metrics)

    # merge pseudo matches into the ranked list by score
    combined = matches + pseudo
    combined.sort(key=lambda m: -m["match_pct"])
    combined = combined[:4]

    result["tags"] = sorted(
        [{"tag": k, "label": TAG_LABELS.get(k, k), "score": int(v * 100)}
         for k, v in tags.items() if v > 0.08],
        key=lambda t: -t["score"],
    )
    result["matches"] = combined
    result["severity"] = {**_severity_from_lesion(lesion_pct), "lesion_pct": lesion_pct}

    top = combined[0] if combined else None
    if not image_bytes and not symptoms:
        result["assessment"] = ("Upload a leaf photo or tick a few visible symptoms to get an "
                                "assessment.")
        result["quality_flags"].append("No image and no symptoms were provided.")
        return result

    if top:
        if image_bytes:
            result["assessment"] = (
                f"Closest match: {top['name']} ({top['match_pct']}% signature match). "
                f"About {lesion_pct}% of the analysed leaf area shows necrotic or rusted tissue."
            )
        else:
            result["assessment"] = (
                f"Based on the symptoms you selected, the closest match is {top['name']} "
                f"({top['match_pct']}% symptom match)."
            )
        if len(combined) > 1 and combined[1]["match_pct"] >= top["match_pct"] - 12:
            result["assessment"] += (f" Note: {combined[1]['name']} is a close second, so confirm "
                                     "by checking the field symptoms listed below.")
    result["ok"] = True
    return result


def symptom_options():
    cleaned = []
    for opt in SYMPTOM_OPTIONS:
        if opt["id"] in SYMPTOM_BOOSTS:
            cleaned.append({"id": opt["id"], "label": opt["label"]})
    return cleaned


def tag_reference():
    return [{"tag": k, "label": v} for k, v in TAG_LABELS.items()]
