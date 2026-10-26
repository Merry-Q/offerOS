/* GitHub Pages adapter: provides a self-contained, fictional product preview. */
(function () {
  if (!location.hostname.endsWith(".github.io")) return;

  const base = "/" + location.pathname.split("/").filter(Boolean)[0];
  window.OFFEROS_BASE = base === "/undefined" ? "" : base;

  const fact = (label, value, line) => ({
    label, value, quote: `${label}：${value}`, line_start: line, line_end: line,
  });
  const resume = {
    id: "cv_pages_demo",
    name: "林知夏 · ToB SaaS 产品经理（虚构示例）",
    file_name: "offeros-demo.txt",
    status: "parsed",
    is_sample: true,
    profile: {
      resume_sections: {
        basic: [
          fact("姓名", "林知夏（虚构人物）", 1),
          fact("职业方向", "ToB SaaS 产品经理", 2),
          fact("现居城市", "上海", 3),
        ],
        intention: [
          fact("目标岗位", "ToB SaaS 产品经理、客户体验产品经理", 5),
          fact("期望城市", "上海、杭州", 6),
        ],
        education: [
          fact("学历", "本科 · 信息管理与信息系统（虚构示例）", 8),
        ],
        work: [
          fact("职位", "产品经理 · 企业客户门户与工单产品", 10),
          fact("工作成果", "完成 32 场客户访谈；门户激活率提升 16%，人工工单量下降 19%（演示数据）", 11),
        ],
        internships: [],
        projects: [
          fact("项目名称", "客户门户 2.0（虚构项目）", 13),
          fact("项目行动", "通过访谈与 SQL 漏斗分析定位激活断点，完成 PRD、原型和灰度上线", 14),
        ],
        skills: [
          fact("产品方法", "用户研究、需求分析、PRD、原型设计、可用性测试", 16),
          fact("数据与实验", "SQL 基础查询、漏斗分析、指标口径、A/B 测试", 17),
        ],
        awards: [],
        other: [fact("演示声明", "所有人物、公司、项目与数字均为虚构内容", 19)],
      },
    },
  };

  const preset = {
    label: "高级产品经理（企业服务）",
    title: "高级产品经理（企业服务）",
    company: "星河云软件（虚构）",
    location: "上海",
    employment_type: "全职",
    jd_text: "负责企业客户服务产品规划，通过客户访谈和数据分析识别机会，协同设计、研发、客户成功和销售交付。要求本科及以上学历，3 年以上 ToB SaaS 产品经验，具备用户研究、数据分析与跨团队推动能力。",
  };
  const jdProfile = {
    title: preset.title, company: preset.company, location: preset.location,
    employment_type: preset.employment_type,
    hard_gates: {
      education: { requirement: "本科及以上", strictness: "硬性" },
      experience: { requirement: "3 年以上 ToB SaaS 经验", strictness: "硬性" },
    },
    must_haves: ["本科及以上学历", "3 年以上 ToB SaaS 经验"],
    core_requirements: ["用户研究", "数据分析", "跨团队推动"],
    nice_to_haves: ["客户门户或工单经验"],
  };
  const research = {
    status: "demo", research_version: 5,
    company_background: [{
      topic: "静态预览说明", kind: "分析",
      conclusion: "星河云软件为虚构公司，本卡片只用于展示产品交互与报告结构。",
      source_ids: [],
    }],
    sources: [], research_note: "GitHub Pages 不运行 FastAPI 后端；联网检索与真实分析需要完整服务。",
  };
  const match = {
    match_id: "match_pages_demo", title: preset.title, company: preset.company,
    jd_profile: jdProfile, research, report_status: "done",
    judge: {
      score: 86, level: "保", one_liner: "核心场景与简历证据高度重合。",
      hard_gate_warnings: [],
      dims: [
        { name: "知识技能", v: 86, w: 0.35 }, { name: "工作经验", v: 90, w: 0.25 },
        { name: "核心能力", v: 88, w: 0.25 }, { name: "个性特质", v: 78, w: 0.15 },
      ],
    },
    report: {
      interview_preparation: {
        resume_questions: [{
          question: "你如何从 32 场访谈中确定客户门户的优先级？",
          why_asked: "验证用户研究与决策闭环", framework: "问题分层 → 证据交叉验证 → 机会排序 → 结果复盘", source: "local_resume",
        }],
        role_questions: [{
          question: "如何定义企业客户门户的激活和留存？",
          requirement: "建立激活、留存和工单效率指标", framework: "目标 → 口径 → 埋点 → 验证", source: "local_outline",
        }],
        questions_to_ask: ["岗位前三个月的成功标准是什么？"],
      },
    },
    llm_meta: {},
  };

  const demoMatches = [
    match,
    {
      ...match,
      match_id: "match_pages_growth",
      title: "增长产品经理",
      company: "北屿数据（虚构）",
      jd_profile: { ...jdProfile, title: "增长产品经理", company: "北屿数据（虚构）", location: "北京", core_requirements: ["获客转化", "A/B 测试", "漏斗指标"] },
      judge: { ...match.judge, score: 61, level: "冲", one_liner: "能力可迁移，但增长实验证据不足。", dims: [{ name: "知识技能", v: 64, w: 0.35 }, { name: "工作经验", v: 58, w: 0.25 }, { name: "核心能力", v: 66, w: 0.25 }, { name: "个性特质", v: 55, w: 0.15 }] },
    },
    {
      ...match,
      match_id: "match_pages_success",
      title: "客户成功产品经理",
      company: "青禾云服（虚构）",
      jd_profile: { ...jdProfile, title: "客户成功产品经理", company: "青禾云服（虚构）", location: "杭州", core_requirements: ["客户成功", "服务流程", "留存指标"] },
      judge: { ...match.judge, score: 78, level: "稳", one_liner: "服务流程经验匹配，补充客户成功指标表述后可以稳投。", dims: [{ name: "知识技能", v: 78, w: 0.35 }, { name: "工作经验", v: 82, w: 0.25 }, { name: "核心能力", v: 80, w: 0.25 }, { name: "个性特质", v: 70, w: 0.15 }] },
    },
    {
      ...match,
      match_id: "match_pages_intern",
      title: "产品实习生（校园招聘）",
      company: "启明学院项目（虚构）",
      jd_profile: { ...jdProfile, title: "产品实习生（校园招聘）", company: "启明学院项目（虚构）", location: "远程", employment_type: "实习", core_requirements: ["在校生", "基础产品能力"] },
      judge: { ...match.judge, score: 44, level: "不建议投", one_liner: "年限和职责都高于实习定义，投递会显得方向混乱。", dims: [{ name: "知识技能", v: 60, w: 0.35 }, { name: "工作经验", v: 35, w: 0.25 }, { name: "核心能力", v: 52, w: 0.25 }, { name: "个性特质", v: 28, w: 0.15 }] },
    },
  ];
  const demoIds = ["enterprise", "growth", "success", "intern"];
  const demoJobs = demoMatches.map((item, index) => ({
    id: `job_pages_${demoIds[index]}`,
    title: item.title,
    company: item.company,
    location: item.jd_profile.location,
    employment_type: item.jd_profile.employment_type,
    matches: [{ id: item.match_id, level: item.judge.level, score: item.judge.score }],
  }));
  const demoDiscoveryItems = demoMatches.map((item, index) => ({
    id: `found_pages_${demoIds[index]}`,
    title: item.title,
    company: item.company,
    city: item.jd_profile.location,
    recruitment_type: item.jd_profile.employment_type,
    graduate_cohort: "未注明",
    category: "产品",
    open_evidence: "GitHub Pages 内置的虚构历史样例，用于展示已保存结果。",
    url: `https://example.com/offeros-demo/${demoIds[index]}`,
    source_host: "example.com",
    checked_at: "2026-10-23T12:00:00+08:00",
    gate_warnings: index === 3 ? ["岗位对象与当前经历阶段不匹配"] : [],
    score: item.judge.score,
    score_basis: { formula: "已识别技能标签 70 分 + 岗位方向 30 分", skill_points: Math.round(item.judge.score * 0.7), role_points: Math.round(item.judge.score * 0.3) },
    matched_tags: item.jd_profile.core_requirements.slice(0, 2),
    missing_tags: index === 1 ? ["增长实验"] : [],
  }));
  const demoDiscoveryRun = {
    id: "search_pages_demo",
    resume_id: resume.id,
    status: "done",
    stage: "done",
    error: null,
    created_at: "2026-10-23T12:00:00+08:00",
    updated_at: "2026-10-23T12:00:00+08:00",
    filters: {},
    rejected: [],
    stats: { checked: 12, duplicates: 2, result_limit: 24, stop_reason: "search_exhausted", previous_jobs: 0, history_excluded: 0 },
    items: demoDiscoveryItems,
  };

  const nativeFetch = window.fetch.bind(window);
  const jsonResponse = (data, status = 200) => new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json; charset=utf-8" },
  });
  window.fetch = async function (input, options = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const marker = url.pathname.indexOf("/api/");
    if (marker < 0) return nativeFetch(input, options);
    const path = url.pathname.slice(marker);
    const method = String(options.method || "GET").toUpperCase();

    if (path === "/api/auth/demo" && method === "POST") return jsonResponse({
      token: "pages-preview", user: { id: "pages-demo", username: "demo", role: "user" },
      presets: [preset], sample_answer: "请用 STAR 结构回答：情境、任务、行动、可验证结果。",
    });
    if (path === "/api/resumes" && method === "GET") return jsonResponse({ items: [resume], max_upload_mb: 5 });
    if (path === `/api/resumes/${resume.id}/source`) return jsonResponse({ raw_text: "林知夏（虚构人物）\nToB SaaS 产品经理\n\n完成 32 场客户访谈，门户激活率提升 16%，人工工单量下降 19%。" });
    if (path.startsWith("/api/discovery/profile/")) return jsonResponse({
      enabled: false, limit: 24, cities: ["上海", "杭州"], roles: ["ToB SaaS 产品经理"],
      recruitment_types: ["全职"], signals: { roles: ["ToB SaaS"], skills: ["用户研究", "数据分析"], degree: "本科", experience_bucket: "3 年以上" },
    });
    if (path === "/api/discovery/runs" && method === "GET") return jsonResponse({ items: [{
      id: demoDiscoveryRun.id, resume_id: resume.id, status: "done", stage: "done", error: null,
      created_at: demoDiscoveryRun.created_at, updated_at: demoDiscoveryRun.updated_at,
      item_count: demoDiscoveryItems.length, filters: {}, page: 1,
    }] });
    if (path === `/api/discovery/runs/${demoDiscoveryRun.id}` && method === "GET") return jsonResponse(demoDiscoveryRun);
    if (path.startsWith(`/api/discovery/runs/${demoDiscoveryRun.id}/items/`) && path.endsWith("/analyze") && method === "POST") {
      const found = demoDiscoveryItems.findIndex(item => path.includes(`/${item.id}/`));
      const result = demoMatches[Math.max(0, found)];
      return jsonResponse({ ...result, resume_id: resume.id, source_url: demoDiscoveryItems[Math.max(0, found)].url, jd_text: preset.jd_text, discovery: { quick_score: result.judge.score, checked_at: demoDiscoveryItems[Math.max(0, found)].checked_at, url: demoDiscoveryItems[Math.max(0, found)].url, score_version: "quick-v1" } });
    }
    if (path === "/api/jobs" && method === "GET") return jsonResponse({ items: demoJobs });
    if (path.startsWith("/api/match/runs/") && method === "GET") {
      const result = demoMatches.find(item => path.endsWith(`/${item.match_id}`));
      return result ? jsonResponse(result) : jsonResponse({ detail: "历史分析不存在" }, 404);
    }
    if (path === "/api/match/analyze-jd" && method === "POST") return jsonResponse({ jd_profile: jdProfile });
    if (path === "/api/match/run" && method === "POST") return jsonResponse(match);
    if (path === "/api/match/research" && method === "POST") return jsonResponse({ research });
    if (path.endsWith("/interview-report") && method === "POST") return jsonResponse({
      report: { overall: "回答已覆盖情境与行动，建议补充可验证的结果。", scores: { 结构: 82, 证据: 78 }, strengths: ["表达清晰"], improvements: ["补充数据结果"], next_practice: ["练习 90 秒 STAR 回答"] },
    });
    return jsonResponse({ detail: "GitHub Pages 静态预览不提供此后端功能。" }, 503);
  };

  document.addEventListener("DOMContentLoaded", () => {
    const note = document.querySelector("body > aside[role='note']");
    if (note) note.textContent = "GitHub Pages 静态交互预览：页面内的人物、岗位和分析均为浏览器内置的虚构样例。真实简历上传、联网搜索与持久化需要 FastAPI 后端。";
  });
})();
