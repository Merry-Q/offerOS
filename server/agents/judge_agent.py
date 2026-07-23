from __future__ import annotations

import json
from typing import Any

from server.llm import llm


SYSTEM = """你是 Match Judge Agent，唯一有权评分。根据 JD 档案、候选人画像输出 JSON：
{
  "dims": {"competency": 0-100, "proof": 0-100, "competitiveness": 0-100},
  "threshold": 0-100,
  "strengths": ["..."],
  "gaps": [{"severity": "fatal|important|fixable", "text": "..."}],
  "one_liner": "一句话结论",
  "level_hint": "保|稳|冲|不建议投"
}
规则：
- 综合匹配度加权：胜任40% + 证明25% + 竞争35%；门槛只做修正不进加权。
- 不要编造简历没有的证据。
只输出 JSON。"""


def _clamp(n: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        v = 50
    return max(lo, min(hi, v))


def apply_threshold_correction(raw: int, threshold: int) -> int:
    if threshold >= 90:
        return raw
    if threshold >= 75:
        return max(0, raw - 4)
    if threshold >= 50:
        return max(0, raw - 12)
    if threshold >= 20:
        return min(raw, 55)
    return 0


def decide_level(competency: int, proof: int, competitiveness: int, threshold: int, gaps: list) -> str:
    if threshold < 20:
        return "不建议投"
    fatal = any(g.get("severity") == "fatal" for g in gaps)
    if fatal or threshold < 50:
        return "不建议投"
    if competency >= 85 and proof >= 75 and competitiveness >= 75 and not fatal:
        return "保"
    if 70 <= competency < 85:
        return "稳"
    if competency >= 85:
        return "稳"
    return "冲"


def mock_judge(jd_profile: dict, resume_profile: dict) -> dict[str, Any]:
    evidence = resume_profile.get("evidence") or []
    weak = resume_profile.get("weak") or []
    dims = {
        "competency": 78 if evidence else 62,
        "proof": 74 if len(evidence) >= 2 else 60,
        "competitiveness": 68,
    }
    threshold = 82 if jd_profile.get("must_haves") else 70
    gaps = [{"severity": "important", "text": w} for w in weak[:2]] or [
        {"severity": "fixable", "text": "部分要求需补量化 STAR"}
    ]
    strengths = (resume_profile.get("strengths") or [])[:3] or ["具备可匹配的基础证据"]
    return {
        "dims": dims,
        "threshold": threshold,
        "strengths": strengths,
        "gaps": gaps,
        "one_liner": "核心任务大体可覆盖，部分证明链偏弱；建议投递并优先改简历叙事。",
        "level_hint": "稳",
    }


def judge_match(jd_profile: dict, resume_profile: dict) -> tuple[dict[str, Any], dict]:
    fallback = mock_judge(jd_profile, resume_profile)
    user = {
        "jd_profile": jd_profile,
        "resume_profile": resume_profile,
        "formula": "competency*0.4 + proof*0.25 + competitiveness*0.35",
    }
    data, meta = llm.complete_json(SYSTEM, json.dumps(user, ensure_ascii=False), fallback)
    if not isinstance(data, dict):
        data = fallback

    dims_in = data.get("dims") or fallback["dims"]
    dims = {
        "competency": _clamp(dims_in.get("competency", fallback["dims"]["competency"])),
        "proof": _clamp(dims_in.get("proof", fallback["dims"]["proof"])),
        "competitiveness": _clamp(
            dims_in.get("competitiveness", fallback["dims"]["competitiveness"])
        ),
    }
    threshold = _clamp(data.get("threshold", fallback["threshold"]))
    raw = int(
        round(
            dims["competency"] * 0.4
            + dims["proof"] * 0.25
            + dims["competitiveness"] * 0.35
        )
    )
    score = apply_threshold_correction(raw, threshold)
    gaps = data.get("gaps") or fallback["gaps"]
    if not isinstance(gaps, list):
        gaps = fallback["gaps"]
    level = decide_level(
        dims["competency"], dims["proof"], dims["competitiveness"], threshold, gaps
    )
    if threshold < 20:
        level = "不建议投"
        score = 0

    result = {
        "dims": [
            {"name": "岗位胜任", "key": "competency", "v": dims["competency"], "w": 0.4},
            {"name": "简历证明", "key": "proof", "v": dims["proof"], "w": 0.25},
            {"name": "录用竞争", "key": "competitiveness", "v": dims["competitiveness"], "w": 0.35},
        ],
        "threshold": threshold,
        "raw": raw,
        "score": score,
        "level": level,
        "one_liner": data.get("one_liner") or fallback["one_liner"],
        "strengths": data.get("strengths") or fallback["strengths"],
        "gaps": gaps,
    }
    return result, meta
