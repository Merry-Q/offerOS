import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from server.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings.ensure_dirs()
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS resumes (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_text TEXT,
                profile_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preferences (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                pay TEXT NOT NULL,
                company TEXT NOT NULL,
                goal TEXT NOT NULL,
                chips_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                jd_profile_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS match_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                resume_id TEXT NOT NULL,
                resume_name TEXT NOT NULL,
                pref_id TEXT NOT NULL,
                pref_name TEXT NOT NULL,
                score INTEGER,
                level TEXT,
                one_liner TEXT,
                dims_json TEXT,
                threshold INTEGER,
                raw_score INTEGER,
                strengths_json TEXT,
                gaps_json TEXT,
                jd_profile_json TEXT,
                report_json TEXT,
                llm_meta_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                props_json TEXT,
                user_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_event ON analytics_events(event);
            CREATE INDEX IF NOT EXISTS idx_events_created ON analytics_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_match_job ON match_runs(job_id);
            """
        )
        _ensure_column(conn, "resumes", "user_id", "TEXT")
        _ensure_column(conn, "preferences", "user_id", "TEXT")
        _ensure_column(conn, "jobs", "user_id", "TEXT")
        _ensure_column(conn, "analytics_events", "user_id", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prefs_user ON preferences(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id)")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
