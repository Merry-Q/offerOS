from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from server.auth import get_current_user, require_admin
from server.db import dumps, get_db, loads, utc_now

router = APIRouter(tags=["analytics"])


class TrackBody(BaseModel):
    event: str = Field(min_length=1, max_length=80)
    props: dict[str, Any] = Field(default_factory=dict)


def track_event(event: str, props: dict[str, Any] | None = None, user_id: str | None = None) -> None:
    safe = {
        k: v
        for k, v in (props or {}).items()
        if k.lower() not in ("api_key", "key", "token", "authorization", "password")
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO analytics_events (event, props_json, user_id, created_at) VALUES (?, ?, ?, ?)",
            (event, dumps(safe), user_id, utc_now()),
        )


@router.post("/analytics/track")
def track(body: TrackBody, user: dict = Depends(get_current_user)):
    track_event(body.event, body.props, user_id=user["id"])
    return {"ok": True}


@router.get("/analytics/summary")
def summary(_: dict = Depends(require_admin)):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM analytics_events").fetchone()["c"]
        by_event = conn.execute(
            "SELECT event, COUNT(*) AS c FROM analytics_events GROUP BY event ORDER BY c DESC"
        ).fetchall()
        recent = conn.execute(
            "SELECT id, event, props_json, created_at FROM analytics_events ORDER BY id DESC LIMIT 100"
        ).fetchall()
        resumes = conn.execute("SELECT COUNT(*) AS c FROM resumes").fetchone()["c"]
        parsed = conn.execute(
            "SELECT COUNT(*) AS c FROM resumes WHERE status = 'parsed'"
        ).fetchone()["c"]
        jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        matches = conn.execute("SELECT COUNT(*) AS c FROM match_runs").fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

        def count_event(name: str) -> int:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM analytics_events WHERE event = ?", (name,)
            ).fetchone()["c"]

        app_open = count_event("app_open")
        onboard_complete = count_event("onboard_complete")
        match_start = count_event("match_start")
        report_generated = count_event("report_generated")
        llm_used = conn.execute(
            "SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'llm_mode' AND props_json LIKE '%\"llm_used\": true%'"
        ).fetchone()["c"]
        llm_mode_total = count_event("llm_mode")

    return {
        "totals": {
            "events": total,
            "users": users,
            "resumes": resumes,
            "parsed_resumes": parsed,
            "jobs": jobs,
            "match_runs": matches,
        },
        "funnel": {
            "app_open": app_open,
            "onboard_complete": onboard_complete,
            "match_start": match_start,
            "report_generated": report_generated,
        },
        "llm": {
            "mode_events": llm_mode_total,
            "used_true": llm_used,
            "used_rate": (llm_used / llm_mode_total) if llm_mode_total else 0,
        },
        "by_event": [{"event": r["event"], "count": r["c"]} for r in by_event],
        "recent": [
            {
                "id": r["id"],
                "event": r["event"],
                "props": loads(r["props_json"], {}),
                "created_at": r["created_at"],
            }
            for r in recent
        ],
    }
