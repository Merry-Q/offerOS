"""Resume facts with source quotes; no candidate information outside the file."""
from __future__ import annotations

import hashlib
import re
from typing import Any

SECTION_LABELS = {
    "basic": "基本信息", "intention": "求职期望", "education": "教育经历",
    "work": "工作经历", "internships": "实习经历", "projects": "项目经历",
    "skills": "技能与语言", "awards": "证书与获奖", "other": "其他简历信息",
}
HEADINGS = {
    "基本信息": "basic", "个人信息": "basic", "联系方式": "basic",
    "求职意向": "intention", "求职期望": "intention", "职业目标": "intention",
    "教育经历": "education", "教育背景": "education", "education": "education",
    "工作经历": "work", "工作经验": "work", "职业经历": "work", "work experience": "work",
    "实习经历": "internships", "实习经验": "internships", "internships": "internships",
    "项目经历": "projects", "项目经验": "projects", "projects": "projects",
    "专业技能": "skills", "技能": "skills", "技能特长": "skills", "技能与语言": "skills",
    "语言能力": "skills", "英语能力": "skills", "skills": "skills",
    "证书信息": "awards", "获奖经历": "awards", "荣誉奖项": "awards", "证书与获奖": "awards",
    "自我评价": "other", "个人总结": "other", "自我介绍": "other",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def source_span(raw_text: str, quote: str) -> tuple[int, int] | None:
    """Allow layout whitespace changes, but preserve the actual source characters."""
    if not quote or not _compact(quote):
        return None
    indexes = [i for i, char in enumerate(raw_text) if not char.isspace()]
    compact_raw = "".join(raw_text[i] for i in indexes)
    needle = _compact(quote)
    start = compact_raw.find(needle)
    if start < 0:
        return None
    return indexes[start], indexes[start + len(needle) - 1] + 1


def validate_sections(sections: Any, raw_text: str) -> dict[str, list[dict]]:
    """Only retain values and quotations present in the uploaded resume."""
    result: dict[str, list[dict]] = {key: [] for key in SECTION_LABELS}
    if not isinstance(sections, dict):
        return result
    seen = set()
    for key in result:
        records = sections.get(key)
        if not isinstance(records, list):
            continue
        for record in records[:60]:
            if not isinstance(record, dict):
                continue
            value, quote = record.get("value"), record.get("quote")
            if not isinstance(value, str) or not isinstance(quote, str):
                continue
            value, quote = value.strip(), quote.strip()
            if not value or len(value) > 6000 or len(quote) > 8000:
                continue
            span = source_span(raw_text, quote)
            if span is None or _compact(value) not in _compact(quote):
                continue
            actual = raw_text[span[0]:span[1]]
            fingerprint = (key, _compact(value))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            label = str(record.get("label") or SECTION_LABELS[key])[:40]
            evidence_id = "ev_" + hashlib.sha256(f"{key}:{value}:{actual}".encode()).hexdigest()[:12]
            result[key].append({
                "id": evidence_id, "label": label, "value": value, "quote": actual,
                "line_start": raw_text.count("\n", 0, span[0]) + 1,
                "line_end": raw_text.count("\n", 0, span[1]) + 1,
            })
    return result


def rule_sections(raw_text: str) -> dict[str, list[dict]]:
    """Conservative section splitting when a model is unavailable or old data lacks facts."""
    sections: dict[str, list[dict]] = {key: [] for key in SECTION_LABELS}
    current = "basic"
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections[current].append({"label": SECTION_LABELS[current], "value": text, "quote": text})
        lines.clear()

    for line in raw_text.splitlines():
        heading = re.sub(r"^[\s#一二三四五六七八九十\d、.．]+", "", line).strip().rstrip(":：").lower()
        key = HEADINGS.get(heading)
        if key:
            flush()
            current = key
        elif line.strip():
            lines.append(line)
        elif lines:
            flush()
    flush()

    # Explicit contact fields and the heading line are useful even without a model.
    basic_text = "\n".join(r["value"] for r in sections["basic"])
    basic = []
    first_line = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")
    first_parts = re.split(r"[|｜]", first_line)
    name = first_parts[0].strip()
    if 1 < len(name) <= 24 and not re.search(r"[：:@\d]|简历|resume", name, re.I):
        basic.append({"label": "姓名 / 简历标题", "value": name, "quote": first_line})
        if len(first_parts) > 1 and first_parts[1].strip():
            basic.append({"label": "职业方向", "value": first_parts[1].strip(), "quote": first_line})
    for label, pattern in (
        ("邮箱", r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
        ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ):
        for match in re.finditer(pattern, basic_text):
            basic.append({"label": label, "value": match.group(), "quote": match.group()})
    if basic:
        # Keep unclassified header text too; contact extraction never discards facts.
        sections["basic"] = basic + sections["basic"]
    # Split common resume header lines into fields without synthesizing values.
    for key in ("education", "work", "internships"):
        expanded = []
        for record in sections[key]:
            block_lines = record["value"].splitlines()
            header = block_lines[0]
            parts = [part.strip() for part in re.split(r"[，,|｜]", header) if part.strip()]
            if len(parts) >= 3:
                # Labels that cannot be determined safely stay as original text.
                for part in parts:
                    label = "经历信息"
                    if key == "education":
                        if re.fullmatch(r"本科|硕士|博士|学士|大专|专科|高中|MBA|PhD", part, re.I):
                            label = "学历"
                        elif re.search(r"(?:19|20)\d{2}", part):
                            label = "就读时间"
                        elif re.search(r"大学|学院|学校|university|college|school", part, re.I):
                            label = "学校"
                        else:
                            label = "专业 / 教育信息"
                    elif re.fullmatch(r"(?:19|20)\d{2}(?:[./年]\d{1,2}月?)?(?:\s*[—–\-~～至]\s*(?:(?:19|20)\d{2}(?:[./年]\d{1,2}月?)?|今|现在|present))?", part, re.I):
                        label = "实习时间" if key == "internships" else "任职时间"
                    elif re.search(r"(?:经理|工程师|专员|总监|实习生|设计师|分析师|负责人)$|\b(?:manager|engineer|designer|analyst|lead)$", part, re.I):
                        label = "职位"
                    elif re.search(r"(?:公司|科技|集团|软件|事务所)(?:（[^）]*）|\([^)]*\))?$|\b(?:inc|ltd|llc|corp)\.?$", part, re.I):
                        label = "公司"
                    expanded.append({"label": label, "value": part, "quote": header})
                if len(block_lines) > 1:
                    body = "\n".join(block_lines[1:])
                    expanded.append({"label": "经历与成果", "value": body, "quote": body})
            else:
                expanded.append(record)
        sections[key] = expanded
    return validate_sections(sections, raw_text)


def attach_resume_evidence(profile: dict, raw_text: str, *, meta: dict | None = None) -> dict:
    """Use the same validated facts for the archive and downstream matching."""
    result = dict(profile)
    validated = validate_sections(result.get("resume_sections"), raw_text)
    rules = rule_sections(raw_text)
    for key in validated:
        if not validated[key]:
            validated[key] = rules[key]
    result["resume_sections"] = validated
    result["evidence_version"] = 1
    if meta is not None:
        result["parse_meta"] = {"used": bool(meta.get("used")), "reason": str(meta.get("reason") or "")[:300]}
    facts = [record for records in validated.values() for record in records]
    result["evidence"] = list(dict.fromkeys(record["quote"] for record in facts))
    result["knowledge_skills"] = [
        {"name": r["value"], "evidence": r["quote"], "source": "简历"} for r in validated["skills"]
    ]
    result["skills"] = [r["value"] for r in validated["skills"]]
    result["work_experience"] = [
        {"name": r["label"], "evidence": r["quote"], "source": "简历"}
        for key in ("work", "internships", "projects") for r in validated[key]
    ]
    # Generated persona descriptions are not resume facts.
    result["core_abilities"] = []
    result["personality_traits"] = []
    result["suitable_roles"] = []
    result["strengths"] = []
    result["weak"] = []
    result["years"] = "unknown"
    result["summary"] = "仅依据当前简历原文建立档案；未写出的能力按未具备处理。"
    return result
