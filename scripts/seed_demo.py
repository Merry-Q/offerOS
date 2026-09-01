"""Create/reset the isolated fictional OfferOS demo account."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.auth import hash_password
from server.db import dumps, get_db, init_db, utc_now


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "Demo@OfferOS2026"

PROFILE = {
    "summary": "虚构人物林知夏：4 年 ToB SaaS 产品经验，擅长用户研究、流程产品设计与跨团队交付。",
    "knowledge_skills": [
        {"name": "用户研究", "evidence": "独立完成 32 场客户访谈并形成机会地图", "source": "简历"},
        {"name": "产品分析与设计", "evidence": "使用漏斗分析、流程建模和原型验证推进方案", "source": "简历"},
        {"name": "数据分析", "evidence": "围绕激活率、工单自助解决率建立指标看板", "source": "简历"},
    ],
    "work_experience": [
        {"name": "云帆协作科技（虚构）· 产品经理", "evidence": "2022.07—2026.06，负责企业客户门户与工单产品", "source": "简历"},
        {"name": "客户门户 2.0", "evidence": "主导从调研、方案评审到灰度上线的完整闭环", "source": "简历"},
    ],
    "core_abilities": [
        {"name": "需求洞察", "evidence": "从访谈与行为数据识别高频自助服务机会", "source": "简历"},
        {"name": "跨团队推动", "evidence": "协调研发、设计、客户成功和销售完成分阶段交付", "source": "简历"},
        {"name": "结果导向", "evidence": "上线后客户门户激活率提升 16%，人工工单量下降 19%", "source": "简历"},
    ],
    "personality_traits": [
        {"name": "结构化", "evidence": "将分散需求整理为机会树与优先级规则", "source": "AI推断"},
        {"name": "协作耐心", "evidence": "通过双周共识会处理销售与研发目标冲突", "source": "AI推断"},
    ],
    "suitable_roles": [
        {"role": "ToB SaaS 产品经理", "industries": ["企业服务", "协同办公"], "reason": "已有完整的客户门户和工单产品证据链"},
        {"role": "客户体验产品经理", "industries": ["云服务", "软件服务"], "reason": "用户研究和服务流程优化能力较强"},
    ],
    "strengths": ["用户洞察与数据验证结合", "能独立推进复杂协作项目", "结果表达可量化"],
    "weak": ["没有消费互联网增长经验", "英文跨国协作证据较少"],
    "evidence": [
        "客户门户激活率提升 16%，人工工单量下降 19%",
        "32 场客户访谈形成机会地图",
        "交付周期由平均 7 周缩短至 5 周",
    ],
    "skills": ["用户研究", "PRD", "数据分析", "流程设计", "原型设计"],
    "years": "4 年",
}

RAW_RESUME = """林知夏（虚构人物） | ToB SaaS 产品经理
所有公司、项目与数字均为 OfferOS Demo 构造内容，不对应任何真实个人。

工作经历
云帆协作科技（虚构），产品经理，2022.07—2026.06
- 负责企业客户门户与工单产品，完成 32 场客户访谈并建立机会地图。
- 主导客户门户 2.0，协调研发、设计、客户成功与销售分阶段上线。
- 上线后激活率提升 16%，人工工单量下降 19%，交付周期由 7 周缩短到 5 周。

教育经历
南川大学（虚构），信息管理与信息系统，本科，2018—2022
"""

JD_TEXT = """岗位名称：高级产品经理（企业服务）
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
"""

JD_PROFILE = {
    "title": "高级产品经理（企业服务）", "company": "星河云软件（虚构）", "location": "上海",
    "employment_type": "全职", "level": "高级",
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
}

DIMS = [
    {"name": "知识技能", "key": "knowledge_skills", "v": 86, "w": 0.35},
    {"name": "工作经验", "key": "work_experience", "v": 90, "w": 0.25},
    {"name": "核心能力", "key": "core_abilities", "v": 88, "w": 0.25},
    {"name": "个性特质", "key": "personality_traits", "v": 78, "w": 0.15},
]

REPORT = {
    "conclusion": "岗位与林知夏的 ToB SaaS、客户门户和工单产品经历高度一致，建议按“保”档投递。投前应补充英文协作的真实边界，避免把加分项写成已具备的硬能力。",
    "conclusion_structured": {"verdict": "保", "one_liner": "核心场景与证据高度重合。", "why_fit": ["同类产品经验", "指标证据完整"], "why_risk": ["英语工作证据不足"], "decision_advice": "优化简历后投递", "next_7_days": ["完成岗位版简历", "准备客户门户 STAR", "练习英文自我介绍"]},
    "score_narrative": {"knowledge_skills": "技能覆盖较完整。", "work_experience": "经验场景高度相关。", "core_abilities": "有完整交付闭环。", "personality_traits": "行为证据支持结构化与协作。", "hard_gates": "学历与年限通过；英语为加分项。"},
    "match_table": [{"requirement": "3 年以上 ToB SaaS 经验", "source": "must_have", "evidence": "4 年企业服务产品经验", "strength": "强", "gap_note": ""}],
    "strengths_detail": [{"text": "客户服务产品经验", "evidence": "客户门户和工单产品", "how_to_amplify": "把指标放在项目首句"}],
    "gaps_detail": [{"severity": "fixable", "text": "工作英语证据较少", "impact": "影响加分项", "fix_plan": "如实补充真实英文场景", "interview_cover": "说明实际使用边界"}],
    "resume_rewrite": [
        {"section": "客户门户 2.0", "original": "负责客户门户改版", "problem": "角色与结果不清晰", "rewrite": "主导客户门户 2.0 从 32 场访谈、机会排序到灰度上线，协调四个职能团队交付，使激活率提升 16%、人工工单量下降 19%。", "why_better": "对齐用户洞察、跨团队交付和指标闭环", "rewrite_scope": "句子润色"},
        {"section": "项目经历", "original": "多项企业产品项目", "problem": "项目结构分散", "rewrite": "按客户问题—产品策略—关键决策—协作交付—业务结果重组完整项目，突出客户服务产品方法论。", "why_better": "适合跨岗位时展示可迁移的完整能力", "rewrite_scope": "项目改写"},
    ],
    "interview": [
        {"category": "项目深挖", "question": "你如何从 32 场访谈中确定客户门户的优先级？", "why_asked": "验证洞察方法", "framework": "问题分层→证据交叉验证→机会排序→决策", "sample_outline": "结合客户门户 2.0 的真实过程回答", "followups": ["反对意见如何处理？"], "pitfalls": ["只讲流程不讲取舍"]},
        {"category": "行为", "question": "销售和研发目标冲突时你如何推动共识？", "why_asked": "验证协作能力", "framework": "冲突背景→共同目标→方案选择→结果复盘", "sample_outline": "使用双周共识会案例", "followups": ["如果仍无法达成一致呢？"], "pitfalls": ["把功劳全部归于个人"]},
    ],
    "interview_knowledge": {"must_know": ["企业客户服务指标", "工单分流", "客户门户激活"], "talking_points": ["用户洞察", "交付闭环", "量化结果"], "questions_to_ask": ["团队当前最重要的客户服务指标是什么？", "岗位前三个月的成功标准是什么？", "产品与客户成功如何协作？"]},
}


def seed() -> None:
    init_db()
    now = utc_now()
    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", (DEMO_USERNAME,)).fetchone()
        user_id = user["id"] if user else "user_demo"
        if user:
            conn.execute("UPDATE users SET password_hash = ?, role = 'user' WHERE id = ?", (hash_password(DEMO_PASSWORD), user_id))
        else:
            conn.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, 'user', ?)", (user_id, DEMO_USERNAME, hash_password(DEMO_PASSWORD), now))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM jobs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM resumes WHERE user_id = ?", (user_id,))

        resume_id, job_id, match_id = "cv_demo_linzhixia", "job_demo_enterprise", "m_demo_enterprise"
        conn.execute("""INSERT INTO resumes (id,user_id,name,file_name,file_type,file_path,status,raw_text,profile_json,direction_tag,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (resume_id,user_id,"林知夏 · ToB 产品经理（虚构）","demo-lin-zhixia.docx","docx","","parsed",RAW_RESUME,dumps(PROFILE),"产品",now,now))
        conn.execute("""INSERT INTO jobs (id,user_id,title,jd_text,jd_profile_json,company,location,source_url,employment_type,apply_status,starred,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (job_id,user_id,JD_PROFILE["title"],JD_TEXT,dumps(JD_PROFILE),JD_PROFILE["company"],"上海","","全职","待决策",1,now,now))
        conn.execute("""INSERT INTO match_runs (id,job_id,version,resume_id,resume_name,pref_id,pref_name,score,level,one_liner,dims_json,threshold,raw_score,strengths_json,gaps_json,jd_profile_json,report_json,llm_meta_json,judge_status,report_status,report_updated_at,judge_duration_ms,report_duration_ms,report_modules_json,jd_text_hash,starred,auto_report,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            match_id,job_id,1,resume_id,"林知夏 · ToB 产品经理（虚构）","","",86,"保","核心场景与证据高度重合，建议优化后投递。",dumps(DIMS),92,86,
            dumps(["客户门户与工单经验高度匹配","用户研究和数据闭环完整"]),dumps([{"severity":"fixable","text":"英语工作证据较少"}]),dumps(JD_PROFILE),dumps(REPORT),dumps({"demo":True}),"done","done",now,1200,4800,dumps({"m1":"done","m2":"done","m3":"done","m4":"done"}),"demo",1,1,now))
    print(f"Demo account ready: {DEMO_USERNAME} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
