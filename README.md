# 🌱 AgriSense — Intelligent Farming Assistant

AgriSense is a local web application that turns agricultural knowledge and live
weather into practical, day-to-day decisions for farmers and field advisers:

- **Crop guide** — sowing windows, soil and climate needs, a stage-by-stage
  fertiliser schedule, irrigation guidance, common pests and the diseases to
  watch, for 16 major crops.
- **Weather advisory** — a live 7-day forecast translated into actions: alerts,
  spray windows, a fungal/bacterial disease-pressure index and a day-by-day
  action plan.
- **Irrigation planner** — a FAO-56 style soil-water balance that tells you how
  much water to apply, when, and the volume for your field.
- **Disease centre** — a searchable catalogue of 47 diseases plus an **offline**
  leaf-photo analyzer (with an optional symptom questionnaire) that ranks the
  most likely problems and explains *why*.
- **Tips & season** — a month-by-month field calendar and 26 practical farming
  tips.

The whole app runs locally with a single command and needs no API keys. It works
fully offline: the weather layer falls back to a clearly-labelled climatological
estimate, and disease analysis runs on the server.

---

## Tech stack

| Layer     | Choice                                             |
|-----------|----------------------------------------------------|
| Backend   | Python + Flask (JSON API)                          |
| Frontend  | Vanilla HTML / CSS / JavaScript (single page app)  |
| Imaging   | Pillow (pure-Python heuristics, no ML model)       |
| Weather   | Open-Meteo (geocoding + forecast, no API key)      |
| Data      | JSON knowledge base in `data/`                     |

No build step, no database, no Node.js required.

---

## Quick start

```bash
# 1. (optional but recommended) create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

Requires Python 3.8+ and internet access only for live weather (everything else
works offline).

---

## Project structure

```
Agrisense/
├── app.py                 # Flask app: page + all JSON API routes
├── requirements.txt
├── README.md
├── data/                  # knowledge base (plain JSON, easy to extend)
│   ├── crops.json         # 16 crops
│   ├── diseases.json      # 47 diseases
│   ├── seasonal.json      # 12-month field calendar
│   └── tips.json          # 26 farming tips
├── modules/
│   ├── data_store.py      # loads/indexes the JSON knowledge base
│   ├── weather.py         # Open-Meteo client, normalisation, offline fallback
│   ├── advisory.py        # forecast -> alerts, spray windows, risk, action plan
│   ├── irrigation.py      # FAO-56 soil-water balance planner
│   ├── disease.py         # offline image analyzer + symptom matcher
│   └── seasonal.py        # month/season logic and tip filtering
├── templates/
│   └── index.html         # single-page app shell (six views)
└── static/
    ├── css/style.css      # theme and responsive layout
    └── js/app.js          # all front-end logic and rendering
```

---

## The six views

1. **Dashboard** — knowledge-base stats, the current season's focus, quick
   actions and highlighted tips.
2. **Crop Guide** — search/filter the 16 crops; open a crop for an overview,
   care & fertiliser schedule, irrigation guidance and disease list.
3. **Weather Advisory** — search any place (or use your location), pick a crop
   and growth stage, and get current conditions, a 7-day strip, a
   working-conditions score, alerts, spray windows, disease-pressure bars, the
   weekly water balance, the next 48 hours and a day-by-day action plan.
4. **Irrigation Planner** — enter crop, stage, soil, method, area and rainfall,
   or pull values straight from the last weather lookup, and get a depth,
   interval and volume plus a 10-day moisture schedule.
5. **Disease Centre** — run the offline photo/symptom diagnosis, or browse and
   search the full disease catalogue.
6. **Tips & Season** — a clickable month-by-month calendar plus filterable tips.

---

## API reference

All endpoints return JSON. Successful responses include `"ok": true`; errors
include `"ok": false` and `"error": "<message>"`.

| Method | Endpoint                     | Key parameters                                   |
|--------|------------------------------|--------------------------------------------------|
| GET    | `/api/health`                | –                                                |
| GET    | `/api/overview`              | –                                                |
| GET    | `/api/crops`                 | `q`, `category`                                  |
| GET    | `/api/crops/<crop_id>`       | –                                                |
| GET    | `/api/diseases`              | `q`, `crop`, `type`                              |
| GET    | `/api/diseases/<disease_id>` | –                                                |
| GET    | `/api/disease/meta`          | – (crops, pathogen types, symptom options, tags) |
| POST   | `/api/diagnose`              | multipart: `image` (file), `crop_id`, `symptoms` |
| GET    | `/api/locations`             | `q` (place search / geocoding)                   |
| GET    | `/api/weather`               | `location` **or** `lat`,`lon`,`label`; `crop`, `stage` |
| GET    | `/api/irrigation/options`    | –                                                |
| POST   | `/api/irrigation`            | JSON body (see below)                            |
| GET    | `/api/seasonal`              | `month` (1–12, optional)                         |
| GET    | `/api/tips`                  | `category`, `q`, `limit`                         |

Example irrigation request:

```json
POST /api/irrigation
{
  "crop_id": "wheat",
  "stage": "flowering",
  "soil_type": "loam",
  "method": "sprinkler",
  "area": 1,
  "area_unit": "acre",
  "et0": 4.0,
  "rain_forecast_mm": 5,
  "rain_recent_mm": 2,
  "last_irrigation_days_ago": 5,
  "horizon_days": 7
}
```

---

## How the disease analyzer works

The image analysis is deliberately **explainable and offline** — there is no
neural network and nothing is downloaded. It never sends your photo anywhere.

1. The photo is decoded with Pillow and resized for speed.
2. Each pixel is classified in HSV space (healthy green, chlorosis, necrosis,
   rust/orange, white powdery growth, dark/black tissue, etc.).
3. Flat, sky-like pixels connected to the image border are flood-filled away as
   background, so *interior* white mildew is not mistaken for background.
4. Blob and adjacency analysis measures spots, blotches, rings, mottling and
   texture, producing **19 visual-signature scores** (e.g. "concentric rings",
   "yellow halo spots", "white powdery surface growth").
5. If you also tick symptoms, each symptom adds a probabilistic boost.
6. Every disease in the catalogue declares a set of `visual_signatures`; the
   analyzer scores each candidate against the detected evidence and returns a
   ranked list with the **signals that contributed** and a management plan.

You can use it with **an image only**, **symptoms only**, or both (best). It is a
decision-support aid, not a lab test.

## How irrigation is estimated

A FAO-56 style water balance:

```
crop water use      ETc   = Kc × ET₀
net irrigation need       = ETc − effective rainfall
readily available water   = p × TAW   (limits how much the soil can hold)
gross depth               = net depth ÷ application efficiency
```

Soil type, growth stage, irrigation method (efficiency) and recent/forecast rain
all feed the calculation. The planner also grows a 10-day root-zone moisture
schedule and explains its assumptions.

## Weather source and offline fallback

Live data comes from [Open-Meteo](https://open-meteo.com/) (free, no API key).
If the network is unavailable, AgriSense falls back to a **climatological
estimate** for the location and month. Those results are always labelled as
estimates in the interface, so they are never confused with a real forecast.

---

## Extending the knowledge base

`data/*.json` is plain and editable. Add a crop, disease, month or tip by
following the existing shape (unique `id`, and diseases reference crops through
`crop_ids`). `modules/data_store.py` loads and indexes everything at startup, so
no code changes are needed for new entries.

---

## Tests

The project ships with self-checks used during development (run from the project
folder):

```bash
# backend: data loading, irrigation maths, advisory rules, image analyzer
python <path-to>/agrisense_test.py

# HTTP: every API route and the exact JSON shape the front end expects
python <path-to>/agrisense_http_test.py
```

(These scripts live outside the repository in the development workspace; the app
itself has no test dependencies.)

---

## Limitations & disclaimer

- Disease diagnosis is a **heuristic image/symptom matcher**, not a certified
  diagnostic. Always confirm with your local agricultural extension service.
- Weather advisories and irrigation numbers are **guidance**, built from
  forecasts and standard crop coefficients. Confirm against field observations.
- Where any chemical control is mentioned, **always read and follow the product
  label**, confirm it is registered for that crop and pest in your area, and
  respect the pre-harvest interval and safety precautions.
- The development server (`python app.py`) is for local use. For a real
  deployment, run behind a production WSGI server.

## Credits

- Weather and geocoding: [Open-Meteo](https://open-meteo.com/).
- Crop water-use method: FAO Irrigation & Drainage Paper 56 (ET₀ / Kc approach).
- Built with Flask and Pillow.
