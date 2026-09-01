"""Shared demo career-library assets so users can try matching without uploading."""
from __future__ import annotations

from typing import Any

from server.db import dumps, get_db, utc_now

SAMPLE_RESUME_ID = "cv_sample"

SAMPLE_PROFILE: dict[str, Any] = {
    "summary": "3 年 ToB SaaS 产品经理，擅长从用户访谈挖需求、用数据验证优先级，并推动跨职能落地。",
    "strengths": [
        "独立负责过 0→1 功能从调研到上线",
        "习惯用漏斗/留存指标评估方案效果",
        "能对齐销售、研发与客户成功的目标冲突",
    ],
    "weak": [
        "缺少超大型组织（500+人）协作经验",
        "技术背景偏产品侧，算法细节需搭档补充",
    ],
    "evidence": [
        "主导客户门户改版，激活率 +18%，支持工单 -22%",
        "搭建需求评审机制，平均交付周期从 6 周压到 4 周",
        "完成 40+ 用户访谈，沉淀机会树指导路线图",
    ],
    "skills": ["用户研究", "PRD", "数据分析", "A/B 测试", "跨团队协作"],
    "years": "3 年",
}

SAMPLE_JD_TEXT = """岗位名称：高级产品经理（ToB SaaS）

岗位职责：
1. 负责核心客户成功/门户相关产品方向，从洞察到落地全链路推进；
2. 通过用户访谈、数据分析与竞品研究，识别高价值机会并排优先级；
3. 撰写 PRD，组织评审，与设计、研发、销售协同交付；
4. 定义成功指标（激活、留存、工单等），持续迭代优化。

任职要求：
1. 3 年以上 ToB / SaaS 产品经验，有独立负责模块从 0→1 或重大改版经历；
2. 擅长用户研究与数据驱动决策，能清晰表达取舍理由；
3. 具备跨职能推动能力，能处理目标冲突；
4. 加分：有客户门户、工单/支持体系、或增长相关经验。
"""


def seed_sample_resume() -> None:
    now = utc_now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM resumes WHERE id = ?", (SAMPLE_RESUME_ID,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE resumes SET name = ?, status = ?, profile_json = ?, user_id = NULL, "
                "updated_at = ? WHERE id = ?",
                (
                    "示例 · ToB 产品经理",
                    "parsed",
                    dumps(SAMPLE_PROFILE),
                    now,
                    SAMPLE_RESUME_ID,
                ),
            )
            return
        conn.execute(
            "INSERT INTO resumes (id, user_id, name, file_name, file_type, file_path, status, "
            "raw_text, profile_json, created_at, updated_at) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                SAMPLE_RESUME_ID,
                "示例 · ToB 产品经理",
                "sample-pm-resume.txt",
                "txt",
                "",
                "parsed",
                "（示例简历，无真实文件）",
                dumps(SAMPLE_PROFILE),
                now,
                now,
            ),
        )


def is_sample_resume(resume_id: str) -> bool:
    return resume_id == SAMPLE_RESUME_ID
