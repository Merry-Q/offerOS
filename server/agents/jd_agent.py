from __future__ import annotations

import re
from typing import Any

from server.llm import llm


SYSTEM = """你是 JD Analyst Agent。分析岗位 JD，输出 JSON：
{
  "title": "岗位标题",
  "level": "级别推断",
  "must_haves": ["强制门槛..."],
  "core_requirements": ["核心要求..."],
  "nice_to_haves": ["加分项..."],
  "risks": ["JD 风险/坑..."],
  "summary": "一句话岗位档案"
}
只输出 JSON。不要编造 JD 未写的硬性门槛。"""


def mock_jd_profile(jd_text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in jd_text.splitlines() if ln.strip()]
    title = lines[0] if lines else "未命名岗位"
    title = re.sub(r"^岗位[：:]\s*", "", title)[:60]
    bullets = [re.sub(r"^[\d\-、\.\)\s]+", "", ln) for ln in lines[1:8] if len(ln) > 4]
    return {
        "title": title,
        "level": "未知",
        "must_haves": bullets[:2] or ["具备相关岗位经验"],
        "core_requirements": bullets[2:5] or ["能独立推进核心任务"],
        "nice_to_haves": bullets[5:7],
        "risks": ["JD 表述可能偏理想化，需用证据核验「独立负责」类要求"],
        "summary": f"{title} · 规则拆解岗位档案",
    }


def analyze_jd(jd_text: str) -> tuple[dict[str, Any], dict]:
    fallback = mock_jd_profile(jd_text)
    data, meta = llm.complete_json(SYSTEM, f"JD 文本：\n{jd_text[:10000]}", fallback)
    if not isinstance(data, dict):
        return fallback, meta
    if not data.get("title"):
        data["title"] = fallback["title"]
    return data, meta
