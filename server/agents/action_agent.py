from __future__ import annotations

import json
from typing import Any

from server.llm import llm


SYSTEM = """你是 Career Action Agent。不重新评分。根据判分结果与证据输出六模块报告 JSON：
{
  "conclusion": "岗位结论补充说明",
  "match_table": [{"requirement": "...", "evidence": "...", "strength": "强|中|弱"}],
  "gaps_detail": [{"severity": "fatal|important|fixable", "text": "..."}],
  "resume_rewrite": [{"original": "...", "problem": "...", "rewrite": "..."}],
  "interview": [{"question": "...", "framework": "..."}]
}
只输出 JSON。不要改动已有分数。"""


def mock_report(judge: dict, resume_profile: dict, jd_profile: dict) -> dict[str, Any]:
    evidence = (resume_profile.get("evidence") or ["（待补充证据）"])[0]
    reqs = (jd_profile.get("core_requirements") or jd_profile.get("must_haves") or ["核心岗位要求"])[:4]
    table = []
    for i, req in enumerate(reqs):
        strength = "强" if i < 2 else ("中" if i == 2 else "弱")
        table.append({"requirement": req, "evidence": evidence, "strength": strength})
    return {
        "conclusion": judge.get("one_liner") or "已生成行动方案。",
        "match_table": table,
        "gaps_detail": judge.get("gaps") or [],
        "resume_rewrite": [
            {
                "original": evidence[:80],
                "problem": "角色边界与方法不够清晰，难证明独立负责",
                "rewrite": f"作为负责人推进相关事项，明确目标与方法，并沉淀可验证结果。原文要点：{evidence[:60]}",
            }
        ],
        "interview": [
            {
                "question": "如何证明你能独立负责关键模块？",
                "framework": "背景约束 → 你做的决策 → 可验证结果 → 复盘改进",
            },
            {
                "question": "讲一次跨团队推动的经历",
                "framework": "冲突点 → 机制/方法 → 结果与因果链",
            },
        ],
    }


def build_action_report(judge: dict, resume_profile: dict, jd_profile: dict) -> tuple[dict[str, Any], dict]:
    fallback = mock_report(judge, resume_profile, jd_profile)
    user = {
        "judge": {
            "score": judge.get("score"),
            "level": judge.get("level"),
            "one_liner": judge.get("one_liner"),
            "strengths": judge.get("strengths"),
            "gaps": judge.get("gaps"),
        },
        "resume_profile": resume_profile,
        "jd_profile": jd_profile,
    }
    data, meta = llm.complete_json(SYSTEM, json.dumps(user, ensure_ascii=False), fallback)
    if not isinstance(data, dict):
        return fallback, meta
    for key in ("match_table", "gaps_detail", "resume_rewrite", "interview", "conclusion"):
        if key not in data:
            data[key] = fallback[key]
    return data, meta
