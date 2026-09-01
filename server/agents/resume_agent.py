from __future__ import annotations

from typing import Any

from server.llm import llm


SYSTEM = """你是 Resume Analyst Agent。根据简历文本生成可编辑的职场人物画像，不要编造无法从文本支持的经历。
字段：
{
  "summary": "一句话能力画像",
  "knowledge_skills": [{"name":"知识或技能","evidence":"简历原文证据","source":"简历"}],
  "work_experience": [{"name":"经验主题","evidence":"简历原文证据","source":"简历"}],
  "core_abilities": [{"name":"核心能力","evidence":"简历原文证据","source":"简历"}],
  "personality_traits": [{"name":"个性特质","evidence":"只能根据行为证据推断","source":"AI推断"}],
  "suitable_roles": [{"role":"职位","industries":["行业"],"reason":"理由"}],
  "strengths": ["..."],
  "weak": ["..."],
  "evidence": ["可追溯证据要点..."],
  "skills": ["..."],
  "years": "推断的年限描述或 unknown"
}
只输出 JSON。"""


def mock_profile(raw_text: str, file_name: str) -> dict[str, Any]:
    snippet = " ".join((raw_text or "").split())[:180]
    return {
        "summary": f"基于《{file_name}》的能力画像（规则拆解）",
        "knowledge_skills": [],
        "work_experience": [{"name": "项目与工作经历", "evidence": snippet, "source": "简历"}] if snippet else [],
        "core_abilities": [],
        "personality_traits": [],
        "suitable_roles": [],
        "strengths": [
            "能从简历中识别到项目与结果表述" if snippet else "简历文本较短，待补充项目结果",
            "具备可继续匹配的基础素材",
        ],
        "weak": ["独立 0→1 / 量化结果可能表述不足，需在面试中补强"],
        "evidence": [snippet or "（文本为空，仅有文件名占位）", f"来源文件：{file_name}"],
        "skills": [],
        "years": "unknown",
    }


def analyze_resume(raw_text: str, file_name: str) -> tuple[dict[str, Any], dict]:
    fallback = mock_profile(raw_text, file_name)
    user = f"文件名：{file_name}\n\n简历文本：\n{(raw_text or '')[:12000]}"
    data, meta = llm.complete_json(SYSTEM, user, fallback)
    if not isinstance(data, dict):
        return fallback, meta
    for key in (
        "summary", "knowledge_skills", "work_experience", "core_abilities",
        "personality_traits", "suitable_roles", "strengths", "weak", "evidence"
    ):
        if key not in data:
            data[key] = fallback[key]
    return data, meta
