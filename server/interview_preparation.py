"""Resume questions are grounded locally; model-generated role questions use public JD only."""
from __future__ import annotations
import re


def _strings(values):
    return [str(value).strip() for value in values if isinstance(value, str) and value.strip()] if isinstance(values, list) else []


def _requirements(jd):
    values = []
    for key in ('core_requirements', 'must_haves', 'nice_to_haves'):
        for row in jd.get(key) or []:
            text = str(row.get('text') or row.get('name') or row.get('requirement') or '') if isinstance(row, dict) else str(row)
            if text and text not in values:
                values.append(text)
    return values[:8]


TOPICS = [
    (r'AI|RAG|大模型|智能体|Agent', '怎样判断一个业务场景适合使用 RAG、Agent，还是传统流程？',
     ['先定义用户任务、知识更新频率与错误成本，再决定是否需要生成式方案。', '固定知识问答可比较检索增强与直接检索；多步骤工具调用才考虑Agent，并设置权限和人工确认。', '用带标准依据的评测集比较检索召回、回答正确率、引用准确率、拒答率、时延和单次成本。', '先做离线评测与小流量试点，设置失败兜底、版本记录和回滚标准。'],
     ['检索召回与生成准确性的区别', 'RAG的切分、召回、重排和引用', 'Agent工具权限、停止条件与可观测性']),
    (r'SQL|数据|指标|实验|A/B|激活|留存', '一个核心指标变好了，如何证明是产品改动带来的？',
     ['明确指标定义、统计周期、分母、去重口径和埋点质量。', '区分相对提升与百分点变化，按渠道、用户类型和时间分层排查。', '有条件时设计随机对照、提前设定主指标与护栏；避免样本偏差和多次窥探。', '无法做实验时交代对照方法、同期变化与归因限制，不把相关性表述为因果。'],
     ['漏斗、留存与队列口径', '实验分流、样本量和护栏指标', 'SQL去重、分组聚合与关联膨胀']),
    (r'用户|客户|需求|研究|访谈', '客户提出的功能要求很多，你如何找到真正值得解决的问题？',
     ['区分购买者、使用者和管理者，明确各自任务及现有替代方案。', '用近期真实行为追问发生频率、损失和处理流程，不只询问想要什么功能。', '将访谈观察与工单、行为数据交叉验证，区分个例与可重复模式。', '按问题影响、覆盖范围、战略目标及投入排序，先验证风险最高的假设。'],
     ['问题与方案的区分', '访谈样本偏差与证据交叉验证', '需求优先级与最小验证实验']),
    (r'SaaS|B端|企业|业务|商业|产品规划|路线图', '企业软件如何兼顾客户定制需求与产品标准化？',
     ['先画出业务角色、流程和客户分层，判断需求是否可复用。', '区分标准能力、配置能力和单客户定制，说明各自维护与升级成本。', '将商业价值、使用频率、交付风险和产品战略纳入取舍。', '通过试点明确验收、权限、数据隔离及推广条件，再规划规模化交付。'],
     ['企业软件的购买与使用链路', '标准化、配置化与定制的边界', '权限模型、数据隔离和交付验收']),
    (r'PRD|原型|设计|流程|交付|协作|研发', '如何把一个模糊业务诉求变成研发可验收的方案？',
     ['先定义目标、用户场景、范围和不做事项，确认问题及成功指标。', '描述主流程、异常流程、状态变化、权限与数据依赖。', '通过原型和评审对齐取舍，将需求拆成有依赖和优先级的交付单元。', '用可执行验收案例定义完成标准，上线后检查指标与异常并复盘。'],
     ['用户流程与状态机', '功能需求与非功能要求', '验收标准、灰度发布与回滚']),
]


def local_resume_questions(profile):
    sections = profile.get('resume_sections') or {}
    groups, group = [], []
    for record in sections.get('projects') or []:
        if record.get('label') == '项目名称' and group:
            groups.append(group); group = []
        group.append(record)
    if group:
        groups.append(group)
    if not groups:
        for key in ('work', 'internships'):
            records = [row for row in sections.get(key) or [] if re.search(r'成果|经历|内容|范围|协作|交付', str(row.get('label') or ''))]
            groups.extend([[row] for row in records[:3]])
    questions = []
    for records in groups[:3]:
        name = next((str(row['value']) for row in records if row.get('label') == '项目名称'), '')
        facts = [row for row in records if row.get('quote') and row.get('label') not in {'项目名称', '项目时间与角色'}]
        if not facts:
            facts = [row for row in records if row.get('quote')]
        if not facts:
            continue
        context = '「'+name+'」' if name else '简历中的这段经历'
        story = ' '.join(str(row.get('value') or '') for row in records)
        for variant in range(2):
            evidence = facts[min(variant, len(facts)-1)]
            question = f'在{context}中，你如何识别问题、选择方案，并明确自己负责的部分？' if variant == 0 else f'针对{context}，你如何证明结果、解释归因，并说明项目的边界？'
            specific = '区分问题判断、方案选择、验证方法与最终交付，不补充原文没有的结果。'
            probes = []
            if re.search(r'RAG|大模型|知识检索', story, re.I):
                question = f'在{context}中，为什么考虑RAG？用户流程、引用展示与拒答规则分别解决什么问题？' if variant == 0 else f'{context}的原型与评测实际做到了哪一步？如何验证引用可追溯，并说明尚未实施的部分？'
                specific = '围绕原文已有的检索流程、引用、拒答或评测内容说明设计取舍；明确原型、评测、训练与线上部署的边界。'
                probes = ['怎样选取评测问题，区分检索失败、回答错误与引用不支持结论？', '知识缺失或引用冲突时，拒答和人工兜底如何设计？']
            elif re.search(r'工单|分流', story):
                question = f'在{context}中，如何划分服务场景、设计推荐路径与人工兜底？' if variant == 0 else f'{context}中工单量变化的统计口径是什么？怎样排除入口流量、客户数量和同期流程变化的影响？'
                specific = '对照原文已有的场景分类、引导与兜底设计、实验或工单变化，说明对应的用户动作和统计范围。'
                probes = ['自助解决率提高时，如何监测错误分流、重复咨询与用户满意度？', '哪些问题必须转人工？实验比较的主指标和护栏分别是什么？']
            elif re.search(r'激活|漏斗|访谈', story):
                question = f'在{context}中，如何把访谈与漏斗观察转成优先级和产品方案？' if variant == 0 else f'{context}的激活率结果如何计算？怎样区分相对提升、百分点变化和因果归因？'
                specific = '对照原文已有的访谈、漏斗、灰度或激活结果，交代观察到的断点、方案选择与指标口径。'
                probes = ['访谈反馈与行为数据冲突时，你会先验证什么？', '基线、分母、观察周期和用户分群如何影响对结果的解释？']
            questions.append({'question': question, 'why_asked': '核对简历事实、个人贡献与岗位要求之间是否有完整证据链。',
                'evidence': evidence['quote'], 'evidence_id': evidence.get('id', ''), 'line_start': evidence.get('line_start'),
                'framework': '情境与约束 → 目标 → 个人动作与取舍 → 结果口径 → 边界与复盘',
                'answer_points': ['从下方原文中确认项目范围、你的职责和已有结果，不增添原文以外的经历。',
                    specific,
                    '如原文有指标，讲清基线、周期与统计口径；原文没有的数据或能力直接说明未体现。'],
                'followups': ['当时最重要的约束是什么？哪些决定由你负责？', '如何验证判断？如果重做一次，会先检验哪个假设？'] if variant == 0 else ['结果受哪些同期因素影响？有哪些不能归因于你的部分？', '哪些工作已完成，哪些仅停留在原型或方案阶段？'],
                'pitfalls': ['将团队结果全部归因于个人。', '为回答完整而补造项目、指标、工具经验或能力。'], 'source': 'local_resume'})
            if probes:
                questions[-1]['followups'] = probes
    return questions


def role_question_fallback(jd):
    reqs = _requirements(jd)
    text = ' '.join(reqs) + ' ' + str(jd.get('title') or '')
    questions = []
    for pattern, question, points, knowledge in TOPICS:
        matching = next((req for req in reqs if re.search(pattern, req, re.I)), '')
        if matching or re.search(pattern, text, re.I):
            questions.append({'question': question, 'requirement': matching or (reqs[0] if reqs else ''),
                'why_asked': '练习岗位要求中的方法判断、业务理解与专业知识，不预设你已掌握这些能力。',
                'framework': '定义问题 → 对比方案 → 明确取舍 → 设计验证 → 说明风险', 'answer_points': list(points),
                'knowledge_points': list(knowledge), 'followups': ['如果资源或时间减半，你会保留什么？', '哪些信号会让你推翻当前方案？'],
                'pitfalls': ['只罗列术语，不解释场景和取舍。', '把假设当成该公司的内部事实。'], 'source': 'local_jd'})
    for req in reqs:
        if len(questions) >= 6:
            break
        if any(q['requirement'] == req for q in questions):
            continue
        questions.append({'question': f'围绕“{req}”，你会如何拆解业务目标、设计方案并验证效果？', 'requirement': req,
            'why_asked': '检验岗位要求对应的业务分析与方法运用。', 'framework': '场景 → 目标 → 方案 → 取舍 → 验证',
            'answer_points': ['明确服务对象、使用场景、约束与成功标准。', '对比可选方案，说明前提、成本及主要风险。', '给出验证指标、异常兜底与复盘条件，不编造公司内部数据。'],
            'knowledge_points': ['该要求对应的基本概念与适用条件', '衡量效果的指标与常见误区'],
            'followups': ['什么情况下这个方案不成立？', '如何低成本验证最关键的假设？'], 'pitfalls': ['直接给方案，忽略业务目标。'], 'source': 'local_jd'})
    return questions[:6]


def enrich_interview_preparation(report, profile, jd):
    """Also adapts saved reports without making any model call or changing scores."""
    report = dict(report)
    role = []
    fallback = role_question_fallback(jd)
    jd_text = ' '.join(_requirements(jd))
    for question in report.get('interview') or []:
        if not isinstance(question, dict) or question.get('category') != '职位侧' or not _strings(question.get('answer_points')):
            continue
        # Numeric claims absent from the public JD need an explicit hypothetical label.
        points = [point for point in _strings(question.get('answer_points')) if not re.search(r'\d+(?:\.\d+)?\s*[%％]', point)
                  or re.search(r'假设|示例|例如', point) or all(number in jd_text for number in re.findall(r'\d+(?:\.\d+)?\s*[%％]', point))]
        if len(points) < 3:
            continue
        role.append({**question, 'answer_points': points, 'source': question.get('source') or 'model_jd'})
    for question in fallback:
        if len(role) >= 6:
            break
        if not any(q['question'] == question['question'] for q in role):
            role.append(question)
    report['interview_preparation'] = {'version': 2, 'resume_questions': local_resume_questions(profile),
        'role_questions': role[:8], 'questions_to_ask': _strings((report.get('interview_knowledge') or {}).get('questions_to_ask'))[:3]}
    return report
