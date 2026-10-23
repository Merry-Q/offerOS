import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from server.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    # WAL 降低读写互锁概率；失败时忽略（如只读介质）
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass
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

            CREATE TABLE IF NOT EXISTS job_discovery_runs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                resume_id TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                items_json TEXT NOT NULL DEFAULT '[]',
                errors_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_discovery_owner ON job_discovery_runs(user_id, created_at);

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
                judge_status TEXT,
                report_status TEXT,
                report_error TEXT,
                report_updated_at TEXT,
                judge_duration_ms INTEGER,
                report_duration_ms INTEGER,
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

            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                hits INTEGER DEFAULT 0,
                last_hit_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_event ON analytics_events(event);
            CREATE INDEX IF NOT EXISTS idx_events_created ON analytics_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_match_job ON match_runs(job_id);
            CREATE INDEX IF NOT EXISTS idx_llm_cache_kind ON llm_cache(kind);
            """
        )
        _ensure_column(conn, "resumes", "user_id", "TEXT")
        _ensure_column(conn, "preferences", "user_id", "TEXT")
        _ensure_column(conn, "jobs", "user_id", "TEXT")
        _ensure_column(conn, "analytics_events", "user_id", "TEXT")
        _ensure_column(conn, "match_runs", "judge_status", "TEXT")
        _ensure_column(conn, "match_runs", "report_status", "TEXT")
        _ensure_column(conn, "match_runs", "report_error", "TEXT")
        _ensure_column(conn, "match_runs", "report_updated_at", "TEXT")
        _ensure_column(conn, "match_runs", "judge_duration_ms", "INTEGER")
        _ensure_column(conn, "match_runs", "report_duration_ms", "INTEGER")
        _ensure_column(conn, "match_runs", "report_modules_json", "TEXT")
        _ensure_column(conn, "match_runs", "jd_text_hash", "TEXT")
        # Phase1+: 岗位元数据、批量、投递、偏好扩展
        _ensure_column(conn, "jobs", "company", "TEXT")
        _ensure_column(conn, "jobs", "location", "TEXT")
        _ensure_column(conn, "jobs", "source_url", "TEXT")
        _ensure_column(conn, "jobs", "batch_id", "TEXT")
        _ensure_column(conn, "jobs", "apply_status", "TEXT")
        _ensure_column(conn, "jobs", "closed_reason", "TEXT")
        _ensure_column(conn, "jobs", "starred", "INTEGER")
        _ensure_column(conn, "jobs", "employment_type", "TEXT")
        _ensure_column(conn, "match_runs", "starred", "INTEGER")
        _ensure_column(conn, "match_runs", "batch_id", "TEXT")
        _ensure_column(conn, "match_runs", "auto_report", "INTEGER")
        _ensure_column(conn, "resumes", "direction_tag", "TEXT")
        _ensure_column(conn, "preferences", "level", "TEXT")
        _ensure_column(conn, "preferences", "hard_constraint", "TEXT")
        _ensure_column(conn, "preferences", "direction", "TEXT")
        _ensure_column(conn, "preferences", "allow_cross_resume", "INTEGER")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS match_batches (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                resume_id TEXT,
                status TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                done_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_batches_user ON match_batches(user_id);

            CREATE TABLE IF NOT EXISTS application_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_status_history_job
              ON application_status_history(job_id, created_at);

            CREATE TABLE IF NOT EXISTS resume_drafts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                resume_id TEXT NOT NULL,
                job_id TEXT,
                match_id TEXT,
                source_text TEXT NOT NULL,
                suggested_text TEXT NOT NULL,
                edited_text TEXT NOT NULL,
                source_label TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_resume_drafts_user
              ON resume_drafts(user_id, updated_at);

            CREATE TABLE IF NOT EXISTS report_action_items (
                match_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(match_id, user_id, item_key)
            );

            CREATE TABLE IF NOT EXISTS match_batch_items (
                batch_id TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                input_json TEXT NOT NULL,
                status TEXT NOT NULL,
                job_id TEXT,
                error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(batch_id, item_index),
                FOREIGN KEY(batch_id) REFERENCES match_batches(id) ON DELETE CASCADE
            );
            """
        )
        _ensure_column(conn, "match_batches", "request_key", "TEXT")
        _ensure_column(conn, "job_discovery_runs", "stats_json", "TEXT NOT NULL DEFAULT '{}'")
        # 历史行：已有报告视为双完成；有判分无报告视为报告待补
        conn.execute(
            """
            UPDATE match_runs
            SET judge_status = COALESCE(NULLIF(judge_status, ''), 'done'),
                report_status = CASE
                  WHEN report_json IS NOT NULL AND TRIM(report_json) NOT IN ('', 'null')
                    THEN COALESCE(NULLIF(report_status, ''), 'done')
                  WHEN score IS NOT NULL
                    THEN COALESCE(NULLIF(report_status, ''), 'pending')
                  ELSE COALESCE(NULLIF(report_status, ''), 'idle')
                END
            WHERE judge_status IS NULL OR judge_status = ''
               OR report_status IS NULL OR report_status = ''
            """
        )
        conn.execute(
            """
            UPDATE jobs SET apply_status = CASE COALESCE(NULLIF(apply_status, ''), 'none')
              WHEN 'none' THEN '待决策'
              WHEN 'todo_rewrite' THEN '待改简历'
              WHEN 'todo_apply' THEN '待投'
              WHEN 'applied' THEN '已投'
              WHEN 'interviewing' THEN '面试中'
              WHEN 'closed' THEN '结束'
              ELSE apply_status
            END
            WHERE apply_status IS NULL OR apply_status = ''
               OR apply_status IN ('none','todo_rewrite','todo_apply','applied','interviewing','closed')
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prefs_user ON preferences(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_employment ON jobs(employment_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_match_report_status ON match_runs(report_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_match_batch ON match_runs(batch_id)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_request_key "
            "ON match_batches(user_id, request_key) WHERE request_key IS NOT NULL"
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
