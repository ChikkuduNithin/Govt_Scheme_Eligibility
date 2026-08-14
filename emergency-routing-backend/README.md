# Emergency Routing Backend

FastAPI backend for the emergency routing system. Async endpoints powered by FastAPI, async MongoDB access via motor.

## Project Structure

```
emergency-routing-backend/
  app/
    main.py            # FastAPI app, CORS, healthcheck
    core/
      config.py        # pydantic-settings config loaded from .env
      database.py      # motor async MongoDB client + get_db() dependency
    models/            # pydantic models (Create + InDB per collection)
    routers/
      hospitals.py     # /api/v1/hospitals endpoints
      ambulances.py    # /api/v1/ambulances endpoints (register / GPS updates)
      emergencies.py   # /api/v1/emergencies + /api/v1/recommendations endpoints
      alerts.py        # /api/v1/hospital-alerts endpoints
      ws.py            # /ws/hospital/{hospital_id} + /ws/ambulance/{ambulance_id}
    services/          # business logic (clinical requirements, eligibility, ETA, decision engine, ws_manager)
  scripts/
    check_db.py        # DB connection verification script
    seed_hospitals.py  # dev seed: hospitals + hospital_status for Hyderabad
    seed_ambulances.py # dev seed: ambulances for Hyderabad
  tests/
    test_clinical_requirements.py
    test_eligibility_filter.py
    test_eta_service.py
    test_decision_engine.py
    test_hospitals_api.py
    test_emergencies_api.py
    test_alerts_api.py
    test_ambulances_api.py
    test_indexes.py
  requirements.txt
  .env.example
  README.md
```

## Requirements

- Python 3.10+
- MongoDB running locally (or a MongoDB Atlas connection string)

## Setup

```bash
cd emergency-routing-backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

Create your `.env` from the example:

```bash
cp .env.example .env
```

## Run Locally

```bash
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000.

- Interactive docs: http://localhost:8000/docs
- Healthcheck: http://localhost:8000/health

The `/health` endpoint returns `{"status": "ok"}` and reports MongoDB connection status. The app connects to MongoDB on startup and closes the connection on shutdown.

## Verify the Database Connection

Before continuing development, run the DB check script to confirm MongoDB is reachable and the configured database is usable:

```bash
python scripts/check_db.py
```

What it does:

1. Connects to MongoDB using the same `MONGO_URI` / `DB_NAME` config from `.env` (via `app/core/config.py`).
2. Lists the existing collections in the database.
3. Inserts one throwaway test document into a `connection_test` collection, reads it back and prints it, then deletes it.
4. Prints a clear `SUCCESS` or `FAILURE` message.

You should see `SUCCESS: MongoDB connection and basic read/write/delete all work.` If you see a `FAILURE` message instead, check that MongoDB is running and that your `MONGO_URI` in `.env` is correct.

## Seed the Database

Populate the `hospitals` and `hospital_status` collections with 15 synthetic hospitals around Hyderabad, India:

```bash
python scripts/seed_hospitals.py
```

This is a dev-only seed. It **clears both collections** before inserting, so it is safe to re-run. It inserts:

- 15 hospitals spread across a ~15km radius of Hyderabad with varied, realistic capabilities (large trauma/ICU centers with blood banks, stroke-capable neurology+CT hospitals, cardiac-capable cardiology+cath_lab hospitals, pediatric/obstetric-focused hospitals, and small clinics with no trauma/ICU).
- A matching `hospital_status` document per hospital with plausible randomized bed counts (`icu_available` between 0 and `icu_total`, etc.), random `AVAILABLE`/`UNAVAILABLE` department statuses, and `accepting_patients` mostly true.

After seeding, a summary table is printed to the console showing each hospital's trauma/ICU/stroke/cardiac flags and whether it is accepting patients, followed by a count summary of the capability mix.

## Seed Ambulances

Populate the `ambulances` collection with a few synthetic ambulances around Hyderabad:

```bash
python scripts/seed_ambulances.py
```

This is also a dev-only seed and **clears the `ambulances` collection** before inserting. The `recommend` endpoint needs a matching ambulance to know where the patient is being picked up from.

## API Endpoints

All routes are under `/api/v1`.

### Hospitals

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/hospitals` | List hospitals. Optional `?lat=&lng=&radius_km=` filters to those within the radius (all three must be provided together). |
| `GET` | `/hospitals/{hospital_id}` | Hospital details, including its current status (or `status: null`). |
| `GET` | `/hospitals/{hospital_id}/status` | Current hospital status. |
| `POST` | `/hospitals/{hospital_id}/status` | Create/update hospital status (upsert by `hospital_id`; server-stamped `updated_at`). |

### Ambulances

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/ambulances` | List ambulances, optional `?status=` filter and `?lat=&lng=&radius_km=` nearby search. |
| `POST` | `/ambulances` | Register an ambulance (unique `ambulance_id`; `409` on duplicate). |
| `GET` | `/ambulances/{ambulance_id}` | Fetch one ambulance. |
| `PATCH` | `/ambulances/{ambulance_id}` | Update live location and/or status. The ambulance app pushes GPS pings here so ETA uses the current position. |

### Emergencies

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/emergencies` | Create an emergency case. Body: `emergency_type`, `severity`, `patient`, `ambulance_id`. Server generates `case_id` and sets status `OPEN`. |
| `GET` | `/emergencies/{case_id}` | Fetch an emergency case. |
| `POST` | `/emergencies/{case_id}/recommend` | Run the decision engine (eligibility + ETA + wait-time estimation) against all hospitals and their statuses. Stores the recommendation and moves the case to `RECOMMENDED`. |
| `GET` | `/recommendations/{case_id}` | Fetch the stored recommendation. |
| `POST` | `/recommendations/{case_id}/accept` | Accept a hospital for the case. Body: `{"hospital_id": "..."}`. The crew usually picks the recommended hospital but may pick any alternative. Moves the case to `ACCEPTED` and marks the ambulance `BUSY`. |
| `POST` | `/emergencies/{case_id}/close` | Close the case (patient handover complete). Sets status `CLOSED` and returns the ambulance to `ACTIVE`. |

### Hospital Alerts

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/hospital-alerts` | Notify a hospital about a case. Body: `{"case_id": "...", "hospital_id": "..."}`. Creates a `hospital_alerts` doc (`PENDING`) embedding a snapshot (patient info, emergency type, required capabilities, ETA from the stored recommendation) and broadcasts it over WebSocket to that hospital's channel. |
| `POST` | `/hospital-alerts/{alert_id}/accept` | Marks the alert `ACCEPTED`. |
| `POST` | `/hospital-alerts/{alert_id}/reject` | Marks the alert `REJECTED`, re-runs the decision engine excluding the rejected hospital, stores a new recommendation and broadcasts it over WebSocket to the ambulance's channel. |

A `PENDING` alert that gets no response within `ALERT_RESPONSE_TIMEOUT_SECONDS` is automatically rejected and re-routed by a background task.

## Configuration

All settings are loaded from `.env` (see `.env.example`):

| Setting | Default | Purpose |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME` | `emergency_routing` | Database name |
| `PORT` | `8000` | Uvicorn port |
| `AVG_URBAN_SPEED_KMH` | `30.0` | Speed used by the haversine ETA fallback |
| `ROUTING_PROVIDER` | `haversine` | `haversine` (built-in) or `openrouteservice` (real road routing) |
| `ROUTING_API_KEY` | *(empty)* | OpenRouteService API key |
| `ALERT_RESPONSE_TIMEOUT_SECONDS` | `30` | Auto-reject + re-route after this long without a response |
| `MAX_STATUS_AGE_SECONDS` | `600` | Hospital statuses older than this are treated as stale/ineligible |
| `WS_KEEPALIVE_SECONDS` | `30` | WebSocket ping interval |

### WebSockets

| Endpoint | Purpose |
| --- | --- |
| `WS /ws/hospital/{hospital_id}` | Hospital dashboard subscribes here to receive incoming alerts in real time. |
| `WS /ws/ambulance/{ambulance_id}` | Ambulance app subscribes here to receive re-routing updates when a hospital rejects an alert. |

The WebSocket layer uses an in-memory `ConnectionManager` (keyed by `hospital_id` / `ambulance_id`). This is single-process only; a production deployment running multiple instances should replace it with Redis pub/sub so broadcasts reach subscribers on any instance.

## Run Tests

```bash
python -m pytest tests -q
```

Note: the API tests (`test_hospitals_api.py`, `test_emergencies_api.py`) run against a dedicated test database (`emergency_routing_test`) and use `dependency_overrides` so they never touch your seeded data.
