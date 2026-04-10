# Janam Architecture

## Overview

Janam is a FastAPI-based incident intelligence backend with a static web operations console.
It supports real-time synchronization, alert streaming, geospatial context, and external ingest connectors (including n8n).

## Core Components

- Backend API: FastAPI application in `backend/main.py` and `backend/app/api/routes.py`
- Analysis Engine: `JanamAnalysisService` and `JanamBrain`
- Persistence Layer: repository pattern over SQLite/PostgreSQL
- Realtime Streams: WebSocket channels for updates, cases, and alerts
- Frontend Console: static HTML/JS dashboard in `frontend/pages/demos/janam.html` and `frontend/pages/demos/janam.js`
- Connector Layer: external systems post normalized events to `/ingest/events` or `/ingest/n8n`

## Data Flow

### User Reports

1. Client submits report via HTTP endpoint.
2. API validates request and authorizes with API key.
3. Analysis service scores severity and extracts signal.
4. Report is stored in DB.
5. Alert stream publishes events for medium/high severity.
6. WebSocket clients receive realtime updates.

### Connector Ingest (n8n / Bridges)

1. External source sends event to connector workflow.
2. Connector normalizes payload to Janam ingest schema.
3. For `/ingest/n8n`, connector signs payload with HMAC-SHA256.
4. Backend verifies signature, timestamp skew, and API key.
5. Backend applies anonymity/privacy controls by default.
6. Event is analyzed, persisted, and broadcast as needed.

## Storage

- Local development: SQLite (optional)
- Production: PostgreSQL recommended
- DB initialization is performed on startup

## Security and Privacy by Design

- Role-based API keys for read/write actions
- Optional explicit-key enforcement at startup
- Signed webhook verification for `/ingest/n8n`
- Anonymous ingest mode enabled by default
- PII scrubbing and identity fingerprinting on ingest
- Coordinate coarsening for safer geospatial privacy

## Scalability Pattern

- Run Janam backend as central API service.
- Run n8n/bridge connectors where data sources live (hybrid local/cloud).
- Route all normalized events to central Janam API.
- Scale backend replicas and Postgres resources independently.
