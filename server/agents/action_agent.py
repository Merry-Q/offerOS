from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from server.llm import llm
from server.config import settings


SHARED = """你是 OfferOS 的 Career Action Agent（资深求职教练 + 招聘侧面试官视角）。
硬性约束：
1. 不重新评分，不改动 score / level / dims / threshold。
2. 禁止编造简历没有的公司、项目、数据、职级、工具熟练度。
3. 证据不足时明确写「简历未体现 / 需面试补证」，不要用空话填充。
4. 只输出合法 JSON，不要 Markdown，不要解释。
5. 语言：简体中文；语气专业、具体、可执行，避免鸡汤与空泛形容词。
写作：用因果链（要求→证据→缺口→行动）；优先具体动词；避免无证据套话。
"""

SYSTEM_M1 = SHARED + """
本模块只输出：
{
  "conclusion": "string 120-240字，含投递建议/匹配主因/核心风险/投前必做",
  "conclusion_structured": {
    "verdict": "必须与 judge.level 一致：保|稳|冲|不建议投",
    "one_liner": "string",
    "why_fit": ["2-3条"],
    "why_risk": ["2-3条"],
    "decision_advice": "string",
    "next_7_days": ["正好3条，7天内可完成"]
  },
  "score_narrative": {
    "knowledge_skills": "60-120字，点名知识技能证据",
    "work_experience": "60-120字，点名工作经验",
    "core_abilities": "60-120字，点名核心能力证据",
    "personality_traits": "60-120字，只依据行为证据",
    "hard_gates": "说明硬门槛警示，但不得修改原分和档位"
  }
}
"""

SYSTEM_M2 = SHARED + """
本模块只输出：
{
  "match_table": [
    {
      "requirement": "string",
      "source": "must_have|core|nice_to_have",
      "evidence": "string",
      "strength": "强|中|弱|缺失",
      "gap_note": "弱/缺失必填，否则可空字符串"
    }
  ],
  "strengths_detail": [
    {"text": "string", "evidence": "string", "how_to_amplify": "string"}
  ],
  "gaps_detail": [
    {
      "severity": "fatal|important|fixable",
      "text": "string",
      "impact": "string",
      "fix_plan": "string",
      "interview_cover": "string"
    }
  ]
}
质量：
- match_table 至少 6 行；优先覆盖全部 must_haves，再 core，再 nice_to_haves。
- strengths_detail 2-3 条；gaps_detail 3-5 条，可细化 judge.gaps 但不可矛盾。
"""

SYSTEM_M3 = SHARED + """
本模块只输出：
{
  "resume_rewrite": [
    {
      "section": "string",
      "original": "string",
      "problem": "string",
      "rewrite": "60-140字：动作动词+方法/协作对象+可验证结果（禁止伪造精确指标）",
      "why_better": "说明如何对齐该 JD",
      "source_resume": "可选：若引用跨简历证据池，填来源简历名；否则空字符串"
    }
  ]
}
质量：3-4 条；同方向岗位针对句子润色；跨岗位或跨行业时，对完整项目进行结构化改写。
每项增加 "rewrite_scope": "句子润色|项目改写"。优先覆盖 must_have 与关键 gaps。
若提供「可用跨简历证据池」，可引用其中标注来源的真实证据辅助改写建议，禁止编造。
"""

SYSTEM_M4 = SHARED + """
本模块只输出：
{
  "interview": [
    {
      "category": "行为|项目深挖|岗位知识|压力/反问",
      "question": "string",
      "why_asked": "string",
      "framework": "string",
      "sample_outline": "绑定真实经历；不足则写建议先补的证据清单",
      "followups": ["string", "string"],
      "pitfalls": ["string"],
      "source_resume": "可选：若引用跨简历证据池，填来源简历名；否则空字符串"
    }
  ],
  "interview_knowledge": {
    "must_know": ["5-6条"],
    "talking_points": ["正好3条"],
    "questions_to_ask": ["正好3条"]
  }
}
质量：interview 5-8 题；类别尽量覆盖行为/项目/岗位知识/反问。
若提供「可用跨简历证据池」，可在 sample_outline 中引用并标注来源，禁止编造。
"""

# 兼容旧引用名
SYSTEM = SYSTEM_M1


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _compose_conclusion(structured: dict, fallback: str) -> str:
    parts: list[str] = []
    one = (structured.get("one_liner") or "").strip()
    advice = (structured.get("decision_advice") or "").strip()
    why_fit = [str(x).strip() for x in _as_list(structured.get("why_fit")) if str(x).strip()]
    why_risk = [str(x).strip() for x in _as_list(structured.get("why_risk")) if str(x).strip()]
    next_days = [str(x).strip() for x in _as_list(structured.get("next_7_days")) if str(x).strip()]

    if one:
        parts.append(one)
    if why_fit:
        parts.append("匹配主因：" + "；".join(why_fit[:4]) + "。")
    if why_risk:
        parts.append("核心风险：" + "；".join(why_risk[:4]) + "。")
    if advice:
        parts.append(advice)
    if next_days:
        numbered = "；".join(f"{i+1}. {x}" for i, x in enumerate(next_days[:3]))
        parts.append("未来 7 天行动：" + numbered + "。")
    text = "".join(parts).strip()
    return text or fallback


def mock_report(judge: dict, resume_profile: dict, jd_profile: dict) -> dict[str, Any]:
    evidence_list = resume_profile.get("evidence") or ["（待补充证据）"]
    evidence = evidence_list[0]
    must = _as_list(jd_profile.get("must_haves"))
    core = _as_list(jd_profile.get("core_requirements") or jd_profile.get("must_haves"))
    nice = _as_list(jd_profile.get("nice_to_haves"))
    reqs: list[tuple[str, str]] = []
    for r in must:
        reqs.append((str(r), "must_have"))
    for r in core:
        if str(r) not in {x[0] for x in reqs}:
            reqs.append((str(r), "core"))
    for r in nice:
        if str(r) not in {x[0] for x in reqs}:
            reqs.append((str(r), "nice_to_have"))
    if not reqs:
        reqs = [("核心岗位要求", "core")]
    while len(reqs) < 6:
        reqs.append((f"待补充要求 {len(reqs)+1}", "core"))

    table = []
    for i, (req, source) in enumerate(reqs[:8]):
        if i < 2:
            strength, note = "强", ""
        elif i < 4:
            strength, note = "中", "证据偏概括，建议补量化结果"
        elif i < 5:
            strength, note = "弱", "仅部分相关，需在面试补证"
        else:
            strength, note = "缺失", "简历未体现，投前需补项目或诚实降级预期"
        table.append(
            {
                "requirement": req,
                "source": source,
                "evidence": evidence if strength != "缺失" else "简历未体现",
                "strength": strength,
                "gap_note": note,
            }
        )

    strengths = _as_list(resume_profile.get("strengths")) or ["具备可匹配的基础证据"]
    strengths_detail = [
        {
            "text": str(s),
            "evidence": evidence_list[min(i, len(evidence_list) - 1)],
            "how_to_amplify": "在简历首屏与面试开场用 1 个可验证结果放大该优势",
        }
        for i, s in enumerate(strengths[:3])
    ]

    raw_gaps = _as_list(judge.get("gaps")) or [
        {"severity": "fixable", "text": "部分要求需补量化 STAR"}
    ]
    gaps_detail = []
    for g in raw_gaps[:6]:
        if not isinstance(g, dict):
            continue
        gaps_detail.append(
            {
                "severity": g.get("severity") or "important",
                "text": g.get("text") or "存在待补缺口",
                "impact": "可能拉低简历证明分与首轮面试说服力",
                "fix_plan": "用 1 段可验证项目经历补齐角色、方法与结果",
                "interview_cover": "先承认边界，再讲已验证能力与学习闭环",
            }
        )

    level = judge.get("level") or "稳"
    one_liner = judge.get("one_liner") or "核心任务大体可覆盖，部分证明链偏弱；建议投递并优先改简历叙事。"
    structured = {
        "verdict": level,
        "one_liner": one_liner,
        "why_fit": [str(s) for s in strengths[:3]] or ["基础能力与岗位方向大体对齐"],
        "why_risk": [g["text"] for g in gaps_detail[:2]] or ["关键证明链仍偏弱"],
        "decision_advice": f"建议按「{level}」策略处理：先改简历叙事再投，面试重点补证明链。",
        "next_7_days": [
            "按匹配表弱项改写 3 条简历子弹",
            "准备 2 个可深挖项目的 STAR",
            "针对 must_have 缺口列出补证清单",
        ],
    }

    return {
        "conclusion": _compose_conclusion(structured, one_liner),
        "conclusion_structured": structured,
        "score_narrative": {
            "knowledge_skills": "知识技能分反映岗位要求的知识与工具覆盖度，并以简历证据为准。",
            "work_experience": f"工作经验分关注场景、年限与成果。当前证据如：{evidence[:80]}。",
            "core_abilities": "核心能力分关注能否独立完成 JD 中的关键任务与协作闭环。",
            "personality_traits": "个性特质只根据行为证据推断；简历未体现的部分按证据不足处理。",
            "hard_gates": "硬门槛单独警示，不修改加权原分与保稳冲档位。",
        },
        "match_table": table,
        "strengths_detail": strengths_detail,
        "gaps_detail": gaps_detail,
        "resume_rewrite": [
            {
                "section": "项目经历",
                "original": evidence[:120],
                "problem": "角色边界与方法不够清晰，难证明独立负责",
                "rewrite": (
                    f"作为负责人推进相关事项，明确目标、方法与协作对象，并沉淀可验证结果。"
                    f"原文要点：{evidence[:60]}"
                ),
                "why_better": "强化「独立负责 + 方法 + 结果」，直接抬升简历证明分与 must_have 覆盖。",
                "rewrite_scope": "句子润色",
            },
            {
                "section": "成果表述",
                "original": (evidence_list[1] if len(evidence_list) > 1 else evidence)[:120],
                "problem": "结果缺少对比或范围，招聘官难以判断影响量级",
                "rewrite": "围绕目标指标说明基线、动作与结果变化（可用比例/周期/覆盖范围），并补充复盘改进点。",
                "why_better": "让成果可核验，提升与 JD 核心要求的对齐度。",
                "rewrite_scope": "句子润色",
            },
            {
                "section": "技能/职责",
                "original": "负责相关模块推进与跨团队沟通",
                "problem": "职责描述空泛，未对应 JD 关键词",
                "rewrite": "对照 JD 核心要求，用「场景 + 动作 + 产出物」重写职责，避免只写参与/协助。",
                "why_better": "提高关键词命中与初筛通过率。",
                "rewrite_scope": "项目改写",
            },
        ],
        "interview": [
            {
                "category": "行为",
                "question": "如何证明你能独立负责关键模块？",
                "why_asked": "验证 JD 对独立负责/ownership 的硬要求",
                "framework": "背景约束 → 你的决策权 → 方法 → 可验证结果 → 复盘",
                "sample_outline": f"结合经历「{evidence[:50]}」说明你独自拍板的点、协作边界与结果。",
                "followups": ["你当时放弃了什么方案？", "如果结果只有一半，你会怎么迭代？"],
                "pitfalls": ["只说参与协助，没有决策与结果"],
            },
            {
                "category": "项目深挖",
                "question": "讲一次你推动跨团队对齐的经历",
                "why_asked": "考察协同推进与冲突处理",
                "framework": "冲突点 → 机制/方法 → 结果与因果链",
                "sample_outline": "选一个真实跨团队项目，讲清反对意见、你用的对齐机制、最终可验证结果。",
                "followups": ["对方持续反对时你怎么做？", "机制后来沉淀成流程了吗？"],
                "pitfalls": ["把运气或上级施压说成个人能力"],
            },
            {
                "category": "岗位知识",
                "question": "如果让你重新拆解这个岗位的前 30 天目标，你会怎么定？",
                "why_asked": "看你是否理解岗位成功标准",
                "framework": "业务目标 → 关键动作 → 指标 → 风险预案",
                "sample_outline": "结合 JD 核心职责，给出可执行的 30 天里程碑，不要空谈愿景。",
                "followups": ["哪个指标最能证明你入职成功？", "你需要哪些信息才能定目标？"],
                "pitfalls": ["目标过大且不可衡量"],
            },
            {
                "category": "行为",
                "question": "讲一次需求/方案被否决后你如何调整",
                "why_asked": "考察抗压、复盘与学习速度",
                "framework": "否决原因 → 你的判断修正 → 新方案 → 结果",
                "sample_outline": "用真实被打回经历，强调你如何基于反馈重构方案而非硬刚。",
                "followups": ["你如何判断反馈是否正确？", "后来如何避免同类问题？"],
                "pitfalls": ["抱怨他人或推责"],
            },
            {
                "category": "项目深挖",
                "question": "你这份经历里，最能打的成果是什么？因果链是什么？",
                "why_asked": "验证简历证明链是否经得起追问",
                "framework": "目标 → 动作 → 结果 → 归因",
                "sample_outline": f"从「{evidence[:40]}」中挑一个结果，讲清你做了什么、为何有效。",
                "followups": ["去掉你之后结果还会发生吗？", "数据口径如何定义？"],
                "pitfalls": ["只有过程没有结果，或结果无法归因"],
            },
            {
                "category": "压力/反问",
                "question": "你对我们业务/团队最想确认的三个问题是什么？",
                "why_asked": "看候选人是否认真研究岗位与业务",
                "framework": "业务理解 → 角色期待 → 成功标准",
                "sample_outline": "准备关于业务目标、协作方式、成功指标的反问，体现调研深度。",
                "followups": ["你为什么关心这个问题？", "如果答案不理想你还投吗？"],
                "pitfalls": ["只问休假加班等福利问题"],
            },
        ],
        "interview_knowledge": {
            "must_know": [
                "该岗位的核心成功指标是什么",
                "must_have 对应的可验证证据",
                "常见优先级/权衡方法",
                "跨团队对齐机制",
                "项目复盘的因果表述",
                "如何诚实覆盖缺口",
            ],
            "talking_points": [
                "用 1 个最强项目开场，30 秒讲清目标-动作-结果",
                "主动对齐 JD 的 2 条 must_have",
                "提前说明可快补缺口与补齐计划",
            ],
            "questions_to_ask": [
                "这个角色入职 90 天的成功标准是什么？",
                "当前团队最大的瓶颈在业务还是协作？",
                "这个岗位最需要补齐的能力短板是什么？",
            ],
        },
    }


def _normalize_report(data: dict, fallback: dict, judge: dict) -> dict[str, Any]:
    out = dict(fallback)
    for key in (
        "conclusion",
        "conclusion_structured",
        "score_narrative",
        "match_table",
        "strengths_detail",
        "gaps_detail",
        "resume_rewrite",
        "interview",
        "interview_knowledge",
    ):
        if key in data and data[key] not in (None, "", []):
            out[key] = data[key]

    structured = _as_dict(out.get("conclusion_structured"))
    fb_structured = _as_dict(fallback.get("conclusion_structured"))
    for k, v in fb_structured.items():
        if k not in structured or structured.get(k) in (None, "", []):
            structured[k] = v
    if not structured.get("verdict"):
        structured["verdict"] = judge.get("level") or fb_structured.get("verdict") or "稳"
    out["conclusion_structured"] = structured

    conclusion = str(out.get("conclusion") or "").strip()
    if len(conclusion) < 80:
        out["conclusion"] = _compose_conclusion(
            structured, str(fallback.get("conclusion") or judge.get("one_liner") or "")
        )

    score_narrative = _as_dict(out.get("score_narrative"))
    for k, v in _as_dict(fallback.get("score_narrative")).items():
        if not str(score_narrative.get(k) or "").strip():
            score_narrative[k] = v
    out["score_narrative"] = score_narrative

    for list_key in ("match_table", "strengths_detail", "gaps_detail", "resume_rewrite", "interview"):
        items = _as_list(out.get(list_key))
        out[list_key] = items if items else fallback.get(list_key)

    # 兼容旧字段：补齐 match_table / interview / gaps / rewrite 的新键
    norm_table = []
    for row in _as_list(out.get("match_table")):
        if not isinstance(row, dict):
            continue
        norm_table.append(
            {
                "requirement": row.get("requirement") or "",
                "source": row.get("source") or "core",
                "evidence": row.get("evidence") or "",
                "strength": row.get("strength") or "中",
                "gap_note": row.get("gap_note") or "",
            }
        )
    out["match_table"] = norm_table or fallback["match_table"]

    norm_gaps = []
    for g in _as_list(out.get("gaps_detail")):
        if not isinstance(g, dict):
            continue
        norm_gaps.append(
            {
                "severity": g.get("severity") or "important",
                "text": g.get("text") or "",
                "impact": g.get("impact") or "",
                "fix_plan": g.get("fix_plan") or "",
                "interview_cover": g.get("interview_cover") or "",
            }
        )
    out["gaps_detail"] = norm_gaps or fallback["gaps_detail"]

    norm_strengths = []
    for s in _as_list(out.get("strengths_detail")):
        if not isinstance(s, dict):
            continue
        norm_strengths.append(
            {
                "text": s.get("text") or "",
                "evidence": s.get("evidence") or "",
                "how_to_amplify": s.get("how_to_amplify") or "",
            }
        )
    out["strengths_detail"] = norm_strengths or fallback["strengths_detail"]

    norm_rw = []
    for item in _as_list(out.get("resume_rewrite")):
        if not isinstance(item, dict):
            continue
        rw = {
            "section": item.get("section") or "经历",
            "original": item.get("original") or "",
            "problem": item.get("problem") or "",
            "rewrite": item.get("rewrite") or "",
            "why_better": item.get("why_better") or "",
            "rewrite_scope": item.get("rewrite_scope")
            if item.get("rewrite_scope") in ("句子润色", "项目改写")
            else "句子润色",
        }
        src = str(item.get("source_resume") or "").strip()
        if src:
            rw["source_resume"] = src
        norm_rw.append(rw)
    out["resume_rewrite"] = norm_rw or fallback["resume_rewrite"]

    norm_iv = []
    for q in _as_list(out.get("interview")):
        if not isinstance(q, dict):
            continue
        followups = [str(x) for x in _as_list(q.get("followups")) if str(x).strip()]
        pitfalls = [str(x) for x in _as_list(q.get("pitfalls")) if str(x).strip()]
        iv = {
            "category": q.get("category") or "行为",
            "question": q.get("question") or "",
            "why_asked": q.get("why_asked") or "",
            "framework": q.get("framework") or "",
            "sample_outline": q.get("sample_outline") or "",
            "followups": followups,
            "pitfalls": pitfalls,
        }
        src = str(q.get("source_resume") or "").strip()
        if src:
            iv["source_resume"] = src
        norm_iv.append(iv)
    out["interview"] = norm_iv or fallback["interview"]

    knowledge = _as_dict(out.get("interview_knowledge"))
    fb_knowledge = _as_dict(fallback.get("interview_knowledge"))
    out["interview_knowledge"] = {
        "must_know": _as_list(knowledge.get("must_know")) or fb_knowledge.get("must_know") or [],
        "talking_points": _as_list(knowledge.get("talking_points"))
        or fb_knowledge.get("talking_points")
        or [],
        "questions_to_ask": _as_list(knowledge.get("questions_to_ask"))
        or fb_knowledge.get("questions_to_ask")
        or [],
    }
    return out


def _judge_bundle(judge: dict) -> dict[str, Any]:
    return {
        "score": judge.get("score"),
        "level": judge.get("level"),
        "one_liner": judge.get("one_liner"),
        "strengths": judge.get("strengths"),
        "gaps": judge.get("gaps"),
        "dims": judge.get("dims"),
        "threshold": judge.get("threshold"),
        "raw": judge.get("raw"),
    }


def _slice_fallback(fallback: dict, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: fallback.get(k) for k in keys}


def _run_module(
    system: str,
    payload: dict[str, Any],
    fallback_slice: dict[str, Any],
    *,
    max_tokens: int,
) -> tuple[dict[str, Any], dict]:
    data, meta = llm.complete_json(
        system,
        json.dumps(payload, ensure_ascii=False),
        fallback_slice,
        model=llm.action_model,
        max_tokens=max_tokens,
        temperature=0.2,
        timeout=settings.llm_timeout_action,
        disable_thinking=True,
    )
    if not isinstance(data, dict):
        return dict(fallback_slice), meta
    out = dict(fallback_slice)
    for k, v in data.items():
        if v not in (None, "", []):
            out[k] = v
    return out, meta


def _norm_req(text: str) -> str:
    return "".join(str(text or "").lower().split())


def ensure_must_have_coverage(
    report: dict[str, Any],
    jd_profile: dict,
    resume_profile: dict,
) -> dict[str, Any]:
    """程序校验：补齐缺失的 must_haves 行（质量契约，不依赖模型自觉）。"""
    table = [r for r in _as_list(report.get("match_table")) if isinstance(r, dict)]
    covered = {_norm_req(r.get("requirement")) for r in table if r.get("requirement")}
    evidence0 = (_as_list(resume_profile.get("evidence")) or ["简历未体现"])[0]
    for req in _as_list(jd_profile.get("must_haves")):
        req_s = str(req).strip()
        if not req_s:
            continue
        if _norm_req(req_s) in covered:
            continue
        table.append(
            {
                "requirement": req_s,
                "source": "must_have",
                "evidence": "简历未体现",
                "strength": "缺失",
                "gap_note": "硬门槛未覆盖，投前需补项目证据或诚实降级预期",
            }
        )
        covered.add(_norm_req(req_s))
    # 至少 6 行：用 core 补齐
    if len(table) < 6:
        for req in _as_list(jd_profile.get("core_requirements")):
            req_s = str(req).strip()
            if not req_s or _norm_req(req_s) in covered:
                continue
            table.append(
                {
                    "requirement": req_s,
                    "source": "core",
                    "evidence": evidence0 if evidence0 != "简历未体现" else "待补充证据",
                    "strength": "中",
                    "gap_note": "自动补齐行，建议人工核验证据强度",
                }
            )
            covered.add(_norm_req(req_s))
            if len(table) >= 6:
                break
    report["match_table"] = table
    return report


ProgressCb = Callable[[dict[str, str], dict[str, Any] | None], None]


def _compact_for_action(resume_profile: dict, jd_profile: dict) -> tuple[dict, dict]:
    resume = {
        "summary": (resume_profile.get("summary") or "")[:360],
        "strengths": (resume_profile.get("strengths") or [])[:5],
        "weak": (resume_profile.get("weak") or [])[:4],
        "evidence": [str(x)[:140] for x in (resume_profile.get("evidence") or [])[:6]],
        "skills": (resume_profile.get("skills") or [])[:10],
        "years": resume_profile.get("years"),
    }
    jd = {
        "title": jd_profile.get("title"),
        "level": jd_profile.get("level"),
        "must_haves": (jd_profile.get("must_haves") or [])[:8],
        "core_requirements": (jd_profile.get("core_requirements") or [])[:8],
        "nice_to_haves": (jd_profile.get("nice_to_haves") or [])[:4],
        "risks": (jd_profile.get("risks") or [])[:3],
        "summary": (jd_profile.get("summary") or "")[:220],
    }
    return resume, jd


def _format_evidence_pool(evidence_pool: list[dict] | None) -> str:
    if not evidence_pool:
        return ""
    lines: list[str] = ["可用跨简历证据池（标注来源，禁止编造）："]
    for item in evidence_pool[:6]:
        name = item.get("resume_name") or item.get("resume_id") or "其他简历"
        ev = [str(x) for x in (item.get("evidence") or [])[:4]]
        st = [str(x) for x in (item.get("strengths") or [])[:3]]
        sk = [str(x) for x in (item.get("skills") or [])[:6]]
        chunk = f"来源《{name}》"
        if ev:
            chunk += "；证据：" + " / ".join(ev)
        if st:
            chunk += "；优势：" + " / ".join(st)
        if sk:
            chunk += "；技能：" + "、".join(sk)
        lines.append("- " + chunk)
    return "\n".join(lines)


def build_action_report(
    judge: dict,
    resume_profile: dict,
    jd_profile: dict,
    on_progress: ProgressCb | None = None,
    evidence_pool: list[dict] | None = None,
    allow_cross_resume: bool = True,
) -> tuple[dict[str, Any], dict]:
    """
    四模块一轮并行（M1∥M2∥M3∥M4），墙钟 ≈ 最慢单模块，目标 ≤60s。
    M3/M4 直接消费 judge.gaps，不串行等待 M2。
    可选 evidence_pool：跨简历真实证据（需 allow_cross_resume）。
    """
    fallback = mock_report(judge, resume_profile, jd_profile)
    resume_c, jd_c = _compact_for_action(resume_profile, jd_profile)
    base_user = {
        "judge": _judge_bundle(judge),
        "resume_profile": resume_c,
        "jd_profile": jd_c,
        "gaps_hint": judge.get("gaps") or [],
    }
    pool_note = ""
    use_pool = bool(allow_cross_resume and evidence_pool)
    if use_pool:
        pool_note = _format_evidence_pool(evidence_pool)
        base_user["evidence_pool"] = evidence_pool[:6]
    modules = {"m1": "pending", "m2": "pending", "m3": "pending", "m4": "pending"}
    partial: dict[str, Any] = {}
    metas: dict[str, Any] = {
        "modular": True,
        "parallel": "m1-m4",
        "modules": {},
        "cross_resume": use_pool,
    }

    def emit() -> None:
        if on_progress:
            on_progress(dict(modules), dict(partial) if partial else None)

    for k in modules:
        modules[k] = "running"
    emit()

    m3_payload = {
        **base_user,
        "reminders": ["resume_rewrite 3-4条", "禁止伪造精确指标"],
    }
    m4_payload = {
        **base_user,
        "reminders": ["interview 5-8题", "sample_outline 绑定简历证据"],
    }
    if pool_note:
        m3_payload["cross_resume_note"] = pool_note
        m4_payload["cross_resume_note"] = pool_note
        m3_payload["reminders"] = list(m3_payload["reminders"]) + [
            "可引用证据池并填写 source_resume，禁止编造"
        ]
        m4_payload["reminders"] = list(m4_payload["reminders"]) + [
            "可引用证据池并填写 source_resume，禁止编造"
        ]

    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_m1 = pool.submit(
            _run_module,
            SYSTEM_M1,
            {
                **base_user,
                "reminders": ["conclusion 120-240字", "verdict 与 judge.level 一致"],
            },
            _slice_fallback(fallback, ("conclusion", "conclusion_structured", "score_narrative")),
            max_tokens=1100,
        )
        fut_m2 = pool.submit(
            _run_module,
            SYSTEM_M2,
            {
                **base_user,
                "reminders": ["match_table 覆盖 must_haves", "gaps 含 fix_plan"],
            },
            _slice_fallback(fallback, ("match_table", "strengths_detail", "gaps_detail")),
            max_tokens=1400,
        )
        fut_m3 = pool.submit(
            _run_module,
            SYSTEM_M3,
            m3_payload,
            _slice_fallback(fallback, ("resume_rewrite",)),
            max_tokens=1100,
        )
        fut_m4 = pool.submit(
            _run_module,
            SYSTEM_M4,
            m4_payload,
            _slice_fallback(fallback, ("interview", "interview_knowledge")),
            max_tokens=1600,
        )

        results = {
            "m1": fut_m1.result(),
            "m2": fut_m2.result(),
            "m3": fut_m3.result(),
            "m4": fut_m4.result(),
        }

    for key, (chunk, meta) in results.items():
        partial.update(chunk)
        modules[key] = "done"
        metas["modules"][key] = meta
    partial = ensure_must_have_coverage(partial, jd_profile, resume_profile)
    emit()

    report = _normalize_report(partial, fallback, judge)
    report = ensure_must_have_coverage(report, jd_profile, resume_profile)

    metas["used"] = any(
        bool((metas["modules"].get(k) or {}).get("used")) for k in ("m1", "m2", "m3", "m4")
    )
    metas["model"] = next(
        (
            (metas["modules"].get(k) or {}).get("model")
            for k in ("m1", "m2", "m3", "m4")
            if (metas["modules"].get(k) or {}).get("model")
        ),
        None,
    )
    return report, metas
