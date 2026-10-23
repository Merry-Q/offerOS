"""Local-only feature extraction. Never send resume quotations or identity to a model."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

ROLES = ("AI产品经理", "增长产品经理", "产品经理", "产品助理", "产品运营", "用户运营", "内容运营", "数据分析师", "数据工程师", "后端工程师", "前端工程师", "软件工程师", "算法工程师", "测试工程师", "UI设计师", "UX设计师", "项目经理")
CITIES = ("北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "武汉", "苏州", "西安", "重庆", "天津", "厦门", "合肥", "长沙", "远程")
SKILLS = {
    "SQL": r"\bSQL\b", "Python": r"\bPython\b", "Java": r"\bJava\b", "JavaScript": r"\bJavaScript\b|\bJS\b",
    "TypeScript": r"\bTypeScript\b", "React": r"\bReact\b", "Vue": r"\bVue\b",
    "数据分析": r"数据分析|漏斗分析|留存分析", "用户研究": r"用户研究|用户访谈|客户访谈",
    "需求分析": r"需求分析|需求梳理|需求调研", "原型设计": r"原型设计|原型验证|Axure|Figma",
    "PRD": r"\bPRD\b|需求文档", "项目管理": r"项目管理|项目排期|灰度上线",
    "跨团队协作": r"跨团队|跨职能|协调研发|协同研发", "A/B测试": r"A/B|AB测试|实验设计",
    "机器学习": r"机器学习|\bmachine learning\b", "大模型应用": r"大模型|\bLLM\b|\bRAG\b|智能体",
    "英语": r"英语|英文协作|English", "SaaS": r"\bSaaS\b|企业客户门户|企业服务",
    "增长": r"用户增长|增长实验|获客|转化率", "运营": r"用户运营|内容运营|社群运营",
}


def _positive(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text, re.I):
        prefix = text[max(0, match.start()-10):match.start()]
        if not re.search(r"(?:没有|不具备|不会|不懂|缺少|无|未掌握|未使用)[^，。；\n]{0,8}$", prefix):
            return True
    return False


def local_signals(profile: dict) -> dict[str, Any]:
    sections = profile.get("resume_sections") or {}
    def text(keys):
        return "\n".join(str(row.get("value") or "") for key in keys for row in sections.get(key, []) if isinstance(row, dict))
    role_text = text(("basic", "intention", "work", "internships"))
    roles = [role for role in ROLES if role.lower() in role_text.lower()]
    skill_rows = [row for key in ("skills", "work", "internships", "projects") for row in sections.get(key, []) if isinstance(row, dict)
                  and not re.search(r"公司|学校|时间|日期|姓名|邮箱|手机号", str(row.get("label") or ""))]
    skill_text = "\n".join(str(row.get("value") or "") for row in skill_rows)
    skills = [name for name, pattern in SKILLS.items() if _positive(skill_text, pattern)]
    edu = text(("education",))
    degree = next((label for label in ("博士", "硕士", "本科", "大专", "高中") if label in edu), "未体现")
    edu_years = re.findall(r"(?:19|20)\d{2}", edu)
    graduate_year = max(map(int, edu_years)) if edu_years else None
    # Local dates are coarsened before transmission. No exact timeline leaves this module.
    intervals = []
    for key in ("work",):
        for row in sections.get(key, []):
            value = str(row.get("value") or "")
            for match in re.finditer(r"((?:19|20)\d{2})(?:[./年](\d{1,2})月?)?\s*[—–\-~～至]\s*((?:19|20)\d{2}|今|现在|present)(?:[./年](\d{1,2})月?)?", value, re.I):
                start = int(match[1])*12 + int(match[2] or 1)
                now = datetime.now()
                end = (int(match[3])*12 + int(match[4] or 1)) if match[3].isdigit() else now.year*12+now.month
                if start <= end <= now.year*12+now.month:
                    intervals.append((start, end))
    months = set(month for start, end in intervals for month in range(start, end+1))
    years = len(months)/12
    bucket = "未体现" if not intervals else "0–1年" if years < 1 else "1–3年" if years < 3 else "3–5年" if years < 5 else "5年以上"
    return {"roles": roles[:3], "skills": skills, "degree": degree, "experience_bucket": bucket,
            "experience_months": len(months), "graduate_year": graduate_year}


def model_signals(profile: dict) -> dict:
    signals = local_signals(profile)
    return {key: signals[key] for key in ("roles", "skills", "degree", "experience_bucket")}


def scrub_contact(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已移除]", text)
    text = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[电话已移除]", text)
    text = re.sub(r"(?<!\w)\d{6}(?:19|20)\d{2}\d{4}\d{3}[\dXx](?!\w)", "[证件号已移除]", text)
    return text


def outbound_prompt(prompt: str) -> str:
    """Defense in depth; candidate-bearing call sites must use model_signals first."""
    try:
        obj = json.loads(prompt)
    except (ValueError, TypeError):
        return scrub_contact(prompt)
    def clean(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in {"raw_text", "resume_sections", "file_name", "file_path", "transcript", "evidence_pool"}:
                    continue
                if key in {"resume_profile", "profile", "candidate"} and isinstance(item, dict):
                    allowed = model_signals(item) if "resume_sections" in item else {
                        "roles": [x for x in item.get("roles", []) if x in ROLES],
                        "skills": [x for x in item.get("skills", []) if x in SKILLS],
                        "degree": item.get("degree") if item.get("degree") in {"博士","硕士","本科","大专","高中","未体现"} else "未体现",
                        "experience_bucket": item.get("experience_bucket") if item.get("experience_bucket") in {"未体现","0–1年","1–3年","3–5年","5年以上"} else "未体现",
                    }
                    result[key] = allowed
                else:
                    result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        return scrub_contact(value) if isinstance(value, str) else value
    return json.dumps(clean(obj), ensure_ascii=False)
