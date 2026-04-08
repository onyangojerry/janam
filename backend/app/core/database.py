"""Database helpers for Janam."""

from __future__ import annotations

from pathlib import Path
import os
import sqlite3
from typing import Any, Literal


DatabaseBackend = Literal["sqlite", "postgres"]


def default_database_path() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "data" / "janam.sqlite3"


def get_database_backend() -> DatabaseBackend:
    backend = os.getenv("JANAM_DB_BACKEND", "sqlite").strip().lower()
    if backend == "postgres":
        return "postgres"
    return "sqlite"


def is_postgres_backend() -> bool:
    return get_database_backend() == "postgres"


def get_postgres_dsn() -> str:
    return os.getenv("JANAM_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/janam")


def get_database_path() -> Path:
    configured = os.getenv("JANAM_DB_PATH")
    return Path(configured) if configured else default_database_path()


def to_driver_sql(query: str) -> str:
    if not is_postgres_backend():
        return query
    return "%s".join(query.split("?"))


def get_connection() -> Any:
    if is_postgres_backend():
        from psycopg import connect
        from psycopg.rows import dict_row

        return connect(get_postgres_dsn(), row_factory=dict_row)

    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    if not is_postgres_backend():
        database_path = get_database_path()
        database_path.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        if is_postgres_backend():
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id BIGSERIAL PRIMARY KEY,
                    report TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    source TEXT,
                    location TEXT,
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    extraction_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    source TEXT,
                    location TEXT,
                    latitude REAL,
                    longitude REAL,
                    extraction_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

        # Backward-compatible migration for existing databases created before GPS support.
        if is_postgres_backend():
            connection.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
            connection.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
        else:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(reports)").fetchall()
            }
            if "latitude" not in columns:
                connection.execute("ALTER TABLE reports ADD COLUMN latitude REAL")
            if "longitude" not in columns:
                connection.execute("ALTER TABLE reports ADD COLUMN longitude REAL")

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_report_type ON reports(report_type)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_location ON reports(location)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_lat_lon ON reports(latitude, longitude)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_source ON reports(source)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at)"
        )
        connection.commit()
