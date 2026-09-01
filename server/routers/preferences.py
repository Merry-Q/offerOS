from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from server.auth import get_current_user
from server.db import dumps, get_db, loads, utc_now
from server.routers.analytics import track_event

router = APIRouter(tags=["preferences"])


class PreferenceBody(BaseModel):
    name: str | None = Field(None, max_length=120)
    city: str | None = None
    pay: str | None = None
    company: str | None = None
    goal: str | None = None
    direction: str | None = None
    level: str | None = None
    hard_constraint: str | None = None
    allow_cross_resume: bool | None = None
    chips: list[str] | None = None


def _serialize(row) -> dict[str, Any]:
    d = dict(row)
    d["chips"] = loads(d.pop("chips_json", None), [])
    allow = d.get("allow_cross_resume")
    d["allow_cross_resume"] = True if allow is None else bool(allow)
    d["direction"] = d.get("direction") or ""
    d["level"] = d.get("level") or ""
    d["hard_constraint"] = d.get("hard_constraint") or ""
    return d


def _latest_pref(conn, user_id: str):
    return conn.execute(
        "SELECT * FROM preferences WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()


@router.get("/preferences")
def get_preferences(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM preferences WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    items = [_serialize(r) for r in rows]
    return {"items": items, "latest": items[0] if items else None}


@router.put("/preferences")
def upsert_preferences(body: PreferenceBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    now = utc_now()
    data = body.model_dump(exclude_unset=True)

    with get_db() as conn:
        existing = _latest_pref(conn, uid)
        if existing:
            name = data.get("name", existing["name"]) or existing["name"] or "默认偏好"
            city = data.get("city", existing["city"]) if "city" in data else (existing["city"] or "")
            pay = data.get("pay", existing["pay"]) if "pay" in data else (existing["pay"] or "")
            company = data.get("company", existing["company"]) if "company" in data else (existing["company"] or "")
            goal = data.get("goal", existing["goal"]) if "goal" in data else (existing["goal"] or "")
            direction = (
                data.get("direction", existing["direction"])
                if "direction" in data
                else (existing["direction"] or "")
            )
            level = data.get("level", existing["level"]) if "level" in data else (existing["level"] or "")
            hard_constraint = (
                data.get("hard_constraint", existing["hard_constraint"])
                if "hard_constraint" in data
                else (existing["hard_constraint"] or "")
            )
            if "allow_cross_resume" in data:
                allow = 1 if data["allow_cross_resume"] else 0
            else:
                allow = (
                    existing["allow_cross_resume"]
                    if existing["allow_cross_resume"] is not None
                    else 1
                )
            if "chips" in data:
                chips_json = dumps(data["chips"] or [])
            else:
                chips_json = existing["chips_json"] or dumps([])

            conn.execute(
                """
                UPDATE preferences SET
                  name = ?, city = ?, pay = ?, company = ?, goal = ?,
                  direction = ?, level = ?, hard_constraint = ?,
                  allow_cross_resume = ?, chips_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    city or "",
                    pay or "",
                    company or "",
                    goal or "",
                    direction or "",
                    level or "",
                    hard_constraint or "",
                    allow,
                    chips_json,
                    now,
                    existing["id"],
                ),
            )
            row = conn.execute("SELECT * FROM preferences WHERE id = ?", (existing["id"],)).fetchone()
            created = False
        else:
            pref_id = "pref_" + uuid.uuid4().hex[:10]
            name = (data.get("name") or "默认偏好").strip() or "默认偏好"
            allow = 1 if data.get("allow_cross_resume", True) else 0
            conn.execute(
                """
                INSERT INTO preferences (
                  id, user_id, name, city, pay, company, goal, chips_json,
                  direction, level, hard_constraint, allow_cross_resume,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pref_id,
                    uid,
                    name,
                    data.get("city") or "",
                    data.get("pay") or "",
                    data.get("company") or "",
                    data.get("goal") or "",
                    dumps(data.get("chips") or []),
                    data.get("direction") or "",
                    data.get("level") or "",
                    data.get("hard_constraint") or "",
                    allow,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM preferences WHERE id = ?", (pref_id,)).fetchone()
            created = True

    track_event(
        "preference_upsert",
        {"created": created, "fields": list(data.keys())},
        user_id=uid,
    )
    return _serialize(row)
