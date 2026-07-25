/* OfferOS frontend — talks to FastAPI backend */
async function api(path, options = {}) {
  return apiAuth(path, options);
}

function track(event, props = {}) {
  api("/api/analytics/track", { method: "POST", body: { event, props } }).catch(() => {});
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2400);
}

function formatMatchError(err) {
  const raw = String(err?.message || err || "");
  let detail = raw;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) detail = parsed;
  } catch {
    /* keep raw */
  }
  if (Array.isArray(detail)) {
    const missing = detail
      .filter((d) => d?.type === "missing" || d?.msg === "Field required")
      .map((d) => (Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null))
      .filter(Boolean);
    if (missing.length) return `请求缺少必填字段：${missing.join("、")}`;
    const first = detail[0];
    if (first?.msg) return String(first.msg);
  }
  if (raw.length > 120 || raw.trimStart().startsWith("[") || raw.trimStart().startsWith("{")) {
    return "匹配失败，请检查简历与 JD 后重试";
  }
  return raw || "匹配失败，请稍后重试";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

/** 简历解析假阶段进度（对齐匹配页 Agent 进度条） */
const PARSE_STAGES = ["上传文件…", "抽取文本…", "Resume Analyst 生成画像…"];
let parseProgress = null; // { id, name, fileName, stage, status, error, timer }
let parseBusy = false;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function resumeParseCardHtml(p) {
  const statusClass =
    p.status === "running" ? "running"
    : p.status === "done" ? "done"
    : p.status === "failed" ? "failed" : "";
  const pill =
    p.status === "running" ? `<span class="status-pill run">解析中</span>`
    : p.status === "done" ? `<span class="status-pill ok">完成</span>`
    : p.status === "failed" ? `<span class="status-pill idle">失败</span>`
    : `<span class="status-pill idle">待命</span>`;
  const stage =
    p.status === "failed"
      ? (p.error || "解析失败")
      : p.status === "done"
        ? "画像已生成"
        : (p.stage || PARSE_STAGES[0]);
  return `<article class="item-card resume-parse-card ${statusClass}" data-parse-id="${escapeHtml(p.id)}">
    <div class="item-card-head"><div>
      <h4 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        ${escapeHtml(p.name)} ${pill}
      </h4>
      <div class="sub">${escapeHtml(p.fileName || "")} · Resume Analyst</div>
    </div></div>
    <div class="progress"><i></i></div>
    <div class="parse-stage" data-parse-stage>${escapeHtml(stage)}</div>
  </article>`;
}

function startParseProgress({ id, name, fileName }) {
  stopParseProgressTimer();
  parseProgress = {
    id,
    name,
    fileName: fileName || "",
    stage: PARSE_STAGES[0],
    status: "running",
    error: "",
    stageIndex: 0,
    timer: null,
  };
  parseBusy = true;
  parseProgress.timer = setInterval(() => {
    if (!parseProgress || parseProgress.status !== "running") return;
    parseProgress.stageIndex = Math.min(
      parseProgress.stageIndex + 1,
      PARSE_STAGES.length - 1,
    );
    parseProgress.stage = PARSE_STAGES[parseProgress.stageIndex];
    const el = document.querySelector(`[data-parse-id="${CSS.escape(parseProgress.id)}"] [data-parse-stage]`);
    if (el) el.textContent = parseProgress.stage;
  }, 1100);
  return parseProgress;
}

function stopParseProgressTimer() {
  if (parseProgress?.timer) {
    clearInterval(parseProgress.timer);
    parseProgress.timer = null;
  }
}

function finishParseProgress(ok, errorMsg) {
  stopParseProgressTimer();
  if (!parseProgress) return;
  parseProgress.status = ok ? "done" : "failed";
  parseProgress.stage = ok ? "画像已生成" : (errorMsg || "解析失败");
  parseProgress.error = errorMsg || "";
  if (parseProgress.stageIndex !== undefined) {
    parseProgress.stageIndex = PARSE_STAGES.length - 1;
  }
}

function clearParseProgress() {
  stopParseProgressTimer();
  parseProgress = null;
  parseBusy = false;
}

async function runWithParseProgress({ id, name, fileName, onRender }, work) {
  startParseProgress({ id, name, fileName });
  onRender?.();
  try {
    const result = await work();
    finishParseProgress(true);
    onRender?.();
    await sleep(450);
    return result;
  } catch (err) {
    finishParseProgress(false, err.message || String(err));
    onRender?.();
    throw err;
  } finally {
    clearParseProgress();
    onRender?.();
  }
}

function setUploadControlsDisabled(disabled) {
  const libBtn = document.querySelector('button[onclick*="libFile"]');
  const libFile = document.getElementById("libFile");
  const obFile = document.getElementById("obFile");
  if (libBtn) libBtn.disabled = disabled;
  if (libFile) libFile.disabled = disabled;
  if (obFile) obFile.disabled = disabled;
}

let health = null;
let resumes = [];
let jobs = [];
let matchUnlocked = 0;
let jdDone = false;
let judged = false;
let rematchJobId = null;
let jdProfile = null;
let lastResult = null;
let runInFlight = false;

function canMatch() {
  return resumes.some((r) => r.status === "parsed");
}

function setSidebarVisible(visible) {
  document.getElementById("mainNav").hidden = !visible;
  document.body.classList.toggle("has-sidebar", visible);
}

async function boot() {
  const user = await requireLogin({ admin: false });
  if (!user) return;

  const badge = document.getElementById("userBadge");
  if (badge) {
    badge.style.display = "inline-flex";
    badge.textContent = user.username + (user.role === "admin" ? " · 管理员" : "");
    badge.className = "badge ok";
  }
  if (user.must_change_password) {
    showPasswordWarningBanner(true);
  }

  track("app_open");
  document.addEventListener("paste", onJdPaste);
  try {
    health = await api("/api/health");
  } catch (e) {
    toast("无法连接后端：" + e.message);
    return;
  }

  await refreshLibraries();
  if (health.onboarded || canMatch()) {
    setSidebarVisible(true);
    fillSelectors();
    showView("match");
    goMatch(0);
  } else {
    setSidebarVisible(false);
    showView("onboard");
  }
}

async function refreshLibraries() {
  const [r, j] = await Promise.all([
    api("/api/resumes"),
    api("/api/jobs"),
  ]);
  resumes = r.items || [];
  jobs = j.items || [];
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + name).classList.add("active");
  document.querySelectorAll("#mainNav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === name);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function switchView(name) {
  if (!canMatch() && name !== "library") {
    toast("请先完成建库（至少一份已解析简历）");
    showView("onboard");
    return;
  }
  if (name === "library") renderLibrary();
  if (name === "jobs") {
    await refreshLibraries();
    renderJobList();
  }
  if (name === "match") fillSelectors();
  showView(name);
}

/** 职业库 → JD 匹配（与侧边栏同一入口） */
function goToJdMatch() {
  if (!canMatch()) {
    toast("请先上传并解析至少一份简历");
    return;
  }
  switchView("match");
}

/* ===== Onboarding ===== */
async function obUpload(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  if (parseBusy) {
    toast("正在解析，请稍候");
    e.target.value = "";
    return;
  }
  const box = document.getElementById("obResumeResult");
  box.hidden = false;
  document.getElementById("obNext").disabled = true;
  setUploadControlsDisabled(true);

  const paint = () => {
    if (parseProgress) {
      box.innerHTML = resumeParseCardHtml(parseProgress);
    }
  };

  try {
    const item = await runWithParseProgress(
      {
        id: "__onboard__",
        name: file.name.replace(/\.[^.]+$/, "") || file.name,
        fileName: file.name,
        onRender: paint,
      },
      async () => {
        const fd = new FormData();
        fd.append("file", file);
        return api("/api/resumes/upload", { method: "POST", body: fd });
      },
    );
    await refreshLibraries();
    showObResume(item);
    document.getElementById("obNext").disabled = item.status !== "parsed";
    toast("简历画像已生成");
  } catch (err) {
    box.innerHTML = resumeParseCardHtml({
      id: "__onboard__",
      name: file.name,
      fileName: file.name,
      status: "failed",
      stage: err.message,
      error: err.message,
    });
    toast(err.message);
  } finally {
    setUploadControlsDisabled(false);
  }
  e.target.value = "";
}

function showObResume(r) {
  const box = document.getElementById("obResumeResult");
  box.hidden = false;
  const p = r.profile || {};
  box.innerHTML = `
    <strong>${escapeHtml(r.name)}</strong>（${escapeHtml(r.file_name)}）· <span class="badge ok">已解析</span>
    <div class="bullet">${escapeHtml(p.summary || "")}</div>
    <div class="bullet">证据：${(p.evidence || []).map(escapeHtml).join(" · ")}</div>
    <div class="bullet">弱项：${(p.weak || []).map(escapeHtml).join(" · ")}</div>`;
}

async function finishOnboarding() {
  if (!resumes.some((r) => r.status === "parsed")) {
    toast("请先上传并解析简历");
    return;
  }
  try {
    track("onboard_complete");
    await refreshLibraries();
    health = await api("/api/health");
    setSidebarVisible(true);
    fillSelectors();
    showView("match");
    goMatch(0);
    toast("职业库已建立");
  } catch (err) {
    toast(err.message);
  }
}

/* ===== Library ===== */
function renderLibrary() {
  const rl = document.getElementById("resumeList");
  if (!resumes.length && !(parseProgress && parseProgress.id === "__upload__")) {
    rl.innerHTML = `<div class="empty">还没有简历。点击「上传简历」。</div>`;
    return;
  }

  const parts = [];
  if (parseProgress && parseProgress.id === "__upload__") {
    parts.push(resumeParseCardHtml(parseProgress));
  }

  for (const r of resumes) {
    if (parseProgress && parseProgress.id === r.id) {
      parts.push(resumeParseCardHtml({
        ...parseProgress,
        name: parseProgress.name || r.name,
        fileName: parseProgress.fileName || r.file_name,
      }));
      continue;
    }
    const badge =
      r.status === "parsed" ? `<span class="badge ok">已解析</span>`
      : r.status === "parsing" ? `<span class="badge run">解析中</span>`
      : r.status === "failed" ? `<span class="badge err">失败</span>`
      : `<span class="badge idle">${escapeHtml(r.status)}</span>`;
    const p = r.profile;
    const detail = p ? `<div class="detail-box">
      <div class="bullet">${escapeHtml(p.summary || "")}</div>
      <div class="bullet">证据：${(p.evidence || []).map(escapeHtml).join(" · ")}</div>
      <div class="bullet">弱项：${(p.weak || []).map(escapeHtml).join(" · ")}</div>
    </div>` : "";
    const actionsDisabled = parseBusy ? "disabled" : "";
    parts.push(`<article class="item-card">
      <div class="item-card-head"><div>
        <h4>${escapeHtml(r.name)} ${badge}</h4>
        <div class="sub">${escapeHtml(r.file_name)} · 更新 ${fmt(r.updated_at)}</div>
      </div></div>
      ${detail}
      <div class="item-actions">
        <button class="btn btn-teal btn-sm" type="button" ${actionsDisabled} onclick="reparseResume('${r.id}')">重新解析</button>
        <button class="btn btn-secondary btn-sm" type="button" ${actionsDisabled} onclick="openResumeModal('${r.id}')">重命名</button>
        <button class="btn btn-danger btn-sm" type="button" ${actionsDisabled} onclick="deleteResume('${r.id}')">删除</button>
      </div>
    </article>`);
  }

  rl.innerHTML = parts.join("") || `<div class="empty">还没有简历。点击「上传简历」。</div>`;
}

async function libUpload(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  if (parseBusy) {
    toast("正在解析，请稍候");
    e.target.value = "";
    return;
  }
  setUploadControlsDisabled(true);
  try {
    await runWithParseProgress(
      {
        id: "__upload__",
        name: file.name.replace(/\.[^.]+$/, "") || file.name,
        fileName: file.name,
        onRender: () => renderLibrary(),
      },
      async () => {
        const fd = new FormData();
        fd.append("file", file);
        return api("/api/resumes/upload", { method: "POST", body: fd });
      },
    );
    await refreshLibraries();
    renderLibrary();
    fillSelectors();
    toast("画像已生成");
  } catch (err) {
    toast(err.message);
    await refreshLibraries();
    renderLibrary();
  } finally {
    setUploadControlsDisabled(false);
  }
  e.target.value = "";
}

async function reparseResume(id) {
  if (parseBusy) {
    toast("正在解析，请稍候");
    return;
  }
  const r = resumes.find((x) => x.id === id);
  if (!r) return;
  setUploadControlsDisabled(true);
  try {
    await runWithParseProgress(
      {
        id,
        name: r.name,
        fileName: r.file_name,
        onRender: () => renderLibrary(),
      },
      async () => api(`/api/resumes/${id}/parse`, { method: "POST" }),
    );
    await refreshLibraries();
    renderLibrary();
    fillSelectors();
    toast("解析完成");
  } catch (err) {
    toast(err.message);
    await refreshLibraries();
    renderLibrary();
  } finally {
    setUploadControlsDisabled(false);
  }
}

async function deleteResume(id) {
  if (!confirm("删除该简历？")) return;
  try {
    await api(`/api/resumes/${id}`, { method: "DELETE" });
    await refreshLibraries();
    renderLibrary();
    fillSelectors();
    toast("已删除");
  } catch (err) {
    toast(err.message);
  }
}

function openResumeModal(id) {
  const r = resumes.find((x) => x.id === id);
  if (!r) return;
  document.getElementById("resumeEditId").value = id;
  document.getElementById("resumeName").value = r.name;
  document.getElementById("resumeModal").classList.add("open");
}
function closeResumeModal() {
  document.getElementById("resumeModal").classList.remove("open");
}
async function saveResumeName() {
  const id = document.getElementById("resumeEditId").value;
  const name = document.getElementById("resumeName").value.trim();
  if (!name) return;
  try {
    await api(`/api/resumes/${id}`, { method: "PATCH", body: { name } });
    closeResumeModal();
    await refreshLibraries();
    renderLibrary();
    fillSelectors();
    toast("已重命名");
  } catch (err) {
    toast(err.message);
  }
}

/* ===== JD 截图识别 ===== */
let jdShotFileBlob = null;
let jdExtractBusy = false;

function setJdExtractStatus(msg) {
  const el = document.getElementById("jdExtractStatus");
  if (el) el.textContent = msg || "";
}

function clearJdShot() {
  jdShotFileBlob = null;
  const img = document.getElementById("jdShotImg");
  if (img) {
    img.removeAttribute("src");
  }
  document.getElementById("jdShotPreview")?.classList.remove("show");
  const btn = document.getElementById("btnExtractJd");
  if (btn) btn.disabled = true;
  const meta = document.getElementById("jdShotMeta");
  if (meta) meta.textContent = "未选择截图";
  setJdExtractStatus("");
  const f = document.getElementById("jdShotFile");
  if (f) f.value = "";
}

function showJdShotPreview(file) {
  const url = URL.createObjectURL(file);
  const img = document.getElementById("jdShotImg");
  img.onload = () => URL.revokeObjectURL(url);
  img.src = url;
  document.getElementById("jdShotPreview").classList.add("show");
  document.getElementById("btnExtractJd").disabled = false;
  const mb = (file.size / 1024 / 1024).toFixed(2);
  document.getElementById("jdShotMeta").textContent =
    `${file.name || "粘贴的截图"} · ${mb} MB`;
}

function validateJdImage(file) {
  const allowed = ["image/png", "image/jpeg", "image/jpg", "image/webp"];
  if (!file || !allowed.includes(file.type)) {
    toast("请使用 PNG / JPG / WebP 截图");
    return false;
  }
  if (file.size > 5 * 1024 * 1024) {
    toast("截图过大，上限 5MB，请重传");
    return false;
  }
  return true;
}

async function acceptJdShot(file) {
  if (!validateJdImage(file)) return;
  jdShotFileBlob = file;
  showJdShotPreview(file);
  await extractJdFromShot();
}

async function extractJdFromShot() {
  if (!jdShotFileBlob) {
    toast("请先粘贴或上传截图");
    return;
  }
  if (jdExtractBusy) return;
  jdExtractBusy = true;
  document.getElementById("btnExtractJd").disabled = true;
  setJdExtractStatus("正在识别截图中的岗位信息…");
  try {
    const fd = new FormData();
    fd.append("file", jdShotFileBlob, jdShotFileBlob.name || "jd-screenshot.png");
    const data = await api("/api/match/extract-jd-image", { method: "POST", body: fd });
    document.getElementById("jdInput").value = data.jd_text || "";
    setJdExtractStatus(
      data.notes
        ? `识别完成：${data.notes}。请核对下方文字后点击「确认并开始 JD 解析」。`
        : "识别完成。请核对下方文字后点击「确认并开始 JD 解析」。",
    );
    toast("识别完成，请核对文字");
  } catch (err) {
    setJdExtractStatus("识别失败，请重传更清晰的截图");
    toast(err.message || "识别失败，请重传截图");
  } finally {
    jdExtractBusy = false;
    document.getElementById("btnExtractJd").disabled = !jdShotFileBlob;
  }
}

function onJdShotFile(e) {
  const file = e.target.files?.[0];
  if (file) acceptJdShot(file);
}

function onJdShotDrop(e) {
  e.preventDefault();
  e.currentTarget.classList.remove("drag");
  const file = e.dataTransfer?.files?.[0];
  if (file) acceptJdShot(file);
}

function onJdPaste(e) {
  const matchView = document.getElementById("view-match");
  if (!matchView?.classList.contains("active")) return;
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) {
        e.preventDefault();
        acceptJdShot(file);
      }
      return;
    }
  }
}

/* ===== Match ===== */
function fillSelectors() {
  const rs = document.getElementById("selResume");
  const curR = rs.value;
  const parsed = resumes.filter((r) => r.status === "parsed");
  rs.innerHTML = parsed.map((r) =>
    `<option value="${r.id}">${escapeHtml(r.name)}（已解析）</option>`).join("")
    || `<option value="">暂无已解析简历</option>`;
  if ([...rs.options].some((o) => o.value === curR)) rs.value = curR;
}

function goMatch(n) {
  if (n > matchUnlocked) return;
  document.querySelectorAll("#view-match .step").forEach((el) => {
    const i = Number(el.dataset.step);
    el.classList.toggle("active", i === n);
    el.classList.toggle("done", i < n);
  });
  ["m0", "m1", "m2", "m3"].forEach((id, idx) => {
    document.getElementById(id).classList.toggle("active", idx === n);
  });
  if (n === 1 && !jdDone) runJdParse();
  if (n === 2 && !judged && !runInFlight) runJudgeAndReport();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function tryMatch(n) { if (n <= matchUnlocked) goMatch(n); }

function startNewMatch() {
  rematchJobId = null;
  matchUnlocked = 0; jdDone = false; judged = false; jdProfile = null; lastResult = null;
  document.getElementById("btnToJudge").disabled = true;
  document.getElementById("btnToReport").disabled = true;
  document.getElementById("matchTitle").textContent = "匹配一个新岗位";
  document.getElementById("rematchHint").hidden = true;
  document.getElementById("jdInput").value = "";
  clearJdShot();
  fillSelectors();
  switchView("match");
  goMatch(0);
}

function startRematch(jobId) {
  const job = jobs.find((j) => j.id === jobId);
  if (!job) return;
  rematchJobId = jobId;
  matchUnlocked = 0; jdDone = false; judged = false; jdProfile = null; lastResult = null;
  document.getElementById("btnToJudge").disabled = true;
  document.getElementById("btnToReport").disabled = true;
  document.getElementById("matchTitle").textContent = "重新匹配 · " + job.title;
  document.getElementById("rematchHint").hidden = false;
  document.getElementById("jdInput").value = job.jd_text;
  clearJdShot();
  setJdExtractStatus("已载入该岗位上次 JD 文本，可直接确认解析，或粘贴新截图覆盖。");
  fillSelectors();
  switchView("match");
  goMatch(0);
  toast("将新增版本，旧结果保留");
}

async function startAnalysis() {
  if (!canMatch()) { toast("请先准备至少一份已解析简历"); return; }
  const jd = document.getElementById("jdInput").value.trim();
  if (jd.length < 20) { toast("请先识别截图或粘贴完整 JD 文本"); return; }
  if (!document.getElementById("selResume").value) {
    toast("请选择简历画像"); return;
  }
  matchUnlocked = 1; jdDone = false; judged = false; jdProfile = null; lastResult = null;
  document.getElementById("btnToJudge").disabled = true;
  document.getElementById("btnToReport").disabled = true;
  goMatch(1);
}

async function runJdParse() {
  const resume = resumes.find((r) => r.id === document.getElementById("selResume").value);
  document.getElementById("resumeRef").innerHTML = `
    <div class="bullet"><strong>${escapeHtml(resume.name)}</strong> · ${escapeHtml(resume.profile?.summary || "")}</div>
    <div class="bullet">证据：${(resume.profile?.evidence || []).map(escapeHtml).join(" · ")}</div>
    <div class="bullet">弱项：${(resume.profile?.weak || []).map(escapeHtml).join(" · ")}</div>`;

  const card = document.getElementById("jdAgent");
  card.className = "agent-card running";
  const st = document.getElementById("jdStatus");
  st.className = "status-pill run"; st.textContent = "解析中";
  document.getElementById("jdOut").style.opacity = "0.35";

  try {
    const data = await api("/api/match/analyze-jd", {
      method: "POST",
      body: { jd_text: document.getElementById("jdInput").value.trim() },
    });
    jdProfile = data.jd_profile;
    document.getElementById("jdOut").innerHTML = `
      <div class="bullet"><strong>岗位档案：</strong>${escapeHtml(jdProfile.summary || jdProfile.title || "")}</div>
      <div class="bullet"><strong>强制门槛：</strong>${(jdProfile.must_haves || []).map(escapeHtml).join("；") || "—"}</div>
      <div class="bullet"><strong>核心要求：</strong>${(jdProfile.core_requirements || []).map(escapeHtml).join("；") || "—"}</div>
      <div class="bullet"><strong>JD 风险：</strong>${(jdProfile.risks || []).map(escapeHtml).join("；") || "—"}</div>`;
    document.getElementById("jdOut").style.opacity = "1";
    card.className = "agent-card done";
    st.className = "status-pill ok"; st.textContent = data.llm?.used ? "完成 · LLM" : "完成 · Mock";
    jdDone = true;
    matchUnlocked = 2;
    document.getElementById("btnToJudge").disabled = false;
  } catch (err) {
    card.className = "agent-card";
    st.className = "status-pill idle"; st.textContent = "失败";
    document.getElementById("jdOut").innerHTML = `<div class="bullet">${escapeHtml(err.message)}</div>`;
    document.getElementById("jdOut").style.opacity = "1";
    toast(err.message);
  }
}

async function runJudgeAndReport() {
  runInFlight = true;
  document.getElementById("levelBadge").textContent = "判分中…";
  document.getElementById("oneLiner").textContent = "Match Judge 工作中…";
  try {
    const data = await api("/api/match/run", {
      method: "POST",
      body: {
        jd_text: document.getElementById("jdInput").value.trim(),
        resume_id: document.getElementById("selResume").value,
        job_id: rematchJobId || null,
        jd_profile: jdProfile || null,
      },
    });
    rematchJobId = data.job_id;
    lastResult = data;
    const j = data.judge;
    animateJudge(j);
    document.getElementById("strengthList").innerHTML =
      (j.strengths || []).map((s) => `<div class="bullet">${escapeHtml(s)}</div>`).join("") || "—";
    document.getElementById("gapPreview").innerHTML =
      (j.gaps || []).map((g) => {
        const sev = g.severity === "fatal" ? "fatal" : g.severity === "important" ? "imp" : "fix";
        const label = g.severity === "fatal" ? "致命" : g.severity === "important" ? "重要" : "可快补";
        return `<div class="gap-item ${sev}"><span class="tag ${sev}">${label}</span> ${escapeHtml(g.text || "")}</div>`;
      }).join("") || "—";

    fillReport(data);
    judged = true;
    matchUnlocked = 3;
    document.getElementById("btnToReport").disabled = false;
    await refreshLibraries();
    toast(`已保存第 ${data.version} 版到匹配库`);
  } catch (err) {
    const friendly = formatMatchError(err);
    toast(friendly);
    document.getElementById("levelBadge").textContent = "失败";
    document.getElementById("oneLiner").textContent = "匹配未完成，请按提示修正后重试。";
  } finally {
    runInFlight = false;
  }
}

function renderDimBars(containerId, dims, animate) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const list = dims || [];
  el.innerHTML = list.map((d) =>
    `<div class="dim-row"><b>${escapeHtml(d.name)}</b><div class="bar"><i style="width:${animate ? 0 : (d.v || 0)}%"></i></div><span>${animate ? 0 : (d.v ?? 0)}</span></div>`
  ).join("");
  if (animate) {
    requestAnimationFrame(() => {
      list.forEach((d, i) => {
        const row = el.querySelectorAll(".dim-row")[i];
        if (!row) return;
        row.querySelector("i").style.width = (d.v || 0) + "%";
        row.querySelector("span").textContent = d.v ?? 0;
      });
    });
  }
}

function animateJudge(j) {
  const dims = j.dims || [];
  renderDimBars("dimBars", dims, true);
  document.getElementById("scoreNum").textContent = j.score;
  document.getElementById("scoreRing").style.background =
    `conic-gradient(var(--teal) 0 ${j.score}%, #e5edf2 0)`;
  document.getElementById("levelBadge").textContent = `${j.level} · ${j.score}`;
  document.getElementById("oneLiner").textContent = j.one_liner || "";
  document.getElementById("thresholdNote").textContent =
    `加权原始分 ${j.raw} · 门槛通过度 ${j.threshold} · 修正后 ${j.score}`;
}

function showReportTab(n) {
  document.querySelectorAll(".report-tabs button").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.tab) === n);
  });
  document.querySelectorAll(".report-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === "reportPane" + n);
  });
}

function fillReport(data) {
  const j = data.judge;
  const report = data.report || {};
  document.getElementById("modLevel").textContent = `${j.level} · ${j.score}`;
  document.getElementById("modConclusion").textContent = report.conclusion || j.one_liner || "";
  document.getElementById("modDims").innerHTML = (j.dims || []).map((d) =>
    `<div class="dim-row"><b>${escapeHtml(d.name)}</b><div class="bar"><i style="width:${d.v}%"></i></div><span>${d.v}</span></div>`
  ).join("") + `<div class="dim-row"><b>门槛</b><div class="bar"><i style="width:${j.threshold}%;background:var(--navy)"></i></div><span>${j.threshold}</span></div>`;

  const prefBit = data.pref_name ? ` · 偏好「${data.pref_name}」` : "";
  document.getElementById("reportMeta").textContent =
    `已写入匹配库 · ${data.title} · 第 ${data.version} 版 · 简历「${data.resume_name}」${prefBit}`;

  const tableBody = document.getElementById("modMatchBody");
  if (tableBody) {
    tableBody.innerHTML = (report.match_table || []).map((row) => {
      const cls = row.strength === "强" ? "strong" : row.strength === "中" ? "mid" : "weak";
      return `<tr><td>${escapeHtml(row.requirement)}</td><td>${escapeHtml(row.evidence)}</td><td><span class="tag ${cls}">${escapeHtml(row.strength)}</span></td></tr>`;
    }).join("") || `<tr><td colspan="3">暂无匹配表</td></tr>`;
  }

  const gapsEl = document.getElementById("modGaps");
  if (gapsEl) {
    const gaps = report.gaps_detail || j.gaps || [];
    gapsEl.innerHTML = gaps.map((g) => {
      const sev = g.severity === "fatal" ? "fatal" : g.severity === "important" ? "imp" : "fix";
      const label = g.severity === "fatal" ? "致命" : g.severity === "important" ? "重要" : "可快补";
      return `<div class="gap-item ${sev}"><span class="tag ${sev}">${label}</span> ${escapeHtml(g.text || "")}</div>`;
    }).join("") || "—";
  }
  const rw = document.getElementById("modRewrite");
  if (rw) {
    rw.innerHTML = (report.resume_rewrite || []).map((item) => `
      <div class="block"><strong>原文</strong><br>${escapeHtml(item.original || "")}</div>
      <div class="block"><strong>问题</strong><br>${escapeHtml(item.problem || "")}</div>
      <div class="block good"><strong>改写稿</strong><br>${escapeHtml(item.rewrite || "")}</div>
    `).join("") || "—";
  }
  const iv = document.getElementById("modInterview");
  if (iv) {
    iv.innerHTML = (report.interview || []).map((q) => `
      <div class="qa"><strong>${escapeHtml(q.question || "")}</strong><div class="frame">${escapeHtml(q.framework || "")}</div></div>
    `).join("") || "—";
  }
  showReportTab(1);
}

function openScoreModel() {
  document.getElementById("scoreDrawer").classList.add("open");
}

function renderJobList() {
  const root = document.getElementById("jobList");
  if (!jobs.length) {
    root.innerHTML = `<div class="empty">还没有匹配记录。</div>`;
    return;
  }
  root.innerHTML = jobs.map((job) => {
    const latest = (job.matches || [])[0];
    const versions = (job.matches || []).map((m, idx) => {
      const prefBit = m.pref_name ? ` · 偏好 ${escapeHtml(m.pref_name)}` : "";
      return `
      <div class="version-row ${idx === 0 ? "latest" : ""}">
        <div>
          <strong>第 ${m.version} 版</strong> · ${escapeHtml(m.level)} ${m.score}
          <div style="font-size:11px;color:var(--ink-3);margin-top:2px;">
            ${fmt(m.created_at)} · 简历 ${escapeHtml(m.resume_name)}${prefBit}
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" type="button" onclick="viewMatch('${job.id}','${m.id}')">查看</button>
      </div>`;
    }).join("");
    return `<article class="job-card">
      <div class="job-card-head">
        <div>
          <h3>${escapeHtml(job.title)}</h3>
          <div class="sub">${(job.matches || []).length} 个版本 · ${fmt(job.updated_at)}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          ${latest ? `<span class="level-badge level-stable">${escapeHtml(latest.level)} · ${latest.score}</span>` : ""}
          <button class="btn btn-teal btn-sm" type="button" onclick="startRematch('${job.id}')">重新匹配</button>
          <button class="btn btn-danger btn-sm" type="button" onclick="deleteJob('${job.id}')">删除</button>
        </div>
      </div>
      <div class="version-list">${versions}</div>
    </article>`;
  }).join("");
}

async function deleteJob(id) {
  if (!confirm("删除该岗位及全部版本？")) return;
  try {
    await api(`/api/jobs/${id}`, { method: "DELETE" });
    await refreshLibraries();
    renderJobList();
    toast("已删除");
  } catch (err) {
    toast(err.message);
  }
}

function viewMatch(jobId, matchId) {
  const job = jobs.find((j) => j.id === jobId);
  const m = job?.matches?.find((x) => x.id === matchId);
  if (!m) return;
  rematchJobId = jobId;
  lastResult = {
    job_id: jobId,
    match_id: m.id,
    version: m.version,
    title: job.title,
    judge: {
      score: m.score,
      level: m.level,
      one_liner: m.one_liner,
      dims: m.dims,
      threshold: m.threshold,
      raw: m.raw_score,
      strengths: m.strengths,
      gaps: m.gaps,
    },
    report: m.report,
    resume_name: m.resume_name,
    pref_name: m.pref_name,
  };
  matchUnlocked = 3; jdDone = true; judged = true;
  document.getElementById("jdInput").value = job.jd_text;
  document.getElementById("matchTitle").textContent = `历史 · ${job.title} · 第 ${m.version} 版`;
  animateJudge(lastResult.judge);
  document.getElementById("strengthList").innerHTML =
    (m.strengths || []).map((s) => `<div class="bullet">${escapeHtml(s)}</div>`).join("");
  document.getElementById("gapPreview").innerHTML =
    (m.gaps || []).map((g) => {
      const sev = g.severity === "fatal" ? "fatal" : g.severity === "important" ? "imp" : "fix";
      const label = g.severity === "fatal" ? "致命" : g.severity === "important" ? "重要" : "可快补";
      return `<div class="gap-item ${sev}"><span class="tag ${sev}">${label}</span> ${escapeHtml(g.text || "")}</div>`;
    }).join("");
  fillReport(lastResult);
  document.getElementById("btnToJudge").disabled = false;
  document.getElementById("btnToReport").disabled = false;
  showView("match");
  goMatch(3);
}

boot();
