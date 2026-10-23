from __future__ import annotations

import json
from typing import Any

from server.config import settings
from server.llm import llm


SYSTEM = """你是 Match Judge Agent，唯一有权评分。根据 JD 档案、候选人画像输出 JSON：
{
  "dims": {"knowledge_skills": 0-100, "work_experience": 0-100, "core_abilities": 0-100, "personality_traits": 0-100},
  "threshold": 0-100,
  "hard_gate_warnings": [{"gate":"专业|学历|经验|语言","requirement":"要求","candidate":"候选人现状","blocked":true}],
  "strengths": ["最多3条"],
  "gaps": [{"severity": "fatal|important|fixable", "text": "..."}],
  "one_liner": "一句话结论",
  "level_hint": "保|稳|冲|不建议投"
}
规则：
- 综合匹配度加权：知识技能35% + 工作经验25% + 核心能力25% + 个性特质15%。
- 硬门槛不修改分数和档位。即使存在阻塞，也按加权原分给出保/稳/冲/不建议投，并单独警示。
- gaps 2-4 条即可，点出关键风险。
- 不要编造简历没有的证据。
- 只评估当前简历；候选人仅提供本地从简历提取的固定职业标签；不提供原文或身份信息。未写出的能力或资格按不具备处理，不推断隐藏能力，不要求用户补充简历外经历。
只输出 JSON。"""


def _clamp(n: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        v = 50
    return max(lo, min(hi, v))


def apply_threshold_correction(raw: int, threshold: int) -> int:
    """兼容旧调用；v2.1 起硬门槛只警示，不再修改加权分。"""
    return raw


def decide_level(score: int, *_args) -> str:
    if score >= 85:
        return "保"
    if score >= 70:
        return "稳"
    if score >= 55:
        return "冲"
    return "不建议投"


def _compact_resume(profile: dict) -> dict[str, Any]:
    from server.privacy import model_signals
    return model_signals(profile)


def _compact_jd(profile: dict) -> dict[str, Any]:
    return {
        "title": profile.get("title"),
        "level": profile.get("level"),
        "must_haves": (profile.get("must_haves") or [])[:6],
        "hard_gates": profile.get("hard_gates") or {},
        "core_requirements": (profile.get("core_requirements") or [])[:6],
        "nice_to_haves": (profile.get("nice_to_haves") or [])[:4],
        "risks": (profile.get("risks") or [])[:3],
        "summary": (profile.get("summary") or "")[:240],
    }


def mock_judge(jd_profile: dict, resume_profile: dict) -> dict[str, Any]:
    from server.job_discovery import quick_score
    from server.privacy import local_signals
    signals = local_signals(resume_profile)
    text = "\n".join(str(x) for key in ("must_haves", "core_requirements", "nice_to_haves") for x in jd_profile.get(key, []))
    quick = quick_score({"title": jd_profile.get("title", ""), "jd_text": text, "graduate_cohort": "未注明"}, resume_profile)
    required = quick["score_basis"]["required_tags"]
    coverage = round(100 * len(quick["matched_tags"]) / len(required)) if required else 0
    dims = {"knowledge_skills": coverage, "work_experience": 0 if quick["gate_warnings"] or not signals["experience_months"] else 60,
            "core_abilities": coverage, "personality_traits": 0}
    return {"dims": dims, "threshold": 70,
        "hard_gate_warnings": [{"gate": "本地识别门槛", "requirement": text, "candidate": "简历未达到", "blocked": True} for text in quick["gate_warnings"]],
        "strengths": quick["matched_tags"],
        "gaps": [{"severity": "important", "text": "简历未具备：" + tag} for tag in quick["missing_tags"]] or [{"severity": "fixable", "text": "未识别的岗位要求仍需逐条审阅"}],
        "one_liner": "当前为本地规则判断，仅覆盖已识别职业标签与门槛；未写出的能力按未具备处理。", "level_hint": "不建议投"}



def judge_match(jd_profile: dict, resume_profile: dict) -> tuple[dict[str, Any], dict]:
    fallback = mock_judge(jd_profile, resume_profile)
    user = {
        "jd_profile": _compact_jd(jd_profile),
        "resume_profile": _compact_resume(resume_profile),
        "formula": "knowledge_skills*0.35 + work_experience*0.25 + core_abilities*0.25 + personality_traits*0.15",
    }
    # 快模型：目标 ≤10s
    data, meta = llm.complete_json(
        SYSTEM,
        json.dumps(user, ensure_ascii=False),
        fallback,
        model=llm.fast_model,
        max_tokens=900,
        temperature=0.1,
        timeout=settings.llm_timeout_fast,
    )
    if not isinstance(data, dict):
        data = fallback

    dims_in = data.get("dims") or fallback["dims"]
    dims = {
        key: _clamp(dims_in.get(key, fallback["dims"][key]))
        for key in ("knowledge_skills", "work_experience", "core_abilities", "personality_traits")
    }
    # Only coarse professional tags leave locally; they provide no personality evidence.
    dims["personality_traits"] = 0
    threshold = _clamp(data.get("threshold", fallback["threshold"]))
    raw = int(
        round(
            dims["knowledge_skills"] * 0.35
            + dims["work_experience"] * 0.25
            + dims["core_abilities"] * 0.25
            + dims["personality_traits"] * 0.15
        )
    )
    score = apply_threshold_correction(raw, threshold)
    gaps = data.get("gaps") or fallback["gaps"]
    if not isinstance(gaps, list):
        gaps = fallback["gaps"]
    level = decide_level(score)

    hard_gate_warnings = data.get("hard_gate_warnings") or []
    for warning in hard_gate_warnings:
        if isinstance(warning, dict) and warning.get("blocked"):
            gaps.append({
                "severity": "fatal",
                "hard_gate": True,
                "gate": warning.get("gate") or "硬门槛",
                "requirement": warning.get("requirement") or "",
                "candidate": warning.get("candidate") or "简历未体现",
                "text": f"{warning.get('gate') or '硬门槛'}：{warning.get('requirement') or '需核验'}",
            })
    result = {
        "dims": [
            {"name": "知识技能", "key": "knowledge_skills", "v": dims["knowledge_skills"], "w": 0.35},
            {"name": "工作经验", "key": "work_experience", "v": dims["work_experience"], "w": 0.25},
            {"name": "核心能力", "key": "core_abilities", "v": dims["core_abilities"], "w": 0.25},
            {"name": "个性特质", "key": "personality_traits", "v": dims["personality_traits"], "w": 0.15},
        ],
        "threshold": threshold,
        "raw": raw,
        "score": score,
        "level": level,
        "one_liner": data.get("one_liner") or fallback["one_liner"],
        "strengths": data.get("strengths") or fallback["strengths"],
        "gaps": gaps,
        "hard_gate_warnings": hard_gate_warnings,
    }
    return result, meta
