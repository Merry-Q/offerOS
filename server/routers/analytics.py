from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.auth import get_current_user, require_admin
from server.db import dumps, get_db, loads, utc_now

router = APIRouter(tags=["analytics"])

RANGE_CHOICES = {"1d", "7d", "30d", "all"}


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


def _parse_since(range_key: str) -> str | None:
    if range_key == "all":
        return None
    days = {"1d": 1, "7d": 7, "30d": 30}.get(range_key, 7)
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 4)


def _step_rates(counts: list[int]) -> list[float | None]:
    """逐步转化率：相对上一步；第一步为 None。"""
    out: list[float | None] = []
    for i, c in enumerate(counts):
        if i == 0:
            out.append(None)
        else:
            out.append(_rate(c, counts[i - 1]))
    return out


def _unique_users(
    conn,
    event: str,
    *,
    since: str | None = None,
    until: str | None = None,
    user_ids: set[str] | None = None,
) -> set[str]:
    sql = (
        "SELECT DISTINCT user_id FROM analytics_events "
        "WHERE event = ? AND user_id IS NOT NULL AND user_id != ''"
    )
    params: list[Any] = [event]
    if since:
        sql += " AND created_at >= ?"
        params.append(since)
    if until:
        sql += " AND created_at < ?"
        params.append(until)
    rows = conn.execute(sql, params).fetchall()
    found = {r["user_id"] for r in rows}
    if user_ids is not None:
        found &= user_ids
    return found


def _users_with_event_after(
    conn,
    event: str,
    cohort_register_at: dict[str, str],
) -> set[str]:
    """队列用户中，在各自注册时间之后发生过某事件的人数。"""
    if not cohort_register_at:
        return set()
    ids = list(cohort_register_at.keys())
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT user_id, MIN(created_at) AS first_at
        FROM analytics_events
        WHERE event = ? AND user_id IN ({placeholders})
        GROUP BY user_id
        """,
        [event, *ids],
    ).fetchall()
    out: set[str] = set()
    for r in rows:
        uid = r["user_id"]
        if r["first_at"] and r["first_at"] >= cohort_register_at.get(uid, ""):
            out.add(uid)
    return out


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 1)
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return round(sorted_vals[f], 1)
    return round(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f), 1)


SCORE_BUCKETS = [
    ("0-39", 0, 39),
    ("40-59", 40, 59),
    ("60-74", 60, 74),
    ("75-84", 75, 84),
    ("85-100", 85, 100),
]

LEVEL_ORDER = ["保", "稳", "冲", "不建议投"]


def _day_list(since: str | None, range_key: str) -> list[str]:
    """生成按日横坐标；all 默认最近 30 天，避免图表过长。"""
    end = datetime.now(timezone.utc).date()
    if range_key == "1d":
        start = end
    elif range_key == "7d":
        start = end - timedelta(days=6)
    elif range_key == "30d":
        start = end - timedelta(days=29)
    else:
        start = end - timedelta(days=29)
        if since:
            try:
                since_d = datetime.fromisoformat(since.replace("Z", "+00:00")).date()
                # all：最多展示 30 天，若 since 更近则用 since
                start = max(since_d, start)
            except ValueError:
                pass
    days: list[str] = []
    cur = start
    while cur <= end:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _build_quality(conn, since: str | None, health: dict) -> dict[str, Any]:
    time_sql = " AND created_at >= ?" if since else ""
    params: list[Any] = [since] if since else []

    rows = conn.execute(
        f"SELECT score, level, version FROM match_runs WHERE 1=1{time_sql}",
        params,
    ).fetchall()

    level_counts = {k: 0 for k in LEVEL_ORDER}
    bucket_counts = {label: 0 for label, _, _ in SCORE_BUCKETS}
    scores: list[float] = []
    rematch_versions = 0

    for r in rows:
        level = (r["level"] or "").strip() or "未知"
        if level not in level_counts:
            level_counts[level] = 0
        level_counts[level] += 1
        try:
            score = float(r["score"])
            scores.append(score)
            for label, lo, hi in SCORE_BUCKETS:
                if lo <= score <= hi:
                    bucket_counts[label] += 1
                    break
        except (TypeError, ValueError):
            pass
        try:
            if int(r["version"] or 1) > 1:
                rematch_versions += 1
        except (TypeError, ValueError):
            pass

    total = len(rows)
    scores_sorted = sorted(scores)
    judge_rows = conn.execute(
        f"""
        SELECT props_json FROM analytics_events
        WHERE event = 'judge_done'{time_sql}
        """,
        params,
    ).fetchall()
    judge_llm_true = 0
    for row in judge_rows:
        props = loads(row["props_json"], {})
        if props.get("llm_used") is True:
            judge_llm_true += 1

    rematch_events = conn.execute(
        f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'rematch'{time_sql}",
        params,
    ).fetchone()["c"]
    match_starts = conn.execute(
        f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'match_start'{time_sql}",
        params,
    ).fetchone()["c"]

    return {
        "match_runs": total,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "median_score": _percentile(scores_sorted, 0.5),
        "level_distribution": [
            {"level": k, "count": level_counts.get(k, 0), "rate": _rate(level_counts.get(k, 0), total)}
            for k in LEVEL_ORDER
        ]
        + (
            [
                {
                    "level": k,
                    "count": v,
                    "rate": _rate(v, total),
                }
                for k, v in level_counts.items()
                if k not in LEVEL_ORDER
            ]
            if any(k not in LEVEL_ORDER for k in level_counts)
            else []
        ),
        "score_buckets": [
            {"bucket": label, "count": bucket_counts[label], "rate": _rate(bucket_counts[label], total)}
            for label, _, _ in SCORE_BUCKETS
        ],
        "rematch_runs": rematch_versions,
        "rematch_rate": _rate(rematch_versions, total),
        "rematch_events": rematch_events,
        "rematch_event_rate": _rate(rematch_events, match_starts),
        "parse_fail_rate": health.get("parse_fail_rate"),
        "parse_fail": health.get("parse_fail"),
        "parse_success": health.get("parse_success"),
        "duration_p50_ms": health.get("duration_p50_ms"),
        "duration_p95_ms": health.get("duration_p95_ms"),
        "judge_llm_rate": _rate(judge_llm_true, len(judge_rows)),
        "judge_events": len(judge_rows),
    }


def _build_usage(conn, since: str | None, range_key: str, health: dict, overview: dict) -> dict[str, Any]:
    days = _day_list(since, range_key)
    day_set = set(days)
    # 取稍宽一点再过滤，避免时区边界漏数
    fetch_since = days[0] if days else since

    def empty_series() -> dict[str, int]:
        return {d: 0 for d in days}

    series_events = {
        "auth_register": empty_series(),
        "auth_login": empty_series(),
        "match_start": empty_series(),
        "report_generated": empty_series(),
        "rematch": empty_series(),
        "llm_used": empty_series(),
    }

    params: list[Any] = []
    sql = "SELECT event, props_json, created_at FROM analytics_events WHERE 1=1"
    if fetch_since:
        sql += " AND created_at >= ?"
        params.append(fetch_since)

    for row in conn.execute(sql, params).fetchall():
        day = (row["created_at"] or "")[:10]
        if day not in day_set:
            continue
        ev = row["event"]
        if ev in series_events and ev != "llm_used":
            series_events[ev][day] += 1
        if ev == "llm_mode":
            props = loads(row["props_json"], {})
            if props.get("llm_used") is True:
                series_events["llm_used"][day] += 1

    active_users = set()
    for ev in ("app_open", "auth_login", "match_start", "report_generated"):
        active_users |= _unique_users(conn, ev, since=since)

    match_count = overview.get("matches_in_range") or 0
    report_count = overview.get("reports_in_range") or 0
    nsm = overview.get("nsm_report_users") or 0

    daily = [
        {
            "date": d,
            "registers": series_events["auth_register"][d],
            "logins": series_events["auth_login"][d],
            "matches": series_events["match_start"][d],
            "reports": series_events["report_generated"][d],
            "rematches": series_events["rematch"][d],
            "llm_used": series_events["llm_used"][d],
        }
        for d in days
    ]

    return {
        "daily": daily,
        "active_users": len(active_users),
        "matches_per_active_user": (
            round(match_count / len(active_users), 2) if active_users else 0
        ),
        "reports_per_active_user": (
            round(report_count / len(active_users), 2) if active_users else 0
        ),
        "llm_used_total": health.get("llm_used_true") or 0,
        "llm_used_rate": health.get("llm_used_rate") or 0,
        "match_count": match_count,
        "report_count": report_count,
        "nsm_users": nsm,
        "cost_note": "LLM 次数为成本代理指标（未计真实账单）；公开注册时请盯人均匹配与调用率。",
    }


def _build_insight(
    activation: dict, returning: dict, health: dict, quality: dict | None = None
) -> str:
    tips: list[str] = []
    a_steps = activation.get("steps") or []
    if len(a_steps) >= 2 and a_steps[0]["users"] >= 3:
        onboard_rate = a_steps[1].get("from_prev_rate")
        if onboard_rate is not None and onboard_rate < 0.4:
            tips.append(
                f"新客建库完成率 {(onboard_rate * 100):.0f}%，偏低——优先查简历上传/解析引导。"
            )
    if len(a_steps) >= 4 and a_steps[1]["users"] >= 3:
        first_report = a_steps[3].get("from_prev_rate")
        if a_steps[2]["users"] and first_report is not None and first_report < 0.5:
            tips.append("新客首次匹配后出报告偏少，查匹配失败或中途退出。")
    r_steps = returning.get("steps") or []
    if len(r_steps) >= 2 and r_steps[0]["users"] >= 3:
        match_rate = r_steps[1].get("from_prev_rate")
        if match_rate is not None and match_rate < 0.35:
            tips.append(
                f"回访匹配率 {(match_rate * 100):.0f}%，老客回来后较少发起匹配。"
            )
    fail = health.get("parse_fail_rate") or 0
    if health.get("parse_total", 0) >= 5 and fail >= 0.15:
        tips.append(f"简历解析失败率 {(fail * 100):.0f}%，检查文件格式与解析 Agent。")
    p95 = health.get("duration_p95_ms")
    if p95 is not None and p95 >= 60000:
        tips.append(f"匹配 P95 耗时 {int(p95 / 1000)}s，体验偏慢。")
    if quality and (quality.get("match_runs") or 0) >= 5:
        for item in quality.get("level_distribution") or []:
            if item.get("level") == "不建议投" and (item.get("rate") or 0) >= 0.5:
                tips.append("「不建议投」占比 ≥50%，核对评分是否过严或样本是否偏冷门岗。")
                break
        avg = quality.get("avg_score")
        if avg is not None and avg >= 90:
            tips.append("平均分偏高（≥90），留意评分是否区分度不足。")
    if not tips:
        return "时间窗内暂无明显异常；继续观察新客激活与回访匹配两条漏斗。"
    return tips[0]


@router.get("/analytics/summary")
def summary(
    _: dict = Depends(require_admin),
    range_key: str = Query("7d", alias="range"),
):
    if range_key not in RANGE_CHOICES:
        range_key = "7d"
    since = _parse_since(range_key)

    with get_db() as conn:
        # —— 实体存量（全库，不受时间窗）——
        resumes = conn.execute("SELECT COUNT(*) AS c FROM resumes").fetchone()["c"]
        parsed = conn.execute(
            "SELECT COUNT(*) AS c FROM resumes WHERE status = 'parsed'"
        ).fetchone()["c"]
        jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        matches = conn.execute("SELECT COUNT(*) AS c FROM match_runs").fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

        time_sql = " AND created_at >= ?" if since else ""
        time_params: list[Any] = [since] if since else []

        total_events = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE 1=1{time_sql}",
            time_params,
        ).fetchone()["c"]

        by_event = conn.execute(
            f"""
            SELECT event, COUNT(*) AS c FROM analytics_events
            WHERE 1=1{time_sql}
            GROUP BY event ORDER BY c DESC
            """,
            time_params,
        ).fetchall()

        recent = conn.execute(
            f"""
            SELECT id, event, props_json, user_id, created_at FROM analytics_events
            WHERE 1=1{time_sql}
            ORDER BY id DESC LIMIT 100
            """,
            time_params,
        ).fetchall()

        # —— 北极星：时间窗内出过报告的去重用户 ——
        nsm_users = _unique_users(conn, "report_generated", since=since)
        report_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'report_generated'{time_sql}",
            time_params,
        ).fetchone()["c"]
        match_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'match_start'{time_sql}",
            time_params,
        ).fetchone()["c"]

        # —— 漏斗 A：新用户激活（时间窗内注册队列）——
        reg_sql = (
            "SELECT user_id, MIN(created_at) AS registered_at FROM analytics_events "
            "WHERE event = 'auth_register' AND user_id IS NOT NULL AND user_id != ''"
        )
        reg_params: list[Any] = []
        if since:
            reg_sql += " AND created_at >= ?"
            reg_params.append(since)
        reg_sql += " GROUP BY user_id"
        reg_rows = conn.execute(reg_sql, reg_params).fetchall()
        cohort_register_at = {r["user_id"]: r["registered_at"] for r in reg_rows}
        new_cohort = set(cohort_register_at.keys())

        a_register = len(new_cohort)
        onboarded = _users_with_event_after(conn, "onboard_complete", cohort_register_at)
        matched = _users_with_event_after(conn, "match_start", cohort_register_at) & onboarded
        reported = _users_with_event_after(conn, "report_generated", cohort_register_at) & matched
        a_onboard = len(onboarded)
        a_match = len(matched)
        a_report = len(reported)
        a_counts = [a_register, a_onboard, a_match, a_report]
        a_rates = _step_rates(a_counts)
        a_labels = ["注册", "建库完成", "首次匹配", "首份报告"]
        a_keys = ["register", "onboard", "first_match", "first_report"]
        activation_steps = [
            {
                "key": a_keys[i],
                "label": a_labels[i],
                "users": a_counts[i],
                "from_prev_rate": a_rates[i],
                "from_start_rate": _rate(a_counts[i], a_register) if i > 0 else None,
            }
            for i in range(4)
        ]

        # —— 漏斗 B：回访核心环（窗内活跃且非本窗新注册）——
        open_users = _unique_users(conn, "app_open", since=since)
        login_users = _unique_users(conn, "auth_login", since=since)
        active = open_users | login_users
        returning_cohort = active - new_cohort

        # 优先看已建库老客：有过 onboard_complete 的人
        ever_onboarded = _unique_users(conn, "onboard_complete", since=None)
        returning_ready = returning_cohort & ever_onboarded
        # 若交集为空但有回访，仍用 returning_cohort，避免早期无 onboard 埋点时整页空白
        r_base = returning_ready if returning_ready else returning_cohort

        r_visit = len(r_base)
        matched_r = _unique_users(conn, "match_start", since=since, user_ids=r_base)
        reported_r = _unique_users(conn, "report_generated", since=since, user_ids=matched_r)
        rematched_r = _unique_users(conn, "rematch", since=since, user_ids=reported_r)
        r_match = len(matched_r)
        r_report = len(reported_r)
        r_rematch = len(rematched_r)
        r_counts = [r_visit, r_match, r_report, r_rematch]
        r_rates = _step_rates(r_counts)
        r_labels = ["回访打开/登录", "发起匹配", "生成报告", "重新匹配"]
        r_keys = ["visit", "match", "report", "rematch"]
        returning_steps = [
            {
                "key": r_keys[i],
                "label": r_labels[i],
                "users": r_counts[i],
                "from_prev_rate": r_rates[i],
                "from_start_rate": _rate(r_counts[i], r_visit) if i > 0 else None,
            }
            for i in range(4)
        ]

        # —— 健康护栏（时间窗内）——
        parse_ok = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'resume_parse_success'{time_sql}",
            time_params,
        ).fetchone()["c"]
        parse_fail = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'resume_parse_fail'{time_sql}",
            time_params,
        ).fetchone()["c"]
        parse_total = parse_ok + parse_fail

        llm_mode_total = conn.execute(
            f"SELECT COUNT(*) AS c FROM analytics_events WHERE event = 'llm_mode'{time_sql}",
            time_params,
        ).fetchone()["c"]
        llm_used = conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM analytics_events
            WHERE event = 'llm_mode' AND props_json LIKE '%\"llm_used\": true%'{time_sql}
            """,
            time_params,
        ).fetchone()["c"]

        duration_rows = conn.execute(
            f"""
            SELECT props_json FROM analytics_events
            WHERE event = 'report_generated'{time_sql}
            """,
            time_params,
        ).fetchall()
        durations: list[float] = []
        for row in duration_rows:
            props = loads(row["props_json"], {})
            ms = props.get("duration_ms")
            try:
                if ms is not None:
                    durations.append(float(ms))
            except (TypeError, ValueError):
                pass
        durations.sort()

        health = {
            "parse_success": parse_ok,
            "parse_fail": parse_fail,
            "parse_total": parse_total,
            "parse_fail_rate": _rate(parse_fail, parse_total),
            "llm_mode_events": llm_mode_total,
            "llm_used_true": llm_used,
            "llm_used_rate": _rate(llm_used, llm_mode_total),
            "duration_p50_ms": _percentile(durations, 0.5),
            "duration_p95_ms": _percentile(durations, 0.95),
            "session_report_rate": _rate(report_count, match_count),
        }

        activation = {
            "name": "new_user_activation",
            "title": "新用户激活",
            "cohort_size": a_register,
            "cohort_note": "时间窗内完成注册的用户；后续步骤为注册后是否曾完成（用户去重）",
            "steps": activation_steps,
            "activation_rate": _rate(a_report, a_register),
            "onboard_rate": _rate(a_onboard, a_register),
        }
        returning = {
            "name": "returning_core",
            "title": "回访核心环",
            "cohort_size": r_visit,
            "cohort_note": (
                "时间窗内打开/登录、且非本窗新注册"
                + ("；优先统计已建库用户" if returning_ready else "（暂无建库记录，含全部回访用户）")
            ),
            "excluded_new_registrants": len(active & new_cohort),
            "steps": returning_steps,
            "return_match_rate": _rate(r_match, r_visit),
        }

        overview = {
            "nsm_report_users": len(nsm_users),
            "reports_per_nsm_user": (
                round(report_count / len(nsm_users), 2) if nsm_users else 0
            ),
            "new_activation_rate": activation["activation_rate"],
            "return_match_rate": returning["return_match_rate"],
            "session_report_rate": health["session_report_rate"],
            "reports_in_range": report_count,
            "matches_in_range": match_count,
        }

        quality = _build_quality(conn, since, health)
        usage = _build_usage(conn, since, range_key, health, overview)

        payload = {
            "range": range_key,
            "since": since,
            "overview": overview,
            "activation_funnel": activation,
            "returning_funnel": returning,
            "health": health,
            "quality": quality,
            "usage": usage,
            "insight": _build_insight(activation, returning, health, quality),
            "totals": {
                "events": total_events,
                "users": users,
                "resumes": resumes,
                "parsed_resumes": parsed,
                "jobs": jobs,
                "match_runs": matches,
            },
            "llm": {
                "mode_events": health["llm_mode_events"],
                "used_true": health["llm_used_true"],
                "used_rate": health["llm_used_rate"],
            },
            "by_event": [{"event": r["event"], "count": r["c"]} for r in by_event],
            "recent": [
                {
                    "id": r["id"],
                    "event": r["event"],
                    "props": loads(r["props_json"], {}),
                    "user_id": r["user_id"],
                    "created_at": r["created_at"],
                }
                for r in recent
            ],
        }

    return payload
