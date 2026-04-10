# Deployment Guide

## Recommended Production Topology

- Backend: containerized FastAPI service
- Database: managed PostgreSQL
- Frontend: static hosting or CDN-backed web server
- Connector orchestration: n8n Cloud or self-hosted n8n

## 1. Prerequisites

- Domain and TLS certificates
- Managed Postgres instance
- Container hosting platform (Render, Railway, Fly.io, AWS, etc.)
- Secrets manager or secure environment variable storage

## 2. Configure Environment Variables

Start from `.env.example` and set strong values.

Required variables:

- `JANAM_API_KEY`
- `JANAM_WRITE_API_KEY`
- `JANAM_READ_API_KEY`
- `JANAM_ENFORCE_EXPLICIT_KEYS=true`
- `JANAM_DB_BACKEND=postgres`
- `JANAM_DATABASE_URL=<postgres-dsn>`
- `JANAM_N8N_WEBHOOK_SECRET=<strong-random-secret>`
- `JANAM_N8N_WEBHOOK_MAX_SKEW_SECONDS=300`
- `JANAM_CORS_ORIGINS=<frontend-domain-list>`

Privacy defaults (recommended):

- `JANAM_ANONYMIZE_INGEST=true`
- `JANAM_ANONYMIZATION_SALT=<strong-random-secret>`
- `JANAM_STORE_INGEST_RAW_PAYLOAD=false`
- `JANAM_GPS_ROUND_DECIMALS=3`

## 3. Deploy Backend

- Build using `Dockerfile.backend`
- Expose service on port `8000`
- Verify startup health at `/health`

## 4. Deploy Frontend

- Build/static serve from `frontend/pages`
- Ensure frontend points to deployed backend base URL

## 5. Connect n8n

- Set n8n workflow env vars:
  - `JANAM_INGEST_URL=https://<backend-domain>/ingest/n8n`
  - `JANAM_WRITE_API_KEY=<write-key>`
  - `JANAM_N8N_WEBHOOK_SECRET=<same-secret-as-backend>`
- Import and activate `n8n-whatsapp-workflow.json`

## 6. Post-Deploy Verification

Run smoke tests:

```bash
curl -i https://<backend-domain>/health
curl -i https://<backend-domain>/reports?limit=1 -H "X-API-Key: <READ_KEY>"
```

Signed ingest test (example):

```bash
TIMESTAMP=$(date +%s)
PAYLOAD='{"channel":"test","platform":"manual","message_text":"test message","media_type":"text"}'
SIG=$(printf "%s" "${TIMESTAMP}.${PAYLOAD}" | openssl dgst -sha256 -hmac "<N8N_SECRET>" -hex | awk '{print $2}')

curl -i -X POST "https://<backend-domain>/ingest/n8n" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <WRITE_KEY>" \
  -H "X-Janam-Webhook-Timestamp: ${TIMESTAMP}" \
  -H "X-Janam-Webhook-Signature: sha256=${SIG}" \
  -d "${PAYLOAD}"
```

## 7. Production Hardening Checklist

- Enforce HTTPS only
- Restrict CORS to trusted domains
- Rotate secrets regularly
- Enable DB backups and retention policy
- Add uptime and error-rate monitoring
- Define incident response contacts and runbook
