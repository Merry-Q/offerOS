"""LLM 结果缓存（质量无损：同输入复用同输出）。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from server.db import get_db, loads, utc_now


def normalize_jd_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines()).strip()


def text_hash(text: str) -> str:
    normalized = normalize_jd_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def jd_cache_key(jd_text: str) -> str:
    return f"jd:{text_hash(jd_text)}"


def judge_cache_key(resume_id: str, jd_text: str) -> str:
    return f"judge:v2-four-dim:{resume_id}:{text_hash(jd_text)}"


def report_cache_key(resume_id: str, jd_text: str) -> str:
    return f"report:v2-evidence-flow:{resume_id}:{text_hash(jd_text)}"


def cache_get(key: str) -> Any | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM llm_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE llm_cache SET hits = COALESCE(hits, 0) + 1, last_hit_at = ? WHERE cache_key = ?",
            (utc_now(), key),
        )
        return loads(row["payload_json"], None)


def cache_set(key: str, kind: str, payload: Any) -> None:
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO llm_cache (cache_key, kind, payload_json, created_at, hits, last_hit_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              kind = excluded.kind,
              payload_json = excluded.payload_json,
              created_at = excluded.created_at,
              last_hit_at = excluded.last_hit_at
            """,
            (key, kind, json.dumps(payload, ensure_ascii=False), now, now),
        )


def cache_delete(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (key,))
