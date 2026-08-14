# Emergency Routing System — End-to-End Project Documentation

> A real-time emergency medical routing platform that helps dispatchers and ambulance crews pick the **best hospital** for a patient based on the clinical requirements of the emergency, live hospital capacity, and travel time.

This document is the single source of truth for the project. It explains **what** the system does, **how** it is architected, **how to set it up**, **run it**, **test it**, and **extend it** — everything a new teammate needs to go from zero to productive.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [The Problem & The Solution](#2-the-problem--the-solution)
3. [System Architecture](#3-system-architecture)
4. [Directory Structure](#4-directory-structure)
5. [The Data Model (MongoDB Collections)](#5-the-data-model-mongodb-collections)
6. [The Decision Engine](#6-the-decision-engine)
7. [API Reference](#7-api-reference)
8. [WebSockets (Real-Time Layer)](#8-websockets-real-time-layer)
9. [Configuration & Environment Variables](#9-configuration--environment-variables)
10. [Setup Guide](#10-setup-guide)
11. [Running the System](#11-running-the-system)
12. [The End-to-End Workflow (Walkthrough)](#12-the-end-to-end-workflow-walkthrough)
13. [Seed Scripts & Demo Scenario](#13-seed-scripts--demo-scenario)
14. [Testing](#14-testing)
15. [Frontend Applications](#15-frontend-applications)
16. [Error Handling & Edge Cases](#16-error-handling--edge-cases)
17. [Known Limitations & Production Considerations](#17-known-limitations--production-considerations)
18. [FAQ / Troubleshooting](#18-faq--troubleshooting)

---

## 1. Project Overview

The **Emergency Routing System** (also referred to as "nearest_hospital" on disk) is a demo/full-stack application for routing emergency patients to the most suitable hospital. It is made up of **three components**:

| Component | Tech Stack | Purpose |
| --- | --- | --- |
| `emergency-routing-backend` | Python 3.10+, FastAPI, MongoDB (motor), Pydantic | The brain. Exposes the REST API, computes hospital recommendations, manages the case lifecycle, and pushes real-time alerts over WebSockets. |
| `ambulance-app` | React 18, Vite | The ambulance crew's interface. Captures the emergency details and vitals, shows the recommended destination, and lets the crew accept it. |
| `hospital-dashboard` | React 18, Vite | The hospital's interface. Lets staff push live capacity updates (ICU beds, department availability) and respond to incoming emergency alerts in real time. |

The system is **not** a real production medical system — it is a working reference implementation used for evaluation and development (see footer text in the dashboard: *"Demo tool for evaluation only — not production hospital software."*).

---

## 2. The Problem & The Solution

### The Problem

When an ambulance responds to an emergency, the crew must decide **where to take the patient**. The naive answer is "the nearest hospital", but that is often wrong:

- The nearest hospital may **lack the capability** for the emergency (e.g. no trauma center, no CT scanner for a stroke, no cath lab for a cardiac arrest).
- The hospital may be **full** (no ICU beds available) or not **accepting patients**.
- A slightly farther hospital might deliver the patient to **definitive care faster** once travel + waiting + readiness are all considered.

### The Solution

The system computes a **recommendation** for each case:

1. **Filter** hospitals by hard clinical requirements derived from the emergency type and severity.
2. **Eliminate** hospitals that are not accepting patients, have stale status, or lack the required capabilities/beds.
3. **Score** the surviving hospitals by **total care delay** = travel time (ETA) + expected wait at the emergency department + treatment readiness time.
4. **Recommend** the hospital with the lowest total care delay, and list all alternatives with their elimination reasons.

Then it **notifies** the chosen hospital in real time, and if the hospital **rejects** the alert, it **re-routes** the case to the next best hospital automatically.

---

## 3. System Architecture

```mermaid
graph TB
    subgraph Clients
        A[Ambulance App<br/>React + Vite :5173]
        D[Hospital Dashboard<br/>React + Vite :5174]
    end

    subgraph Backend
        B[FastAPI Server<br/>:8000]
        C[MongoDB<br/>emergency_routing]
        W[WebSocket Manager<br/>in-memory]
    end

    A -->|REST /api/v1| B
    D -->|REST /api/v1| B
    D -->|WS /ws/hospital/{id}| B
    A -->|WS /ws/ambulance/{id}| B
    B --> C
    B --> W
    W --> D
    W --> A
```

**Key design points:**

- **Async end-to-end.** FastAPI is fully async, and MongoDB is accessed through `motor` (`AsyncIOMotorClient`), so the event loop never blocks on database I/O.
- **Layered separation.** Models (Pydantic) → Routers (HTTP) → Services (business logic) → Core (config + DB connection).
- **Real-time alerting via WebSockets.** The `ConnectionManager` keeps track of live connections keyed by hospital/ambulance id. Alerts are pushed to hospitals; re-routing updates are pushed to ambulances.
- **Single-process WebSocket manager.** The connection manager is in-memory. This works for development/single instance but must be replaced with Redis pub/sub for multi-instance production (documented in [Section 17](#17-known-limitations--production-considerations)).

### Request/Response Flow (REST)

All REST routes live under `/api/v1` (except the healthcheck and WebSocket routes).

---

## 4. Directory Structure

```
nearest_hospital/
├── .gitignore
├── emergency-routing-backend/          # Python FastAPI backend
│   ├── .env.example                    # Copy to .env
│   ├── requirements.txt                # Python dependencies
│   ├── pytest.ini
│   ├── README.md                       # Backend-specific README
│   ├── app/
│   │   ├── main.py                     # FastAPI app factory, CORS, lifespan, healthcheck
│   │   ├── core/
│   │   │   ├── config.py               # pydantic-settings, reads .env
│   │   │   └── database.py             # motor client, get_db dependency, indexes
│   │   ├── models/                     # Pydantic models (Create + InDB per collection)
│   │   │   ├── location.py
│   │   │   ├── py_object_id.py
│   │   │   ├── hospital.py
│   │   │   ├── hospital_status.py
│   │   │   ├── ambulance.py
│   │   │   ├── emergency_case.py
│   │   │   └── recommendation.py
│   │   ├── routers/                    # HTTP endpoint definitions
│   │   │   ├── hospitals.py
│   │   │   ├── ambulances.py
│   │   │   ├── emergencies.py
│   │   │   ├── alerts.py
│   │   │   └── ws.py
│   │   └── services/                   # Business logic
│   │       ├── clinical_requirements.py
│   │       ├── eligibility_filter.py
│   │       ├── eta_service.py
│   │       ├── decision_engine.py
│   │       └── ws_manager.py
│   ├── scripts/
│   │   ├── check_db.py                 # DB connectivity verification
│   │   ├── seed_hospitals.py           # Seeds 15 hospitals around Hyderabad
│   │   ├── seed_ambulances.py          # Seeds 4 ambulances
│   │   └── demo_scenario.py            # Runs the Hospital A/B/C live demo
│   └── tests/
│       ├── test_clinical_requirements.py
│       ├── test_eligibility_filter.py
│       ├── test_eta_service.py
│       ├── test_decision_engine.py
│       ├── test_hospitals_api.py
│       ├── test_ambulances_api.py
│       ├── test_emergencies_api.py
│       ├── test_alerts_api.py
│       └── test_indexes.py
│
├── ambulance-app/                      # React + Vite frontend (crew)
│   ├── .env.example                    # VITE_API_BASE_URL
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                     # 3-step wizard UI
│       ├── api.js                      # fetch wrapper + base URL
│       └── styles.css
│
└── hospital-dashboard/                 # React + Vite frontend (hospital staff)
    ├── .env.example                    # VITE_API_BASE_URL, VITE_WS_URL
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx                     # Hospital select + status form + alert feed
        ├── api.js                      # fetch wrapper + WS URL helper
        └── styles.css
```

---

## 5. The Data Model (MongoDB Collections)

The application uses a single MongoDB database named `emergency_routing` (configurable via `DB_NAME`). It relies on **six collections**:

### `hospitals`
Static catalogue of hospitals.

| Field | Type | Notes |
| --- | --- | --- |
| `_id` | ObjectId | MongoDB id |
| `name` | string | e.g. "Apollo Hospitals, Jubilee Hills" |
| `location` | `{lat, lng}` | Geographic position |
| `capabilities` | object of booleans | `emergency`, `trauma`, `icu`, `cardiology`, `neurology`, `ct`, `cath_lab`, `blood_bank`, `surgery`, `pediatrics`, `obstetrics` |
| `created_at` | datetime | |

### `hospital_status`
Live capacity snapshot per hospital, upserted by the dashboard.

| Field | Type | Notes |
| --- | --- | --- |
| `hospital_id` | string | Links to `hospitals._id` (unique index) |
| `icu_available` / `icu_total` | int | ICU bed counts |
| `emergency_beds_available` / `emergency_beds_total` | int | Emergency bed counts |
| `trauma_status`, `cardiology_status`, `neurology_status`, `ct_status`, `cath_lab_status` | `"AVAILABLE"` \| `"UNAVAILABLE"` | Department availability |
| `accepting_patients` | bool | Overall intake gate |
| `updated_at` | datetime | Server-stamped on every upsert; used for staleness |

### `ambulances`
Fleet registry. ETA calculations need the ambulance's current location.

| Field | Type | Notes |
| --- | --- | --- |
| `ambulance_id` | string | Unique |
| `location` | `{lat, lng}` | Live location, updated via PATCH pings |
| `type` | `"BLS"` \| `"ALS"` | Basic vs Advanced Life Support |
| `status` | `"ACTIVE"` \| `"BUSY"` \| `"OFFLINE"` | Lifecycle state |

### `emergency_cases`
A single emergency incident.

| Field | Type | Notes |
| --- | --- | --- |
| `case_id` | string | Server-generated `case-<uuid4 hex>` (unique) |
| `emergency_type` | one of 8 literals | `TRAUMA`, `STROKE`, `CARDIAC`, `RESPIRATORY`, `BURN`, `PEDIATRIC`, `OBSTETRIC`, `GENERAL_CRITICAL` |
| `severity` | `"LOW"` \| `"MEDIUM"` \| `"HIGH"` | |
| `patient` | object | `{age, conscious, spo2, heart_rate, bp}` — all validated (see `PatientInfo`) |
| `ambulance_id` | string | Assigned ambulance |
| `status` | `"OPEN"` → `"RECOMMENDED"` → `"ACCEPTED"` → `"CLOSED"` | Lifecycle |
| `accepted_hospital_id` | string \| null | Set on accept |
| `created_at` | datetime | |

### `recommendations`
The stored output of the decision engine, one per case (unique on `case_id`, upserted on re-route).

| Field | Type | Notes |
| --- | --- | --- |
| `case_id` | string | Unique |
| `recommended_hospital_id` | string \| null | null when nothing is eligible |
| `eta_minutes` | float \| null | |
| `total_care_delay_minutes` | float \| null | |
| `reasons` | list[string] | Human-readable justification |
| `alternatives` | list of `{hospital_id, eliminated_reason?, total_care_delay_minutes?}` | Both eligible backups and eliminated hospitals |
| `no_eligible_hospital` | bool | |
| `created_at` | datetime | |

### `hospital_alerts`
Notifications sent to hospitals, with an embedded snapshot.

| Field | Type | Notes |
| --- | --- | --- |
| `case_id` | string | |
| `hospital_id` | string | |
| `status` | `"PENDING"` \| `"ACCEPTED"` \| `"REJECTED"` | |
| `snapshot` | object | `{patient, emergency_type, severity, required_capabilities, eta_minutes}` — a point-in-time copy |
| `created_at` | datetime | |

### Indexes

Created idempotently on app startup (`app/core/database.py:create_indexes`):

- `emergency_cases.case_id` — **unique**
- `recommendations.case_id` — **unique**
- `hospital_status.hospital_id` — **unique**
- `ambulances.ambulance_id` — **unique**
- `hospital_alerts` — compound `(case_id, hospital_id)`
- `hospital_alerts.status`

---

## 6. The Decision Engine

Located in `app/services/`. This is the heart of the system. It runs in three steps.

### Step 1 — Clinical Requirements (`clinical_requirements.py`)

`get_required_capabilities(emergency_type, severity)` returns a dict mapping capability → `True` (**hard required**) or `"preferred"` (**soft**).

| Emergency Type | Hard requirements | Severity-dependent |
| --- | --- | --- |
| `TRAUMA` | emergency, trauma, surgery, blood_bank | `icu` only at HIGH |
| `STROKE` | emergency, ct | `icu` at HIGH; `neurology` always preferred |
| `CARDIAC` | emergency, cardiology | `cath_lab` hard at MEDIUM/HIGH, preferred at LOW; `icu` at HIGH |
| `RESPIRATORY` | emergency | `icu` at HIGH |
| `BURN` | emergency, surgery | `icu` at HIGH |
| `PEDIATRIC` | emergency, pediatrics | `icu` at HIGH |
| `OBSTETRIC` | emergency, obstetrics | `surgery` always preferred; no ICU requirement |
| `GENERAL_CRITICAL` | emergency | `icu` at HIGH |

**Important nuance:** an `icu` value of `False` is *not* a requirement — it means ICU is *not* required. Only `True` values are treated as hard requirements. `"preferred"` values are informational (used to filter display in the dashboard) and never cause elimination.

### Step 2 — Eligibility Filter (`eligibility_filter.py`)

`filter_eligible_hospitals(hospitals, hospital_statuses, required_capabilities, now)` splits hospitals into `eligible` and `eliminated`. A hospital is eliminated if **any** of these hold (first match wins):

1. No `hospital_status` document → `"No hospital status available"`
2. `accepting_patients` is false → `"Hospital not accepting patients"`
3. Status is **stale** (`updated_at` older than `MAX_STATUS_AGE_SECONDS`) → `"Hospital status is stale"`
4. A hard-required capability flag is missing from `hospitals.capabilities` → `"<Capability> capability unavailable"`
5. Status shows the department/bed shortage:
   - `icu` required but `icu_available <= 0` → `"No ICU beds available"`
   - `trauma`/`cardiology`/`neurology`/`ct`/`cath_lab` required but status ≠ `"AVAILABLE"` → `"<Department> capability unavailable"`

### Step 3 — Scoring (`decision_engine.py`)

For every eligible hospital:

```
total_care_delay = eta_minutes + expected_wait_minutes + treatment_readiness_minutes
```

- **`eta_minutes`** — from the ETA service ([Section 7.3](#73-eta-service)).
- **`expected_wait_minutes`** — `estimate_wait_time(status, required_capabilities)`:
  - base `5.0` min
  - `+ 2.0 × occupied_fraction` where `occupied_fraction = 1 − (emergency_beds_available / emergency_beds_total)` (capped at 1)
  - `+ 5.0` if ICU is required and `icu_available == 0`
- **`treatment_readiness_minutes`** — `treatment_readiness_minutes(emergency_type)`: TRAUMA/CARDIAC = 3, STROKE = 4, everything else = 5.

The hospital with the **lowest total care delay** is the recommendation. All others appear in `alternatives` (eligible backups carry their delay; eliminated hospitals carry their reason). If no hospital survives the filter, the result has `no_eligible_hospital: True` and `recommended_hospital_id: null`.

---

## 7. API Reference

All REST endpoints are under `/api/v1`. The FastAPI app also auto-generates interactive docs at **http://localhost:8000/docs** (Swagger) and **http://localhost:8000/redoc**.

### 7.1 Hospitals — `/api/v1/hospitals`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/hospitals` | List hospitals. Optional `?lat=&lng=&radius_km=` filters to those within the radius (all three must be provided together, else `422`). |
| `GET` | `/hospitals/{hospital_id}` | Hospital details **plus** its current status (or `status: null`). |
| `GET` | `/hospitals/{hospital_id}/status` | Current status document (`404` if none). |
| `POST` | `/hospitals/{hospital_id}/status` | Upsert capacity status. Body = `HospitalStatusCreate`. Path id wins; `updated_at` is server-stamped. |

**Example — push status:**
```http
POST /api/v1/hospitals/6571a1a1a1a1a1a1a1a1a001/status
Content-Type: application/json

{
  "icu_available": 6,
  "icu_total": 10,
  "emergency_beds_available": 8,
  "emergency_beds_total": 8,
  "trauma_status": "AVAILABLE",
  "cardiology_status": "AVAILABLE",
  "neurology_status": "AVAILABLE",
  "ct_status": "AVAILABLE",
  "cath_lab_status": "AVAILABLE",
  "accepting_patients": true
}
```

### 7.2 Ambulances — `/api/v1/ambulances`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/ambulances` | List. Optional `?status=` and `?lat=&lng=&radius_km=` (radius requires all three). |
| `POST` | `/ambulances` | Register. Body = `{ambulance_id, location, type, status}`. `409` if id exists. |
| `GET` | `/ambulances/{ambulance_id}` | Fetch one. |
| `PATCH` | `/ambulances/{ambulance_id}` | Update `location` and/or `type` and/or `status`. **This is the GPS-ping endpoint** used by the ambulance app while en route. Requires at least one field. |

### 7.3 ETA Service (internal)

`app/services/eta_service.py` provides `get_eta(origin, destination)`:

- **Default (`ROUTING_PROVIDER=haversine`)**: straight-line (great-circle) distance via the haversine formula, divided by `AVG_URBAN_SPEED_KMH` (default 30 km/h). Returns `{distance_km, eta_minutes, source: "estimated"}`.
- **Optional (`ROUTING_PROVIDER=openrouteservice` + `ROUTING_API_KEY`)**: real road routing via OpenRouteService API. Returns `source: "routing_api"`. On any API failure it **degrades gracefully** back to the haversine estimate.

### 7.4 Emergencies & Recommendations — `/api/v1/emergencies`, `/api/v1/recommendations`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/emergencies` | Create a case. Body = `{emergency_type, severity, patient, ambulance_id}`. Server generates `case_id`, status `OPEN`. Returns `EmergencyCaseInDB`. |
| `GET` | `/emergencies/{case_id}` | Fetch a case. |
| `POST` | `/emergencies/{case_id}/recommend` | Run the decision engine. Stores the recommendation (upsert) and moves the case to `RECOMMENDED`. |
| `GET` | `/recommendations/{case_id}` | Fetch the stored recommendation. |
| `POST` | `/recommendations/{case_id}/accept` | Body `{"hospital_id": "..."}`. Moves case to `ACCEPTED`, records `accepted_hospital_id`, marks ambulance `BUSY`. The crew may pick any alternative, not just the top pick. |
| `POST` | `/emergencies/{case_id}/close` | Marks the case `CLOSED` and returns the ambulance to `ACTIVE`. |

**Example — create a case:**
```http
POST /api/v1/emergencies
Content-Type: application/json

{
  "emergency_type": "TRAUMA",
  "severity": "HIGH",
  "patient": {
    "age": 34,
    "conscious": false,
    "spo2": 91,
    "heart_rate": 118,
    "bp": "90/60"
  },
  "ambulance_id": "amb-001"
}
```

**Example — recommendation response:**
```json
{
  "case_id": "case-<hex>",
  "recommended_hospital_id": "6571...",
  "eta_minutes": 4.2,
  "total_care_delay_minutes": 14.2,
  "reasons": ["Required Trauma capability", "Required Surgery capability", "Required Blood bank capability", "ICU available", "ETA: 4 min", "Expected wait: 7 min", "Total care delay: 14 min"],
  "alternatives": [
    {"hospital_id": "6571...", "eliminated_reason": "No ICU beds available", "total_care_delay_minutes": null}
  ],
  "no_eligible_hospital": false,
  "created_at": "2026-08-14T..."
}
```

### 7.5 Hospital Alerts — `/api/v1/hospital-alerts`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/hospital-alerts` | Body `{"case_id", "hospital_id"}`. Creates a `PENDING` alert with a snapshot (patient, emergency type, required capabilities, ETA from stored recommendation) and **broadcasts it over WebSocket** to that hospital's channel. Also schedules a background auto-timeout. |
| `POST` | `/hospital-alerts/{alert_id}/accept` | Marks the alert `ACCEPTED`. |
| `POST` | `/hospital-alerts/{alert_id}/reject` | Marks the alert `REJECTED`, then **re-runs the decision engine excluding the rejected hospital**, stores a fresh recommendation, and **broadcasts it over WebSocket to the ambulance's channel**. |

**Auto-reject timeout:** a `PENDING` alert that gets no response within `ALERT_RESPONSE_TIMEOUT_SECONDS` (default 30 s) is automatically rejected and re-routed by a background task (`_alert_timeout` in `app/routers/alerts.py`).

### 7.6 Misc

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | `{"status": "ok", "database": "ok"\|"down"}` |
| `WS` | `/ws/hospital/{hospital_id}` | Hospital alert channel |
| `WS` | `/ws/ambulance/{ambulance_id}` | Ambulance re-routing channel |

---

## 8. WebSockets (Real-Time Layer)

The `ConnectionManager` (`app/services/ws_manager.py`) keeps an in-memory registry of open sockets keyed by `hospital_id` / `ambulance_id`.

- **Hospital channel** (`/ws/hospital/{id}`): the dashboard subscribes on dashboard open. When an alert is created, the server pushes the full alert document to that channel.
- **Ambulance channel** (`/ws/ambulance/{id}`): the ambulance crew subscribes. When a hospital rejects an alert, the server pushes the **new recommendation** to this channel so the crew sees the updated destination.
- **Keepalive:** the router runs `_keepalive_loop`, which sends a JSON `{"type": "ping"}` every `WS_KEEPALIVE_SECONDS` (default 30 s) if no message arrives, to keep idle connections from being dropped. Clients should ignore `type: "ping"` messages (both frontends do).

---

## 9. Configuration & Environment Variables

### Backend (`emergency-routing-backend/.env` — copy from `.env.example`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME` | `emergency_routing` | Database name |
| `PORT` | `8000` | Uvicorn port |
| `AVG_URBAN_SPEED_KMH` | `30.0` | Speed for haversine ETA fallback |
| `ROUTING_PROVIDER` | `haversine` | `haversine` or `openrouteservice` |
| `ROUTING_API_KEY` | *(empty)* | OpenRouteService API key |
| `ALERT_RESPONSE_TIMEOUT_SECONDS` | `30` | Auto-reject + re-route timeout |
| `MAX_STATUS_AGE_SECONDS` | `600` | Status older than this is stale/ineligible |
| `WS_KEEPALIVE_SECONDS` | `30` | WS ping interval |

### Ambulance App (`ambulance-app/.env`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend base URL |

### Hospital Dashboard (`hospital-dashboard/.env`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend REST base URL |
| `VITE_WS_URL` | `http://localhost:8000/ws` | WebSocket base URL (the app swaps `http`→`ws`) |

> **Never commit real `.env` files.** The repo ignores them; only `.env.example` files are committed.

---

## 10. Setup Guide

### Prerequisites

- **Python 3.10+** (backend was developed with 3.12)
- **Node.js 18+** and **npm** (for the two frontends)
- **MongoDB** running locally on `27017` — or a MongoDB Atlas connection string in `MONGO_URI`

> If you don't have MongoDB installed, the easiest path is MongoDB Community Server (local) or a free Atlas cluster. Alternatively, run MongoDB in Docker:
> `docker run -d -p 27017:27017 --name mongo mongo:7`

### 1. Backend

```bash
cd emergency-routing-backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
```

### 2. Frontends

```bash
cd ambulance-app
npm install
cp .env.example .env

cd ../hospital-dashboard
npm install
cp .env.example .env
```

---

## 11. Running the System

### 1. Start MongoDB (if not already running)

```bash
# via Docker
docker start mongo
```

### 2. Verify the database connection

```bash
cd emergency-routing-backend
python scripts/check_db.py
```

You should see `SUCCESS: MongoDB connection and basic read/write/delete all work.`

### 3. Start the backend

```bash
cd emergency-routing-backend
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health → `{"status":"ok","database":"ok"}`

### 4. Seed the database (once per fresh DB)

```bash
# From the activated venv, inside emergency-routing-backend
python scripts/seed_hospitals.py
python scripts/seed_ambulances.py
```

### 5. Start the frontends (each in its own terminal)

```bash
cd ambulance-app
npm run dev        # http://localhost:5173

cd ../hospital-dashboard
npm run dev        # http://localhost:5174
```

### Ports summary

| Service | URL |
| --- | --- |
| Backend API | `http://localhost:8000` |
| Swagger docs | `http://localhost:8000/docs` |
| Ambulance app | `http://localhost:5173` |
| Hospital dashboard | `http://localhost:5174` |

---

## 12. The End-to-End Workflow (Walkthrough)

Here is the complete journey of an emergency through the system, which also mirrors how you'd demo it manually:

### Phase 0 — Setup
1. Mongo is running, backend is up, DB is seeded (15 hospitals + 4 ambulances).
2. Hospital staff open the dashboard at `:5174`, pick a hospital (e.g. "Apollo Hospitals, Jubilee Hills") and **Open dashboard**. A WebSocket to `/ws/hospital/<id>` opens. Optionally they push a capacity status.

### Phase 1 — Ambulance crew registers a case
1. Crew opens the ambulance app at `:5173`.
2. **Step 1:** select emergency type (e.g. `TRAUMA`) and severity (`HIGH`).
3. **Step 2:** enter patient vitals (age, conscious, SpO₂, heart rate, BP) and the ambulance id.
4. On submit the app calls:
   - `POST /api/v1/emergencies` → creates the case, status `OPEN`.
   - `POST /api/v1/emergencies/<case_id>/recommend` → runs the decision engine, stores the recommendation, case → `RECOMMENDED`.
   - `GET /api/v1/hospitals` → (best-effort) maps hospital ids to names for display.

### Phase 2 — Crew sees the recommendation
1. App shows the recommended hospital name, ETA, total care delay, the reason list, and expandable alternatives (including eliminated hospitals and why).
2. If nothing is eligible, the app shows the "No eligible hospital" state with the elimination reasons.

### Phase 3 — Accept & alert the hospital
1. Crew clicks **Accept**.
2. `POST /api/v1/recommendations/<case_id>/accept` → case → `ACCEPTED`, ambulance → `BUSY`.
3. `POST /api/v1/hospital-alerts` → creates a `PENDING` alert and pushes it over WebSocket to the hospital's channel. The dashboard (if open for that hospital) displays the alert card with patient vitals, required capabilities, and ETA. A background timer starts (`ALERT_RESPONSE_TIMEOUT_SECONDS`).

### Phase 4 — Hospital responds
- **ACCEPT** → `POST /api/v1/hospital-alerts/<id>/accept` marks the alert `ACCEPTED`. Dashboard shows "Accepted — ambulance en route".
- **UNABLE TO RECEIVE** → `POST /api/v1/hospital-alerts/<id>/reject`:
  1. Marks the alert `REJECTED`.
  2. Re-runs the decision engine **without** the rejected hospital.
  3. Stores a new recommendation (upsert) and pushes it over WebSocket to the **ambulance's** channel.
  4. The ambulance crew sees the new destination (if they have the ambulance WS channel open).
- **No response in time** → the background `_alert_timeout` task auto-rejects and re-routes exactly as in the manual reject.

### Phase 5 — Handover complete
1. When the patient is handed over, the case is closed:
   - `POST /api/v1/emergencies/<case_id>/close` → case → `CLOSED`, ambulance → `ACTIVE`.
2. The ambulance is now free for the next call.

---

## 13. Seed Scripts & Demo Scenario

### `scripts/seed_hospitals.py`
Clears `hospitals` and `hospital_status`, then inserts **15 synthetic hospitals** spread around a ~15 km radius of **Hyderabad, India** with varied capabilities:
- Full trauma/ICU centers with blood banks
- Stroke-capable (neurology + CT)
- Cardiac-capable (cardiology + cath lab)
- Pediatric/obstetric-focused hospitals
- Small emergency-only clinics (no trauma/ICU)

It also creates a matching `hospital_status` per hospital with randomized bed counts and department availability (`random.seed(42)` for reproducibility), then prints a summary table. **Safe to re-run** — it clears first.

### `scripts/seed_ambulances.py`
Clears `ambulances` and inserts 4 synthetic ambulances (`amb-001`…`amb-004`) with varied types and statuses around Hyderabad. Needed because `recommend` resolves the ambulance's location for ETA.

### `scripts/check_db.py`
Connects using the same config as the app, lists collections, does an insert→read→delete round trip on a throwaway doc, and reports `SUCCESS`/`FAILURE`.

### `scripts/demo_scenario.py` — the live A/B/C demo
Rehearses the design doc's "Hospital A/B/C" scenario against a **running** server. Run the backend first, then:

```bash
python scripts/demo_scenario.py
# or skip re-seeding:
python scripts/demo_scenario.py --skip-seed
# or point at a different server:
python scripts/demo_scenario.py --base-url http://localhost:8000
```

What it does:
1. Ensures hospitals are seeded.
2. Resolves the three scenario hospitals by name.
3. Registers (or resets) ambulance `amb-demo-001`.
4. Creates a severe TRAUMA case.
5. Pins deterministic statuses:
   - **A** — City Clinic, Mehdipatnam: emergency-only, no trauma/ICU → *will be eliminated*
   - **B** — Gleneagles Global Hospitals: full trauma center, ICU 6/10 → *best pick*
   - **C** — CARE Hospitals, Banjara Hills: full trauma center, ICU 4/12 → *backup*
6. Runs the decision engine → **B wins**.
7. Simulates B's ICU filling up (`icu_available: 0`).
8. Re-runs the engine → **re-routes to C**.
9. Prints a BEFORE/AFTER summary and narration.

---

## 14. Testing

### Running the tests

```bash
cd emergency-routing-backend
python -m pytest tests -q
```

Requires the venv activated and MongoDB reachable (some tests use a real test database).

### What is covered

| Test file | Scope |
| --- | --- |
| `test_clinical_requirements.py` | Parametrized matrix: every emergency type × severity → expected capability requirements; unknown type/severity raises; fresh dicts each call. |
| `test_eligibility_filter.py` | Elimination reasons (no status, not accepting, stale, missing capability, no ICU beds, department unavailable), staleness logic. |
| `test_eta_service.py` | Haversine math, `get_eta` fallback shape, routing-provider selection. |
| `test_decision_engine.py` | Scoring math (`total_care_delay = eta + wait + readiness`), the A/B/C design scenario (B wins → C when B fills), no-eligible case, wait-time estimation, treatment readiness lookup. |
| `test_hospitals_api.py` | Hospital list, radius filter (and the `422` when partial params), status get/upsert. |
| `test_ambulances_api.py` | Register (duplicate → `409`), update/PATCH (location pings), radius filter. |
| `test_emergencies_api.py` | Full flow create→recommend→accept→close; accept alternatives; validation errors (`422`); all the `404` paths; ambulance BUSY/ACTIVE transitions. |
| `test_alerts_api.py` | Alert creation + WS broadcast shape, accept, reject + re-route, timeout behavior. |
| `test_indexes.py` | Index creation idempotency. |

### How API tests isolate data

API tests use a **dedicated test database** (`emergency_routing_test`) and FastAPI's `dependency_overrides` to swap `get_db`. They clean the relevant collections before each scenario, so **your seeded dev data is never touched**. They drive the app in-process via `httpx.ASGITransport` (no live server needed) while still hitting a real MongoDB instance.

---

## 15. Frontend Applications

Both frontends are minimal React 18 + Vite apps with no UI framework or state library (plain `useState`/`useEffect`).

### Ambulance App (`ambulance-app`)

- **`src/api.js`** — `api(path, options)` wrapper over `fetch` that attaches the JSON header, throws `Error(detail)` with the backend's `detail` message on non-2xx, and returns parsed JSON.
- **`src/App.jsx`** — a 3-step wizard:
  1. **Emergency type** — radio cards for the 8 types + severity dropdown.
  2. **Patient vitals** — age, conscious yes/no, SpO₂, heart rate, BP, ambulance id. Submit → create case → get recommendation → fetch hospital names.
  3. **Recommendation** — recommended hospital, ETA, total care delay, reasons, collapsible alternatives (eligible backups vs eliminated + reason), **Accept** button, "Start over".
- On accept: `POST /recommendations/<case_id>/accept` then `POST /hospital-alerts` (alert failure is non-blocking).

> **Note:** the ambulance app's UI is primarily a manual demo flow. The WebSocket channel for re-routing (`/ws/ambulance/{id}`) exists on the backend, but the current React UI does **not** subscribe to it. Re-routing updates are visible via the demo script or a WS client.

### Hospital Dashboard (`hospital-dashboard`)

- **`src/api.js`** — same `api()` wrapper plus `hospitalWsUrl(id)` which rewrites `http(s)://.../ws` → `ws(s)://.../ws/hospital/<id>`.
- **`src/App.jsx`** — two views:
  1. **Select view** — loads `/hospitals`, lets staff choose a hospital, "Open dashboard".
  2. **Dashboard view** — loads `/hospitals/<id>/status` into a capacity form (ICU/emergency beds, 5 department statuses, accepting patients toggle). `Update Status` upserts it via `POST /hospitals/<id>/status`. Below the form is the **live incoming alerts feed** fed by the WebSocket, with `ACCEPT` / `UNABLE TO RECEIVE` buttons that call the alert accept/reject endpoints. It auto-reconnects every 3 s on disconnect and shows a connection badge.

---

## 16. Error Handling & Edge Cases

- **Global exception handler** (`app/main.py`): catches unhandled exceptions and returns `{"detail": "Internal server error"}` with status `500` (never leaks stack traces).
- **Pydantic validation** returns `422` with field-level detail for malformed bodies (bad BP format, out-of-range vitals, unknown severity, partial radius params, invalid ObjectId…).
- **Duplicate ambulance registration** → `409`.
- **Every missing resource** → `404` with a specific `detail`.
- **Routing API failure** degrades to haversine ETA.
- **No eligible hospital** → `no_eligible_hospital: true` with elimination reasons; the frontends render the "no eligible" state and disable Accept.
- **Alert broadcast failure on accept** is non-blocking in the ambulance app (fire-and-forget).
- **Hospital-name lookup failure** in the ambulance app falls back to raw ids.
- **Stale status** (`> MAX_STATUS_AGE_SECONDS`) makes a hospital ineligible — simulating a hospital whose data is too old to trust.

---

## 17. Known Limitations & Production Considerations

1. **WebSocket manager is in-memory & single-process.** Broadcasts only reach clients connected to the same process. For multi-instance deployments, replace `ConnectionManager` with Redis pub/sub (or similar broker).
2. **Demo-scale data.** Hospitals/ambulances are synthetic Hyderabad fixtures. No auth, no multi-tenancy, no audit log.
3. **ETA fallback is straight-line distance** unless you configure OpenRouteService. Real road ETA requires the API key and outbound network access.
4. **Alert timeout is in-process** (`asyncio.create_task`). Across instances/restarts, timers are lost. A production design would use a scheduler or TTL index.
5. **No idempotency keys.** Duplicate POSTs could create duplicate cases/alerts. Consider unique constraints on intent ids in production.
6. **Case status transitions are not enforced as a state machine** — the API endpoints set statuses but nothing validates ordering (e.g. accepting before recommending returns 404 on missing recommendation, but a "close" can be called on any state).
7. **Not production medical software.** Intended for evaluation/development; clinical rules are illustrative, not certified.

---

## 18. FAQ / Troubleshooting

**Q: `uvicorn` fails with "MongoDB connection is not initialized"?**
Make sure MongoDB is running, then restart the backend. If using Atlas, check `MONGO_URI` in `.env`.

**Q: `/health` returns `database: "down"`?**
MongoDB isn't reachable or was restarted after the backend started. Restart the backend.

**Q: The ambulance app shows an error when creating a case?**
The backend must be running on `:8000` and `VITE_API_BASE_URL` must be correct. Check `ambulance-app/.env`.

**Q: The dashboard shows "Disconnected — retrying"?**
Check `VITE_WS_URL` in `hospital-dashboard/.env` and confirm the backend WS route works (`ws://localhost:8000/ws/hospital/<id>`).

**Q: The recommendation says "No eligible hospital" even though hospitals exist?**
Likely causes: hospital statuses are missing, stale (older than `MAX_STATUS_AGE_SECONDS`), or `accepting_patients: false`. Re-run `python scripts/seed_hospitals.py` to refresh.

**Q: How do I reset the whole dev database?**
Re-run the seed scripts — they clear their collections first. For a full wipe, drop the `emergency_routing` database in Mongo.

**Q: Tests fail with connection errors?**
The API tests need a reachable MongoDB. Start it first, then `python -m pytest tests -q`.

**Q: Do I need to run the frontends to use the system?**
No. Everything is API-driven; you can drive the whole flow with curl or the `demo_scenario.py` script. The frontends are convenience UIs.

**Q: Where is the Swagger documentation?**
`http://localhost:8000/docs` (interactive) and `http://localhost:8000/redoc`.

---

*Generated as the canonical onboarding document for the Emergency Routing System. For component-level detail, see `emergency-routing-backend/README.md`.*
