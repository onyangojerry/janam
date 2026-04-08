# Janam

Janam is a FastAPI-based prototype for crime detection and real-time danger-zone intelligence, with a static operations console frontend.

It now supports centralized persistence and synchronization, so reports submitted by one user are visible to all connected users.

## Stack

- Backend: FastAPI + Pydantic + SQLite/PostgreSQL option
- Frontend: Static HTML/JS operations console
- Realtime: WebSocket updates, alert streaming, and DB-backed case streaming

## Local run (without Docker)

1. Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run backend:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

3. Serve frontend:

```bash
cd frontend/pages
python -m http.server 5500
```

4. Open:

- Frontend: http://127.0.0.1:5500/demos/janam.html
- API docs: http://127.0.0.1:8000/docs

## Docker deployment

1. Create env file:

```bash
cp .env.example .env
```

2. Update keys in `.env` to strong values.

3. Start services:

```bash
docker compose up --build -d
```

4. Access:

- Frontend: http://127.0.0.1:5500/demos/janam.html
- Backend: http://127.0.0.1:8000

5. Central sync behavior:

- PostgreSQL runs as the central data store (`db` service).
- Use `/ws/cases` to stream newly persisted cases from the shared database.
- Use `/analytics/locations` for aggregated safety analytics by location.

5. Stop services:

```bash
docker compose down
```

## Security notes

- `JANAM_ENFORCE_EXPLICIT_KEYS=true` blocks startup if default/dev keys are used.
- Keep `JANAM_WRITE_API_KEY` and `JANAM_READ_API_KEY` secret.
- Restrict `JANAM_CORS_ORIGINS` to trusted frontend origins.

## Key environment variables

- `JANAM_WRITE_API_KEY`: write-role API key
- `JANAM_READ_API_KEY`: read-role API key
- `JANAM_ENFORCE_EXPLICIT_KEYS`: enforce non-default keys (`true`/`false`)
- `JANAM_DB_BACKEND`: `sqlite` or `postgres`
- `JANAM_DATABASE_URL`: PostgreSQL DSN when using postgres backend
- `JANAM_DB_PATH`: sqlite database path (container default set by compose)
- `JANAM_LOG_PATH`: log file path

## New ingestion + analytics endpoints

- `POST /reports/upload` multipart upload for audio/image/text files (`file`, optional `source`, `location`, `note`)
- `POST /reports/image` analyze image-typed report payloads
- `GET /analytics/locations` aggregate report counts and severity by location
- `WS /ws/cases` stream newly created reports from the shared DB in near real time
- `POST /ingest/events` receive normalized events from external connector/bridge services

## Open-source connector machinery

Use open-source bridge/automation tools to ingest messages/media from external services into Janam.

Recommended pattern:

- Connector layer (examples):
	- Matrix + bridges (`mautrix-whatsapp`, `mautrix-signal`, `mautrix-facebook`)
	- `matterbridge`
	- `n8n` or `Node-RED` workflows
- Normalization layer:
	- Convert incoming provider payloads to Janam's `POST /ingest/events` schema.
- Janam layer:
	- Stores the event as a report, runs analysis, and triggers alerts/websocket streams.

Example ingest payload:

```json
{
	"platform": "whatsapp-bridge",
	"channel_id": "community-group-1",
	"sender_id": "user-88",
	"message_text": "Armed attack with gunshots near central station.",
	"media_type": "text",
	"location": "central-station",
	"latitude": 6.45,
	"longitude": 3.41,
	"external_event_id": "wa-msg-9988",
	"raw_payload": {"kind": "message", "priority": "urgent"}
}
```

Connector notes:

- For platforms like WhatsApp/Facebook/Signal, ingest should run through approved/open-source bridge tooling under your own account/service setup.
- Janam intentionally keeps ingestion generic so any compliant connector can push events.

Hybrid/scaled integration pattern:

- Run n8n where it best fits each connector:
	- local/on-prem for SIM/text gateway or private network systems
	- cloud-hosted for SaaS APIs (Gmail/Outlook/Facebook webhooks)
- Route all normalized events to a central Janam API endpoint (`/ingest/n8n` or `/ingest/events`).
- This gives one analysis + alert pipeline while allowing many source integrations.

### n8n quick wiring

- If you are building in n8n, you can post raw webhook items directly to:
	- `POST /ingest/n8n`
- `POST /ingest/n8n` requires signed webhook headers:
	- `X-Janam-Webhook-Timestamp`: unix timestamp (seconds)
	- `X-Janam-Webhook-Signature`: `sha256=<hex_hmac>`
- Signature input format:
	- `"<timestamp>." + <raw_request_body_bytes>`
- HMAC algorithm:
	- `HMAC-SHA256` using `JANAM_N8N_WEBHOOK_SECRET`
- Replay protection:
	- timestamps outside `JANAM_N8N_WEBHOOK_MAX_SKEW_SECONDS` are rejected
- Supported n8n/raw keys include both snake_case and camelCase variants, for example:
	- `text` or `message_text`
	- `type` or `media_type`
	- `chatId` or `channel_id`
	- `author`/`from` or `sender_id`
	- `lat`/`lng` or `latitude`/`longitude`

Example n8n payload:

```json
{
	"provider": "signal-bridge",
	"chatId": "community-alerts",
	"author": "user-11",
	"text": "Gun attack near junction.",
	"type": "text",
	"lat": "6.4501",
	"lng": "3.4202",
	"eventId": "sig-11"
}
```

Example signature pseudo-code:

```text
timestamp = unix_seconds()
body = raw_http_body_bytes
signature = hex(HMAC_SHA256(secret=JANAM_N8N_WEBHOOK_SECRET, message=timestamp + "." + body))
headers:
	X-Janam-Webhook-Timestamp: timestamp
	X-Janam-Webhook-Signature: sha256=<signature>
```

### Multi-platform connector templates

See [CONNECTORS.md](CONNECTORS.md) for ready-to-use n8n Function node templates to wire up:
- **WhatsApp** (Meta Cloud API)
- **Signal** (signal-cli webhook)
- **Facebook Messenger** (Messenger Platform)
- **Gmail** (Google Cloud Pub/Sub)
- **Outlook** (Microsoft Graph webhooks)

Each template includes HMAC-SHA256 signature generation, field normalization to Janam schema, and example payloads for testing.

Anonymous updater safety defaults:

- Ingest is anonymous by default (`anonymous_mode=true`).
- Janam stores fingerprints instead of raw `sender_id`, `channel_id`, and external event IDs.
- Sensitive text fragments (email/phone) are scrubbed before persistence.
- Raw connector payload storage is off by default (`JANAM_STORE_INGEST_RAW_PAYLOAD=false`).
- GPS is coarsened by default (`JANAM_GPS_ROUND_DECIMALS=3`) to reduce precise reporter tracing risk.

You can opt out per event by setting `anonymous_mode=false` on trusted operational feeds.

## Open-source GPS location updates

- The operations console now supports device GPS via browser geolocation and OpenStreetMap Nominatim reverse geocoding.
- In `demos/janam.html`, click `Use Device GPS (OpenStreetMap)` to auto-fill:
	- `latitude`
	- `longitude`
	- `location` (human-readable place name)
- Coordinates are persisted with each report and available in:
	- report responses (`latitude`, `longitude`)
	- alert events (`latitude`, `longitude`)
	- location analytics output (`latitude`, `longitude` when available)

Note: GPS capture requires HTTPS in most browsers, except localhost during development.

## Live map view

- The demo console now includes a live OpenStreetMap map panel.
- It renders markers from:
	- `GET /reports` during initial load/refresh
	- `WS /ws/cases` for realtime newly synced cases
	- `GET /alerts` and `WS /ws/alerts` for severity updates
- Each marker popup includes case ID, severity, location, summary, and timestamp.
- Map controls include severity filters (high/medium/low) and two quick actions:
	- `Fit Visible Cases`: zooms to currently visible markers.
	- `Center High Risk`: centers on the latest high-severity case.

## Geofence notifications

- The map includes a configurable geofence alert mode for user safety.
- Enable `Enable Geofence Alerts`, then set `Alert Radius (meters)`.
- Optional: enable `Audible Alarm` for sound-based warning cues.
- Configure per-severity cooldowns to limit repeated alerts while inside the same zone:
	- `High Cooldown (seconds)`
	- `Medium Cooldown (seconds)`
	- `Low Cooldown (seconds)`
- The app uses your device GPS location and checks distance to high-risk incidents in real time.
- When you enter the configured radius of a high-risk case, the console logs a geofence trigger and attempts a browser notification.
- Use `Check Geofence Now` for an on-demand distance check.
