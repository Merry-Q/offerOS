/* Parsed resume facts. Every displayed fact carries its own source quotation. */
const archiveSections = [
  ["basic", "基本信息"], ["intention", "求职期望"], ["education", "教育经历"],
  ["work", "工作经历"], ["internships", "实习经历"], ["projects", "项目经历"],
  ["skills", "技能与语言"], ["awards", "证书与获奖"], ["other", "其他简历信息"],
];
const archiveChevron = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
let archiveUploading = false;
let archiveSourceRequest = 0;

function resumeStatusLabel(resume) {
  return ({parsed:"已解析", failed:"解析失败", parsing:"解析中", uploaded:"待解析"})[resume.status] || "待解析";
}

function selectArchiveResume(id) {
  selectedResume = resumes.find(resume => resume.id === id) || null;
  if (selectedResume) localStorage.setItem(`offeros.resume.${getUser()?.id}`, selectedResume.id);
  archiveSourceRequest++;
  renderResumePicker();
  renderProfile();
  fillResumeSelect();
}

function renderResumeArchivePicker() {
  const picker = $("#resumePicker"), library = $("#resumeLibrary");
  if (!picker || !library) return;
  picker.innerHTML = selectedResume ? `<div class="archive-document-head"><div><h2>${esc(selectedResume.name)}</h2><p>${esc(selectedResume.file_name)} <span aria-hidden="true">·</span> ${esc(resumeStatusLabel(selectedResume))}</p></div><span class="archive-status ${selectedResume.status==='failed'?'is-error':''}">${esc(resumeStatusLabel(selectedResume))}</span></div>` : '<div class="archive-document-head"><h2>还没有简历档案</h2></div>';
  library.innerHTML = resumes.length ? resumes.map(resume => `<button type="button" class="archive-library-item ${resume.id===selectedResume?.id?'is-selected':''}" data-resume-id="${esc(resume.id)}" aria-pressed="${resume.id===selectedResume?.id}"><span>${esc(resume.name)}</span><small>${esc(resumeStatusLabel(resume))}${resume.is_sample||resume.id.startsWith('cv_demo_')?' · 虚构示例':''}</small></button>`).join("") : '<p class="archive-muted">上传一份简历，在这里切换与查看。</p>';
  library.querySelectorAll("[data-resume-id]").forEach(button => button.onclick = () => selectArchiveResume(button.dataset.resumeId));
}

function renderArchiveFact(fact) {
  const line = fact.line_start === fact.line_end ? `第 ${fact.line_start} 行` : `第 ${fact.line_start}–${fact.line_end} 行`;
  return `<div class="archive-fact ${fact.value.length>65?'is-wide':''}"><div class="archive-field-label">${esc(fact.label)}</div><div class="archive-value">${esc(fact.value)}</div><details class="archive-quote"><summary>原文依据 <span>${esc(line)}</span></summary><blockquote>${esc(fact.quote)}</blockquote></details></div>`;
}

function renderResumeArchive() {
  const root = $("#profileContent"), nav = $("#archiveOutline");
  if (!root || !nav) return;
  archiveSourceRequest++;
  if (!selectedResume) {
    root.innerHTML = '<div class="archive-empty"><h3>从简历开始，建立你的求职依据</h3><p>上传后，基本信息与经历会按模块归档，每项都可以核对原文。</p><button type="button" class="btn teal" id="archiveEmptyUpload">上传简历</button></div>';
    $("#archiveEmptyUpload").onclick = () => $("#resumeFile").click();
    nav.innerHTML = '';
    return;
  }
  const resume = selectedResume, profile = resume.profile || {}, sections = profile.resume_sections || {};
  const count = Object.values(sections).reduce((total, rows) => total + (Array.isArray(rows)?rows.length:0), 0);
  const isDemo = resume.is_sample || resume.id.startsWith("cv_demo_");
  const mode = isDemo ? "虚构示例 · 原文归档" : profile.parse_meta?.used ? "AI 解析 · 引用已核对" : "基础分段 · 未使用模型";
  nav.innerHTML = archiveSections.map(([key,label]) => `<a href="#archive-${key}">${label}<span>${(sections[key]||[]).length}</span></a>`).join("") + '<a href="#archive-original">简历原文</a>';
  root.innerHTML = `<div class="archive-context"><span class="archive-provenance">${esc(mode)}</span><span>${count} 条简历信息</span></div>
    <p class="archive-policy">这些信息就是岗位匹配的简历证据。未写出的能力按未具备处理，不从简历外补充。</p>
    ${resume.status==='failed'?'<div class="archive-error" role="alert"><strong>简历解析未完成</strong><p>请检查文件是否包含可读取的文字，再重新解析或上传其他文件。</p><button type="button" class="btn" id="archiveRetry">重新解析</button></div>':''}
    ${archiveSections.map(([key,label]) => {
      const rows = Array.isArray(sections[key]) ? sections[key] : [];
      return `<details class="archive-section" id="archive-${key}" ${rows.length||key==='basic'?'open':''}><summary><h3>${label}</h3><span class="archive-section-count">${rows.length?rows.length+' 条信息':'简历未体现'}</span>${archiveChevron}</summary><div class="archive-section-body">${rows.length?`<div class="archive-fields">${rows.map(renderArchiveFact).join('')}</div>`:'<p class="archive-section-empty">当前简历未体现此项，匹配时按未具备处理。</p>'}</div></details>`;
    }).join("")}
    <section class="archive-original" id="archive-original"><div><h3>简历原文</h3><p>查看从文件提取的完整文字，核对归档内容。</p></div><button type="button" class="btn" id="archiveShowSource" aria-expanded="false">查看原文</button><pre id="archiveSourceText" hidden></pre></section>
    <div class="archive-actions"><div><strong>用这份简历分析岗位</strong><p>仅引用本档案中的简历信息。</p></div><button type="button" class="btn teal" id="archiveAnalyze" ${resume.status!=='parsed'?'disabled':''}>分析一个岗位</button></div>
    <details class="archive-practice"><summary>基于简历练习面试</summary><p>围绕当前简历的经历提问，也可以输入回答完成练习。</p><button type="button" class="btn" id="openInterview" ${resume.status!=='parsed'?'disabled':''}>开始模拟面试</button></details>`;
  $("#archiveAnalyze").onclick = () => { fillResumeSelect(); go("analyze"); };
  $("#openInterview").onclick = openInterview;
  $("#archiveShowSource").onclick = showArchiveSource;
  $("#archiveRetry")?.addEventListener("click", retryArchiveParse);
  nav.querySelectorAll("a").forEach(link => link.addEventListener("click", event => {
    event.preventDefault();
    const target = document.getElementById(link.hash.slice(1));
    if (target?.tagName === "DETAILS") target.open = true;
    target?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    nav.querySelectorAll("a").forEach(a=>a.classList.toggle('is-active',a===link));
  }));
}

async function showArchiveSource() {
  const button = $("#archiveShowSource"), source = $("#archiveSourceText"), id = selectedResume?.id;
  if (!id || button.disabled) return;
  if (!source.hidden) {
    source.hidden = true;
    button.textContent = "查看原文";
    button.setAttribute("aria-expanded", "false");
    return;
  }
  const request = ++archiveSourceRequest;
  button.disabled = true;
  button.textContent = "正在读取…";
  try {
    const result = await api(`/api/resumes/${encodeURIComponent(id)}/source`);
    if (request !== archiveSourceRequest || selectedResume?.id !== id) return;
    source.textContent = result.raw_text || "文件没有可读取的文字，请重新上传包含文本的简历。";
    source.hidden = false;
    button.textContent = "收起原文";
    button.setAttribute("aria-expanded", "true");
  } catch (error) {
    if (request === archiveSourceRequest) { toast(error.message || "原文读取失败，请重试"); button.textContent = "重试读取原文"; }
  } finally { button.disabled = false; }
}

async function retryArchiveParse() {
  const id = selectedResume?.id, button = $("#archiveRetry");
  if (!id) return;
  button.disabled = true;
  button.textContent = "正在解析…";
  try { await api(`/api/resumes/${id}/parse`,{method:"POST"}); await loadResumes(id); toast("简历档案已更新"); }
  catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "重新解析"; }
}

function wireResumeArchive() {
  const drop = $("#resumeUpload");
  drop.addEventListener("dragover", event => { event.preventDefault(); if(!archiveUploading)drop.classList.add("is-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
  drop.addEventListener("drop", event => {
    event.preventDefault(); drop.classList.remove("is-over");
    if (archiveUploading) return;
    if (event.dataTransfer.files.length !== 1) return toast("请一次上传一份简历");
    uploadResume(event.dataTransfer.files[0]);
  });
}
