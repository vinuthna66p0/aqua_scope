# MarineGuard AI — Oil Spill Intelligence & Decision Support System
### SIH26143 — Leveraging Satellite Imagery to Determine Oil Spills at Sea, with AIS Correlation to Identify the Responsible Vessel

> ⚠ **This is a functional prototype built entirely on SYNTHETIC data.**
> It demonstrates a complete, working, interactive decision-support workflow.
> It is **not** connected to live satellites, real AIS feeds, or real environmental
> data, and it makes no claim of real-world detection accuracy.

---

## 1. Problem Statement

Oil spills at sea cause severe ecological and economic damage. Individually,
SAR-based oil-spill detection, optical (EO) validation, drift/trajectory
modelling and AIS vessel-tracking are all mature, well-established
capabilities. What is missing in most public demonstrations is a **single
integrated, interactive workflow** that takes a raw multi-sensor detection
all the way through to an investigative, decision-ready output — with
visible uncertainty, environmental sensitivity, and closed-loop correction.

## 2. Proposed Solution / Differentiation

MarineGuard AI does **not** claim to invent SAR, EO, AIS correlation or
trajectory modelling. Its contribution is the **integration**:

1. SAR candidate detection + explicit, explainable look-alike rejection
2. EO evidence as a secondary validation layer (not a replacement for SAR)
3. Multiple simultaneous slicks handled independently, end-to-end
4. Spill-time window estimation (not a false single "exact" timestamp)
5. Backward trajectory reconstruction to a probable origin + time window
6. AIS candidate ranking tied explicitly to that reconstructed origin/time
7. Unmatched/dark-vessel investigation flag
8. 10-hour forward prediction with visible, growing uncertainty
9. An interactive Environment Simulator that actually recalculates the path
10. A closed self-correction loop: predicted vs. observed vs. corrected
11. Sensitive-zone impact assessment with response prioritization
12. One unified interactive dashboard tying all of the above together

## 3. Complete Workflow

```
SAR + EO + Location + Time + Wind + Current + Wave/Tide + Historical AIS
        ↓ preprocessing
   SAR Detection → Candidate Slicks → Look-alike Filtering → EO Validation
        ↓
   Multi-sensor Evidence Fusion → Likely Oil / Uncertain / Likely Look-alike
        ↓
   Slick Characterization → Spill Time Estimation → Backward Trajectory
        ↓
   Historical AIS Correlation → Candidate Vessel Ranking
        ↓
   10-Hour Forward Trajectory (wind + current + wave/tide forcing)
        ↓
   Dynamic Map Visualization ⇄ Environmental Change Simulator ⇄ Recalculation
        ↓
   New Satellite Observation → Predicted vs Observed → Error → Correction
        ↓
   Updated Trajectory → Impact / Sensitive-Zone Assessment → Response Priority
        ↓
   Final Decision-Support Dashboard
```

## 4. Architecture

```
oilspill/
├── backend/
│   └── app/
│       ├── main.py              FastAPI app + all REST endpoints
│       ├── models.py            SQLAlchemy models (SQLite)
│       ├── data_generator.py    builds the 8 synthetic demo cases
│       ├── detection.py         SAR candidate classifier (RandomForest, synthetic features)
│       ├── fusion.py            explainable multi-sensor evidence fusion
│       ├── trajectory.py        forward/backward drift model, uncertainty, correction
│       ├── ais_correlation.py   AIS candidate vessel ranking
│       ├── impact.py            sensitive-zone impact assessment
│       └── geo_utils.py         haversine / bearing / destination-point helpers
├── frontend/
│   ├── index.html               dashboard layout
│   ├── style.css                dark dashboard theme
│   └── app.js                   wires the UI to the REST API, Leaflet map, tables
├── requirements.txt
├── run.sh                       one-command launcher
└── README.md
```

FastAPI serves both the JSON API (`/api/...`) **and** the static frontend
(`/`), so a single process is all you need to run the whole prototype.

## 5. Technology Stack

- **Backend:** Python, FastAPI, Uvicorn
- **Data / ML:** NumPy, SciPy, scikit-learn (RandomForestClassifier), OpenCV, Pillow
- **Database:** SQLite via SQLAlchemy
- **Frontend:** HTML, CSS, vanilla JavaScript, Leaflet.js (map)

## 6. Dataset Structure

Each synthetic **case** has: a location, acquisition date, and one shared
environment snapshot (wind, current, wave height, sea-surface temperature).
Each case contains one or more **slicks**, each carrying: geometry, SAR/EO
classification + confidence, an explainable fusion score, a spill-time
timeline, a reconstructed origin, a 10-hour forward trajectory with
hour-by-hour uncertainty, self-correction state, ranked AIS candidates, and
a sensitive-zone impact assessment. Each case also carries a small AIS
vessel fleet (with realistic-looking tracks) and 1-2 synthetic sensitive
zones (mangroves / coral reefs / fishing grounds / protected marine areas /
water-intake stations). See `backend/app/models.py` for the full schema.

## 7. How Each Module Works (Synthetic Prototype Behaviour)

- **SAR detection / look-alike filtering (`detection.py`):** A
  `RandomForestClassifier` is trained at startup on a synthetic, labelled
  feature set (contrast, edge sharpness, elongation, texture variance,
  size, wind context, proximity to shipping lanes) representing "oil-like"
  vs "look-alike" dark regions. Each generated slick's features are scored
  by this model to produce a SAR confidence and, for rejected candidates, a
  plain-language look-alike reason.
- **EO validation (`fusion.py` inputs):** Each slick carries a synthetic EO
  evidence label (Supporting / Conflicting / Unavailable) and confidence,
  generated alongside the case — standing in for a real optical cross-check.
- **Multi-sensor fusion (`fusion.py`):** A transparent, hand-set weighted sum
  (SAR 40%, EO 25%, shape/texture 15%, environment 10%, temporal 10%)
  produces the final confidence and Likely Oil / Uncertain / Likely
  Look-alike classification. Conflicting EO evidence caps the maximum
  achievable confidence. The full per-component breakdown is shown in the
  dashboard's "Evidence Fusion" panel.
- **Spill-time estimation:** Last-clean / first-suspicious / detection
  timestamps are generated with a randomised detection delay (7–52 min) per
  slick, shown as a timeline.
- **Backward trajectory / origin (`trajectory.py`):** The same drift model
  used for forward prediction is run in reverse from the detection point to
  reconstruct a probable origin track and time window.
- **AIS ranking (`ais_correlation.py`):** Each vessel's track position
  nearest the reconstructed origin time is compared against the origin
  location, time window, and drift-consistent course, producing an
  explainable 0-100 candidate score (spatial 35%, temporal 30%, trajectory
  consistency 25%, behaviour 10%, with an AIS-gap penalty). Output is
  explicitly labelled as an investigative ranking, not proof of
  responsibility.
- **Dark-vessel flag:** Case 8 includes a SAR-detected object position with
  **no** corresponding AIS vessel, surfaced as an "Unmatched / Dark-Vessel
  Candidate" — without any accusation of wrongdoing.
- **10-hour forward prediction (`trajectory.py`):** Drift velocity =
  ocean current + 3% of wind speed (a standard simplified rule-of-thumb),
  stepped hourly with a small stochastic wobble for a light Monte-Carlo feel.
- **Uncertainty:** Grows roughly with √(hour), shown as a shaded corridor on
  the map and a column in the trajectory table. This is a modelled,
  clearly-labelled demonstration value, not a validated error budget.
- **Environmental Change Simulator:** The `/api/trajectory/recalculate`
  endpoint re-runs the same drift model with new wind/current parameters
  supplied from the dashboard sliders, and reports the deviation (km)
  between the old and new 10-hour forecast — a real recalculation, not a
  cosmetic redraw.
- **Self-correction:** `/api/observation/update` simulates a new satellite
  pass (perturbing the predicted position, or accepting a supplied one);
  `/api/trajectory/correct` computes the prediction error and applies a
  bias correction to every future trajectory point, updating the map.
- **Impact prioritization (`impact.py`):** Every trajectory point is checked
  against each sensitive zone's radius; the closest approach determines
  Intersects / Approaches / Remains-away status, estimated arrival hour,
  and a HIGH/MEDIUM/LOW response priority.

## 8. Case Demonstrations (8 synthetic cases)

| Case | Demonstrates |
|---|---|
| 01 | Single slick, normal conditions |
| 02 | Two independent, simultaneous slicks |
| 03 | Three slicks + a rejected look-alike (with an "Uncertain" slick too) |
| 04 | Trajectory highly sensitive to wind-direction change |
| 05 | Trajectory highly sensitive to ocean-current change |
| 06 | Self-correction: new observation vs. original prediction |
| 07 | Forecast trajectory intersects a protected marine zone (HIGH priority) |
| 08 | AIS gap + an unmatched/dark vessel near the reconstructed origin |

Selecting a different case in the dashboard reloads all satellite data,
slicks, environment, AIS vessels, trajectories and sensitive zones —
nothing is hardcoded per case in the frontend.

## 9. How to Run Locally

**Requirements:** Python 3.10+

```bash
cd oilspill
./run.sh
```

This creates a virtual environment, installs `requirements.txt`, and starts
the server. Then open:

```
http://localhost:8000
```

The SQLite database (`backend/oilspill.db`) is generated automatically on
first run. To force a full re-generation of the synthetic dataset, delete
`backend/oilspill.db` and restart, or call `POST /api/regenerate`.

### Manual start (alternative)
```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cd backend
../venv/bin/uvicorn app.main:app --reload --port 8000
```

## 10. API Reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/cases` | list all cases (summary) |
| GET | `/api/cases/{case_id}` | full case detail: slicks, vessels, zones |
| POST | `/api/analyze` `{case_id}` | run/refresh full analysis for a case |
| POST | `/api/cases/{case_id}/reset` | reset a case's trajectories/corrections |
| GET | `/api/detection/{slick_id}` | detection + fusion breakdown for one slick |
| GET | `/api/trajectory/{slick_id}` | forward + backward trajectory |
| POST | `/api/trajectory/recalculate` | recompute forward trajectory with new environment |
| POST | `/api/observation/update` | simulate a new satellite observation |
| POST | `/api/trajectory/correct` | apply observation-based correction |
| GET | `/api/ais/{slick_id}` | ranked AIS candidates + dark-vessel flags |
| GET | `/api/impact/{slick_id}` | sensitive-zone impact assessment |
| GET | `/api/event/{event_id}` | full record for one event |
| GET | `/api/metadata_table` | flat, sortable "Detection Metadata" table (all cases) |
| POST | `/api/regenerate` | regenerate the entire synthetic dataset |

## 11. How to Add a New Synthetic Case

Add a new block in `backend/app/data_generator.py::generate_all_cases()`
following the pattern used for `CASE_01`…`CASE_08`: create a `CaseRecord`,
build one or more slicks with `_build_slick(...)`, optional vessels with
`_make_vessel(...)`, a list of sensitive-zone dicts, then call
`_finalize_case(session, case, slicks, vessels, zones)`. Delete
`backend/oilspill.db` (or call `POST /api/regenerate`) to regenerate.

## 12. How Real Data Would Later Replace Synthetic Data

- **SAR/EO:** Replace `_make_features(...)` in `data_generator.py` with real
  feature extraction (OpenCV/scikit-image) from actual Sentinel-1 (SAR) and
  Sentinel-2 (EO) scenes, and retrain `detection.py`'s classifier on a
  labelled real/look-alike dataset instead of the synthetic training set.
- **Environmental data:** Replace the per-case fixed wind/current/wave
  values with a live feed (e.g. ECMWF/CMEMS) keyed by location and time.
- **AIS:** Replace `_make_vessel(...)`-generated tracks with a licensed
  historical/live AIS feed (e.g. via a maritime data provider), keeping the
  same `track` schema (`timestamp, latitude, longitude, speed, course`) so
  `ais_correlation.py` needs no changes.
- **Sensitive zones:** Replace the synthetic zone list with real protected
  area boundaries (e.g. WDPA / national marine-protected-area datasets).

The database schema, API contracts and frontend are already built to accept
these swaps without structural changes — only the data-generation layer
needs to be replaced with real data ingestion.

## 13. Limitations

- All satellite, environmental and AIS data in this prototype is
  **synthetic** and fabricated for demonstration; no real-world detection
  or navigation accuracy is claimed.
- The SAR/look-alike classifier is trained on synthetic features only, not
  on labelled real SAR imagery.
- The drift model is a simplified wind+current rule-of-thumb, not a
  validated oceanographic model (e.g. no true particle/Lagrangian
  simulation, no bathymetry, no weathering/evaporation of oil over time).
- Uncertainty values are illustrative (grow with √time), not a calibrated
  error budget.
- AIS candidate scores are **investigative rankings only** — they do not
  constitute legal proof of responsibility for a spill.
- Several nested structures (trajectory points, AIS candidate snapshots)
  are stored as JSON columns in SQLite rather than fully normalized tables,
  which is adequate for a prototype but would be normalized further for a
  production system.

## 14. Responsible Interpretation of Vessel Ranking

The AIS candidate list ranks vessels by spatial, temporal and trajectory
consistency with a *reconstructed, uncertain* origin — it is a starting
point for human investigation, not an automated accusation. The dashboard
and API responses carry this disclaimer wherever candidate scores appear.