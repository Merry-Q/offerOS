"""Public demo account, curated sample data, and session helper."""
from __future__ import annotations

from typing import Any

from server.auth import create_session, hash_password
from server.cache_store import text_hash
from server.db import dumps, get_db, init_db, utc_now

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "Demo@OfferOS2026"
DEMO_USER_ID = "user_demo"
DEMO_RESUME_ID = "cv_demo_linzhixia"

from server.demo_resume import DEMO_RESUME_TEXT as RAW_RESUME, DEMO_RESUME_PROFILE as PROFILE


SAMPLE_ANSWER = (
    "情境：客户门户 2.0 上线前，人工工单持续上涨，销售和研发对优先级争执很大。"
    "任务：我需要在两周内给出可排期的机会排序。"
    "行动：先完成 32 场访谈，把诉求分成自助服务和人工工单两类，再用激活率和工单量交叉验证；"
    "然后组织双周共识会，让销售、研发、客户成功一起认同一版分阶段上线。"
    "结果：灰度后激活率提升 16%，人工工单下降 19%，交付周期从 7 周收到 5 周。"
    "复盘：如果再做一次，会更早把英语协作边界写清楚，避免面试时被当成已具备的硬能力。"
)


def _pack_report(
    *,
    conclusion: str,
    verdict: str,
    one_liner: str,
    why_fit: list[str],
    why_risk: list[str],
    rewrites: list[dict[str, str]],
    interview: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "conclusion": conclusion,
        "conclusion_structured": {
            "verdict": verdict,
            "one_liner": one_liner,
            "why_fit": why_fit,
            "why_risk": why_risk,
            "decision_advice": "查看报告后决定是否投递",
            "next_7_days": ["完成岗位版简历", "准备一个 STAR 案例", "列出要问面试官的 3 个问题"],
        },
        "score_narrative": {
            "knowledge_skills": "对照岗位核心技能看覆盖度。",
            "work_experience": "对照场景相关度看经历。",
            "core_abilities": "对照交付闭环看能力证据。",
            "personality_traits": "对照协作与结构化行为证据。",
            "hard_gates": "硬门槛只作提醒，不改分数。",
        },
        "match_table": [
            {
                "requirement": why_fit[0] if why_fit else "核心要求",
                "source": "must_have",
                "evidence": why_fit[-1] if why_fit else "",
                "strength": "强" if verdict in {"保", "稳"} else "中",
                "gap_note": why_risk[0] if why_risk else "",
            }
        ],
        "strengths_detail": [{"text": x, "evidence": x, "how_to_amplify": "把指标放在项目首句"} for x in why_fit[:2]],
        "gaps_detail": [
            {
                "severity": "fixable",
                "text": x,
                "impact": "影响加分项或跨岗位说服力",
                "fix_plan": "用真实边界补一句，不要夸大",
                "interview_cover": "面试时主动说明能力边界",
            }
            for x in why_risk[:2]
        ],
        "resume_rewrite": rewrites,
        "interview": interview,
        "interview_knowledge": {
            "must_know": ["客户服务指标", "工单分流", "激活与留存"],
            "talking_points": why_fit,
            "questions_to_ask": ["团队当前最重要的客户服务指标是什么？", "岗位前三个月的成功标准是什么？"],
        },
    }


DEMO_JOBS: list[dict[str, Any]] = [
    {
        "job_id": "job_demo_enterprise",
        "match_id": "m_demo_enterprise",
        "title": "高级产品经理（企业服务）",
        "company": "星河云软件（虚构）",
        "location": "上海",
        "employment_type": "全职",
        "apply_status": "待决策",
        "starred": 1,
        "score": 86,
        "level": "保",
        "one_liner": "核心场景与证据高度重合，建议优化后投递。",
        "dims": [
            {"name": "知识技能", "key": "knowledge_skills", "v": 86, "w": 0.35},
            {"name": "工作经验", "key": "work_experience", "v": 90, "w": 0.25},
            {"name": "核心能力", "key": "core_abilities", "v": 88, "w": 0.25},
            {"name": "个性特质", "key": "personality_traits", "v": 78, "w": 0.15},
        ],
        "strengths": ["客户门户与工单经验高度匹配", "用户研究和数据闭环完整"],
        "gaps": [{"severity": "fixable", "text": "英语工作证据较少"}],
        "jd_text": """岗位名称：高级产品经理（企业服务）
公司名称：星河云软件（虚构）
地点：上海
招聘类型：全职

岗位职责：
1. 负责企业客户服务产品规划，从用户洞察到上线迭代全流程推进；
2. 通过客户访谈、数据分析识别机会并制定路线图；
3. 协同设计、研发、客户成功和销售完成产品交付；
4. 建立激活、留存和工单效率指标，持续优化。

任职要求：
1. 本科及以上学历，3 年以上 ToB SaaS 产品经验；
2. 具备用户研究、数据分析与跨团队推动能力；
3. 有客户门户或工单产品经验优先；
4. 英语可作为工作语言者加分。
""",
        "jd_profile": {
            "title": "高级产品经理（企业服务）",
            "company": "星河云软件（虚构）",
            "location": "上海",
            "employment_type": "全职",
            "level": "高级",
            "hard_gates": {
                "major": {"requirement": "相关专业优先", "strictness": "相关即可"},
                "education": {"requirement": "本科及以上", "strictness": "硬性"},
                "experience": {"requirement": "3 年以上 ToB SaaS 产品经验", "strictness": "硬性"},
                "language": {"requirement": "英语可作为工作语言者加分", "strictness": "偏好"},
            },
            "must_haves": ["本科及以上学历", "3 年以上 ToB SaaS 产品经验"],
            "core_requirements": ["用户研究", "数据分析", "跨团队推动", "客户服务产品规划"],
            "nice_to_haves": ["客户门户或工单经验", "工作英语"],
            "risks": ["英语工作能力需要面试补证"],
            "summary": "面向企业客户服务场景，强调洞察、交付与指标闭环的高级产品岗位。",
        },
        "research": {
            "industry_status": [
                {
                    "conclusion": "企业服务 SaaS 仍以客户成功、激活和工单效率作为常见考核，和林知夏的门户/工单证据同一赛道。",
                    "source_ids": ["s1"],
                }
            ],
            "company_moves": [
                {
                    "conclusion": "星河云软件为 Demo 虚构公司，未检索到真实工商或新闻；展示时按「客户服务产品」岗位逻辑理解即可。",
                    "source_ids": ["s1"],
                }
            ],
            "financing_valuation": [
                {"conclusion": "虚构主体，没有可核验的融资或估值信息。", "source_ids": ["s1"]}
            ],
            "sources": [
                {
                    "id": "s1",
                    "title": "Demo 说明：虚构公司，不对应真实主体",
                    "url": "https://example.com/offeros-demo",
                }
            ],
            "research_note": "演示数据。公司为虚构，结论只用于展示背调卡片怎么读，不作为真实投递依据。",
        },
        "report": _pack_report(
            conclusion="岗位与林知夏的 ToB SaaS、客户门户和工单产品经历高度一致，建议按「保」档投递。投前应补充英文协作的真实边界。",
            verdict="保",
            one_liner="核心场景与证据高度重合。",
            why_fit=["同类产品经验", "指标证据完整"],
            why_risk=["英语工作证据不足"],
            rewrites=[
                {
                    "section": "客户门户 2.0",
                    "original": "负责客户门户改版",
                    "problem": "角色与结果不清晰",
                    "rewrite": "主导客户门户 2.0 从 32 场访谈、机会排序到灰度上线，协调四个职能团队交付，使激活率提升 16%、人工工单量下降 19%。",
                    "why_better": "对齐用户洞察、跨团队交付和指标闭环",
                    "rewrite_scope": "句子润色",
                },
                {
                    "section": "项目经历",
                    "original": "多项企业产品项目",
                    "problem": "项目结构分散",
                    "rewrite": "按客户问题—产品策略—关键决策—协作交付—业务结果重组完整项目，突出客户服务产品方法论。",
                    "why_better": "适合展示可迁移的完整能力",
                    "rewrite_scope": "项目改写",
                },
            ],
            interview=[
                {
                    "category": "项目深挖",
                    "question": "你如何从 32 场访谈中确定客户门户的优先级？",
                    "framework": "问题分层→证据交叉验证→机会排序→决策",
                    "sample_outline": "结合客户门户 2.0 的真实过程回答",
                },
                {
                    "category": "行为",
                    "question": "销售和研发目标冲突时你如何推动共识？",
                    "framework": "冲突背景→共同目标→方案选择→结果复盘",
                    "sample_outline": "使用双周共识会案例",
                },
            ],
        ),
    },
    {
        "job_id": "job_demo_growth",
        "match_id": "m_demo_growth",
        "title": "增长产品经理",
        "company": "北屿数据（虚构）",
        "location": "北京",
        "employment_type": "全职",
        "apply_status": "待改简历",
        "starred": 0,
        "score": 61,
        "level": "冲",
        "one_liner": "能力可迁移，但增长实验证据不足，需要改写成增长语言再投。",
        "dims": [
            {"name": "知识技能", "key": "knowledge_skills", "v": 64, "w": 0.35},
            {"name": "工作经验", "key": "work_experience", "v": 58, "w": 0.25},
            {"name": "核心能力", "key": "core_abilities", "v": 66, "w": 0.25},
            {"name": "个性特质", "key": "personality_traits", "v": 55, "w": 0.15},
        ],
        "strengths": ["有指标意识和实验习惯的雏形", "能跨团队推动上线"],
        "gaps": [{"severity": "important", "text": "缺少获客/转化实验和增长模型证据"}],
        "jd_text": """岗位名称：增长产品经理
公司名称：北屿数据（虚构）
地点：北京
招聘类型：全职

岗位职责：
1. 负责获客到激活的增长实验，设计漏斗并周更结论；
2. 与市场、销售和数据团队合作投放与转化策略；
3. 搭建 A/B 测试机制，沉淀可复用的增长玩法。

任职要求：
1. 3 年以上消费互联网或增长产品经验；
2. 熟悉获客、转化、留存指标和实验设计；
3. 有投放或裂变项目经验优先。
""",
        "jd_profile": {
            "title": "增长产品经理",
            "company": "北屿数据（虚构）",
            "location": "北京",
            "employment_type": "全职",
            "level": "中级",
            "hard_gates": {
                "major": {"requirement": "不限", "strictness": "未要求"},
                "education": {"requirement": "本科及以上", "strictness": "硬性"},
                "experience": {"requirement": "3 年以上增长/消费互联网产品经验", "strictness": "硬性"},
                "language": {"requirement": "未要求", "strictness": "未要求"},
            },
            "must_haves": ["增长或消费互联网经验", "实验设计"],
            "core_requirements": ["获客转化", "A/B 测试", "漏斗指标"],
            "nice_to_haves": ["投放经验", "裂变项目"],
            "risks": ["ToB 服务产品经验不能直接等同增长经验"],
            "summary": "偏消费增长与实验，和林知夏的企业服务主线有场景差。",
        },
        "research": {
            "industry_status": [
                {
                    "conclusion": "增长岗通常考核获客成本、激活和实验节奏，与客户服务产品经理的考核不同。",
                    "source_ids": ["s1"],
                }
            ],
            "company_moves": [
                {"conclusion": "北屿数据为 Demo 虚构公司，没有可核验的近半年业务动作。", "source_ids": ["s1"]}
            ],
            "financing_valuation": [{"conclusion": "无公开融资信息（虚构主体）。", "source_ids": ["s1"]}],
            "sources": [
                {"id": "s1", "title": "Demo 说明：虚构公司", "url": "https://example.com/offeros-demo"}
            ],
            "research_note": "演示用跨岗位案例。重点看「冲」档如何给改写建议，而不是公司真实性。",
        },
        "report": _pack_report(
            conclusion="这是跨岗位案例：林知夏有指标和实验意识，但缺少获客/转化项目。建议改写成增长语言后再投，或先用企业服务岗练手。",
            verdict="冲",
            one_liner="能力可迁移，增长证据不足。",
            why_fit=["有激活/工单等指标意识", "能推动跨团队上线"],
            why_risk=["没有获客与投放项目", "A/B 测试证据偏产品验证而非增长实验"],
            rewrites=[
                {
                    "section": "客户门户激活",
                    "original": "上线后激活率提升 16%",
                    "problem": "没有写成增长实验",
                    "rewrite": "把客户门户激活当作增长实验：定义激活事件、对照灰度组和全量组，两周内将激活率从基线提升 16%，并沉淀为可复用的激活清单。",
                    "why_better": "用增长岗听得懂的实验语言改写已有结果",
                    "rewrite_scope": "句子润色",
                }
            ],
            interview=[
                {
                    "category": "迁移",
                    "question": "如果让你做获客到激活的增长实验，你准备先验证什么？",
                    "framework": "假设→指标→最小实验→决策",
                    "sample_outline": "承认缺少投放经验，用门户激活实验说明你懂闭环",
                }
            ],
        ),
    },
    {
        "job_id": "job_demo_cs",
        "match_id": "m_demo_cs",
        "title": "客户成功产品经理",
        "company": "青禾云服（虚构）",
        "location": "杭州",
        "employment_type": "全职",
        "apply_status": "待投",
        "starred": 1,
        "score": 78,
        "level": "稳",
        "one_liner": "服务流程经验匹配，补上客户成功指标表述后可以稳投。",
        "dims": [
            {"name": "知识技能", "key": "knowledge_skills", "v": 80, "w": 0.35},
            {"name": "工作经验", "key": "work_experience", "v": 76, "w": 0.25},
            {"name": "核心能力", "key": "core_abilities", "v": 82, "w": 0.25},
            {"name": "个性特质", "key": "personality_traits", "v": 70, "w": 0.15},
        ],
        "strengths": ["工单与门户经验可直接映射客户成功产品", "有跨职能推动证据"],
        "gaps": [{"severity": "fixable", "text": "续费/健康度指标未直接写在简历里"}],
        "jd_text": """岗位名称：客户成功产品经理
公司名称：青禾云服（虚构）
地点：杭州
招聘类型：全职

岗位职责：
1. 负责客户成功工作台、健康度和续费相关产品；
2. 降低流失，提高自助解决率和续约率；
3. 与客户成功、销售运营一起定义成功指标。

任职要求：
1. 3 年以上 ToB 产品经验，了解客户成功流程优先；
2. 能用数据解释流失和工单结构；
3. 有工作台或门户产品经验加分。
""",
        "jd_profile": {
            "title": "客户成功产品经理",
            "company": "青禾云服（虚构）",
            "location": "杭州",
            "employment_type": "全职",
            "level": "中高级",
            "hard_gates": {
                "major": {"requirement": "不限", "strictness": "未要求"},
                "education": {"requirement": "本科及以上", "strictness": "硬性"},
                "experience": {"requirement": "3 年以上 ToB 产品经验", "strictness": "硬性"},
                "language": {"requirement": "未要求", "strictness": "未要求"},
            },
            "must_haves": ["ToB 产品经验", "数据解释流失/工单"],
            "core_requirements": ["客户成功流程", "健康度", "自助解决率"],
            "nice_to_haves": ["工作台或门户经验"],
            "risks": ["简历未直接写续费指标"],
            "summary": "客户成功产品与林知夏的门户/工单主线相邻，属于稳档。",
        },
        "research": {
            "industry_status": [
                {
                    "conclusion": "客户成功产品常围绕健康度、续费和自助率，和工单门户是同一服务闭环的不同切片。",
                    "source_ids": ["s1"],
                }
            ],
            "company_moves": [
                {"conclusion": "青禾云服为 Demo 虚构公司，用于展示「稳」档相邻岗位。", "source_ids": ["s1"]}
            ],
            "financing_valuation": [{"conclusion": "无公开融资信息（虚构主体）。", "source_ids": ["s1"]}],
            "sources": [
                {"id": "s1", "title": "Demo 说明：虚构公司", "url": "https://example.com/offeros-demo"}
            ],
            "research_note": "演示用相邻岗位。重点看如何把工单指标改写成客户成功语言。",
        },
        "report": _pack_report(
            conclusion="门户和工单经验可以映射到客户成功工作台。把「人工工单下降」改写成「自助解决率/健康度」后，适合按「稳」档投递。",
            verdict="稳",
            one_liner="服务流程经验匹配，补指标表述即可。",
            why_fit=["ToB 服务流程经验", "工单自助与激活指标"],
            why_risk=["未直接写续费或客户健康度"],
            rewrites=[
                {
                    "section": "工单自助",
                    "original": "人工工单量下降 19%",
                    "problem": "没有映射客户成功指标",
                    "rewrite": "通过门户解决方案提升自助解决率，使人工工单下降 19%，相当于减少客户成功团队重复劳动并改善账户健康度。",
                    "why_better": "让客户成功面试官立刻听懂你的结果",
                    "rewrite_scope": "句子润色",
                }
            ],
            interview=[
                {
                    "category": "指标",
                    "question": "你如何定义一个客户是否健康？",
                    "framework": "使用行为→结果指标→干预动作",
                    "sample_outline": "用激活、工单、自助率三件事说明，并承认续费数据不在你的原职责里",
                }
            ],
        ),
    },
    {
        "job_id": "job_demo_intern",
        "match_id": "m_demo_intern",
        "title": "产品实习生（校园招聘）",
        "company": "启明学院项目（虚构）",
        "location": "远程",
        "employment_type": "实习",
        "apply_status": "不建议",
        "starred": 0,
        "score": 44,
        "level": "不建议投",
        "one_liner": "年限和职责都高于实习定义，投递会显得方向混乱。",
        "dims": [
            {"name": "知识技能", "key": "knowledge_skills", "v": 52, "w": 0.35},
            {"name": "工作经验", "key": "work_experience", "v": 38, "w": 0.25},
            {"name": "核心能力", "key": "core_abilities", "v": 48, "w": 0.25},
            {"name": "个性特质", "key": "personality_traits", "v": 40, "w": 0.15},
        ],
        "strengths": ["基本产品方法仍适用"],
        "gaps": [{"severity": "fatal", "text": "4 年全职经验投实习岗，匹配目标不一致", "hard_gate": True}],
        "jd_text": """岗位名称：产品实习生（校园招聘）
公司名称：启明学院项目（虚构）
地点：远程
招聘类型：实习

岗位职责：
1. 协助整理用户访谈纪要和竞品表格；
2. 协助撰写需求文档初稿；
3. 每周参与产品例会并做会议记录。

任职要求：
1. 在校本科或硕士，每周可实习 4 天；
2. 有课程项目或社团产品经历即可；
3. 不要求全职工作经验。
""",
        "jd_profile": {
            "title": "产品实习生（校园招聘）",
            "company": "启明学院项目（虚构）",
            "location": "远程",
            "employment_type": "实习",
            "level": "实习",
            "hard_gates": {
                "major": {"requirement": "不限", "strictness": "未要求"},
                "education": {"requirement": "在校学生", "strictness": "硬性"},
                "experience": {"requirement": "不要求全职经验", "strictness": "硬性"},
                "language": {"requirement": "未要求", "strictness": "未要求"},
            },
            "must_haves": ["在校学生", "可实习 4 天"],
            "core_requirements": ["访谈纪要", "文档协助"],
            "nice_to_haves": ["课程项目"],
            "risks": ["全职候选人投实习显得目标混乱"],
            "summary": "校园实习岗，和林知夏 4 年全职画像错位。",
        },
        "research": {
            "industry_status": [
                {"conclusion": "校园实习岗服务在校学生，不评估全职交付闭环。", "source_ids": ["s1"]}
            ],
            "company_moves": [
                {"conclusion": "启明学院项目为 Demo 虚构主体，用于展示「不建议投」的硬门槛提醒。", "source_ids": ["s1"]}
            ],
            "financing_valuation": [{"conclusion": "不适用。", "source_ids": ["s1"]}],
            "sources": [
                {"id": "s1", "title": "Demo 说明：虚构实习项目", "url": "https://example.com/offeros-demo"}
            ],
            "research_note": "演示用反例。硬门槛只警示，不改分数；这里分数低是因为目标岗位本身不匹配。",
        },
        "report": _pack_report(
            conclusion="不建议投。这是校园实习，林知夏已是 4 年全职产品经理，投递会让双方都觉得方向混乱。应把精力放在企业服务或客户成功产品岗。",
            verdict="不建议投",
            one_liner="岗位目标和候选人阶段错位。",
            why_fit=["产品方法本身仍通用"],
            why_risk=["不是在校学生", "全职年限远高于实习定义"],
            rewrites=[
                {
                    "section": "投递策略",
                    "original": "海投实习",
                    "problem": "目标和证据不匹配",
                    "rewrite": "停止投递实习岗，把同一份客户门户证据投向企业服务 / 客户成功产品经理。",
                    "why_better": "把有限时间用在匹配的岗位上",
                    "rewrite_scope": "项目改写",
                }
            ],
            interview=[
                {
                    "category": "决策",
                    "question": "如果面试官问你为什么投实习，你怎么回答？",
                    "framework": "承认错配→说明真正目标岗位→结束这条投递",
                    "sample_outline": "Demo 里这题用来练习「会拒绝不匹配机会」",
                }
            ],
        ),
    },
]


def demo_presets() -> list[dict[str, str]]:
    return [
        {
            "id": job["job_id"],
            "label": f"{job['level']} · {job['title']}",
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "employment_type": job["employment_type"],
            "jd_text": job["jd_text"],
        }
        for job in DEMO_JOBS
    ]


def _public_user(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def ensure_demo_user() -> dict[str, Any]:
    init_db()
    now = utc_now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE username = ?",
            (DEMO_USERNAME,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = 'user' WHERE id = ?",
                (hash_password(DEMO_PASSWORD), row["id"]),
            )
            return dict(row)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, 'user', ?)",
            (DEMO_USER_ID, DEMO_USERNAME, hash_password(DEMO_PASSWORD), now),
        )
        row = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE id = ?",
            (DEMO_USER_ID,),
        ).fetchone()
        return dict(row)


def seed_demo_library(*, reset: bool = True) -> dict[str, Any]:
    """Create/reset curated demo resume + job analyses. Does not touch other users."""
    init_db()
    user = ensure_demo_user()
    user_id = user["id"]
    now = utc_now()
    seed_ids = [DEMO_RESUME_ID] + [j["job_id"] for j in DEMO_JOBS] + [j["match_id"] for j in DEMO_JOBS]
    with get_db() as conn:
        if reset:
            placeholders = ",".join("?" * len(DEMO_JOBS))
            conn.execute(
                f"DELETE FROM match_runs WHERE id IN ({','.join('?' * len(DEMO_JOBS))})",
                [j["match_id"] for j in DEMO_JOBS],
            )
            conn.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders})",
                [j["job_id"] for j in DEMO_JOBS],
            )
            conn.execute("DELETE FROM resumes WHERE id = ?", (DEMO_RESUME_ID,))
        conn.execute(
            """INSERT INTO resumes (id,user_id,name,file_name,file_type,file_path,status,raw_text,profile_json,direction_tag,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                DEMO_RESUME_ID,
                user_id,
                "林知夏 · ToB 产品经理（虚构）",
                "demo-lin-zhixia.docx",
                "docx",
                "",
                "parsed",
                RAW_RESUME,
                dumps(PROFILE),
                "产品",
                now,
                now,
            ),
        )
        # Upgrade only system-created fictional copies, never uploaded resumes.
        conn.execute(
            "UPDATE resumes SET raw_text=?,profile_json=?,updated_at=? WHERE id LIKE 'cv_demo_%' "
            "AND id!=? AND file_name='demo-lin-zhixia.docx' AND raw_text LIKE '林知夏（虚构人物） | ToB SaaS 产品经理%'",
            (RAW_RESUME, dumps(PROFILE), now, DEMO_RESUME_ID),
        )
        for job in DEMO_JOBS:
            conn.execute(
                """INSERT INTO jobs (id,user_id,title,jd_text,jd_profile_json,company,location,source_url,employment_type,apply_status,starred,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job["job_id"],
                    user_id,
                    job["title"],
                    job["jd_text"],
                    dumps(job["jd_profile"]),
                    job["company"],
                    job["location"],
                    "",
                    job["employment_type"],
                    job["apply_status"],
                    job["starred"],
                    now,
                    now,
                ),
            )
            conn.execute(
                """INSERT INTO match_runs (id,job_id,version,resume_id,resume_name,pref_id,pref_name,score,level,one_liner,dims_json,threshold,raw_score,strengths_json,gaps_json,jd_profile_json,report_json,llm_meta_json,judge_status,report_status,report_updated_at,judge_duration_ms,report_duration_ms,report_modules_json,jd_text_hash,starred,auto_report,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job["match_id"],
                    job["job_id"],
                    1,
                    DEMO_RESUME_ID,
                    "林知夏 · ToB 产品经理（虚构）",
                    "",
                    "",
                    job["score"],
                    job["level"],
                    job["one_liner"],
                    dumps(job["dims"]),
                    92,
                    job["score"],
                    dumps(job["strengths"]),
                    dumps(job["gaps"]),
                    dumps(job["jd_profile"]),
                    dumps(job["report"]),
                    dumps({"demo": True, "research": job["research"]}),
                    "done",
                    "done",
                    now,
                    900,
                    2400,
                    dumps({"m1": "done", "m2": "done", "m3": "done", "m4": "done"}),
                    text_hash(job["jd_text"]),
                    job["starred"],
                    1,
                    now,
                ),
            )
    return {"user": _public_user(user), "seed_ids": seed_ids, "jobs": len(DEMO_JOBS)}


def issue_demo_session() -> dict[str, Any]:
    user = ensure_demo_user()
    with get_db() as conn:
        has_resume = conn.execute(
            "SELECT id FROM resumes WHERE id = ?", (DEMO_RESUME_ID,)
        ).fetchone()
        has_jobs = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
    if not has_resume or has_jobs < 4:
        seed_demo_library(reset=True)
        user = ensure_demo_user()
    token = create_session(user["id"])
    return {
        "token": token,
        "user": _public_user(user),
        "demo": True,
        "must_change_password": False,
        "presets": demo_presets(),
        "sample_answer": SAMPLE_ANSWER,
    }
