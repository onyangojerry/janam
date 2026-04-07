# Janam

Janam is a FastAPI-based prototype for crime detection and real-time danger-zone intelligence, with a static operations console frontend.

## Stack

- Backend: FastAPI + Pydantic + SQLite/PostgreSQL option
- Frontend: Static HTML/JS operations console
- Realtime: WebSocket updates and alert streaming

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
