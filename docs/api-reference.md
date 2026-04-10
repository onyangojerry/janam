# API Reference

## Authentication

Janam uses API key authentication via HTTP header:

- Header: `X-API-Key`
- Read endpoints require read or write key
- Write endpoints require write key

Key variables:

- `JANAM_WRITE_API_KEY`
- `JANAM_READ_API_KEY`
- `JANAM_ENFORCE_EXPLICIT_KEYS`

## Health

- `GET /health`
  - Returns service status

## Report Endpoints

- `POST /reports/analyze`
- `POST /reports/text`
- `POST /reports/audio`
- `POST /reports/image`
- `POST /reports/video`
- `POST /reports/upload` (multipart)
- `GET /reports?limit=<n>`

## Alert and Analytics Endpoints

- `GET /alerts?limit=<n>`
- `GET /analytics/locations?limit=<n>`

## Ingest Endpoints

- `POST /ingest/events`
  - Generic normalized ingest endpoint

- `POST /ingest/n8n`
  - n8n-focused endpoint with signature verification
  - Required headers:
    - `X-Janam-Webhook-Timestamp`
    - `X-Janam-Webhook-Signature`
    - `X-API-Key`

### n8n Signature Contract

- Algorithm: HMAC-SHA256
- Message format: `<timestamp>.<raw_request_body>`
- Secret: `JANAM_N8N_WEBHOOK_SECRET`
- Replay protection: `JANAM_N8N_WEBHOOK_MAX_SKEW_SECONDS`

## WebSocket Channels

- `WS /ws/updates`
- `WS /ws/cases`
- `WS /ws/alerts`

Authentication for websockets:

- Query param: `api_key=<key>`
- Or header: `X-API-Key`

## API Docs UI

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
