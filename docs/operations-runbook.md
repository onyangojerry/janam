# Operations Runbook

## Monitoring

Track:

- API health (`/health`)
- HTTP 5xx/4xx rates
- Ingest success/failure on `/ingest/n8n`
- DB availability and latency
- WebSocket connection counts

## Logging

- Ensure `JANAM_LOG_PATH` is writable in deployment environment
- Centralize logs in platform log aggregation
- Alert on repeated Unauthorized or signature failures

## Common Incidents

### 1. n8n requests failing with 401

Checks:

- `X-API-Key` matches backend write key
- `X-Janam-Webhook-Signature` computed with correct secret
- Request timestamp within allowed skew window

### 2. n8n requests failing with 503 on /ingest/n8n

Checks:

- `JANAM_N8N_WEBHOOK_SECRET` set in backend runtime
- Service restarted after env changes

### 3. Client cannot read reports

Checks:

- Read key configured correctly
- Header `X-API-Key` present
- CORS origin allowed for browser client

### 4. Missing realtime updates

Checks:

- WebSocket authenticated with key
- Network/proxy supports websocket upgrade
- Backend process healthy and not rate-limited

## Safe Restart Procedure

1. Confirm DB healthy.
2. Drain or pause external connector ingest.
3. Restart backend instances.
4. Resume ingest and validate `/health` and signed ingest.

## Backup and Recovery

- Use managed Postgres automatic backups.
- Define restore point objective and recovery time objective.
- Test restore process quarterly.
