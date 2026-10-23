const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const api=(p,o={})=>apiAuth(p,o);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const toast=m=>{const e=$("#toast");e.textContent=m;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),2600)};
let resumes=[],selectedResume=null,analysis=null,questions=[],questionIndex=0,recognition=null,transcriptText="";
const titles={discover:["","匹配岗位","从简历标签发现岗位，用招聘原页核验，再深入分析。"],home:["下一步从这里开始","今天解决哪件事？","先建立可信的职业档案，再用岗位证据做决策。"],profile:["你的求职基线","我的简历档案","上传简历，按模块核对信息；这些内容就是岗位匹配的依据。"],analyze:["从岗位证据出发","分析一个岗位","输入、确认、结论、依据和准备，保持在一条链路里。"],history:["可复用的判断","历史分析","回到任何一次岗位分析，继续准备。"]};
function go(v){window.history.replaceState(null,"",location.pathname+location.search+(v==="home"?"":"#"+v));$(".main").classList.toggle("archive-page",v==="profile");$$(".view").forEach(x=>x.classList.toggle("active",x.id==="view-"+v));$$(".nav button").forEach(x=>x.classList.toggle("active",x.dataset.view===v));const t=titles[v];$("#pageEyebrow").textContent=t[0];$("#pageTitle").textContent=t[1];$("#pageSub").textContent=t[2];if(v==="analyze"&&!$("#analysisResult").innerHTML.trim())setJdImportOpen(true);if(v==="history")loadHistory();if(v==="discover")loadDiscovery();scrollTo(0,0)}
async function boot(){
  const u=await requireLogin({admin:false});
  if(!u)return;
  $("#userBadge").textContent=u.username?.startsWith("archive_")?"个人简历档案":"林知夏（演示）";
  $$("[data-view]").forEach(b=>b.onclick=()=>go(b.dataset.view));
  $$("[data-go]").forEach(b=>b.onclick=()=>go(b.dataset.go));
  wire();
  renderPresets();
  await loadResumes();
  const initialView=location.hash.slice(1);if(titles[initialView])go(initialView);
}
function wire(){
 wireResumeArchive();wireDiscovery();wireAnalysisFlow();
 $("#resumeFile").onchange=e=>uploadResume(e.target.files[0]);
 $("#resetJd").onclick=resetJd;$("#fetchUrl").onclick=fetchUrl;$("#startAnalysis").onclick=startAnalysis;
 $$(".input-tabs button").forEach(b=>b.onclick=()=>{$$(".input-tabs button").forEach(x=>x.classList.toggle("active",x===b));$("#jdText").hidden=b.dataset.mode==="url";$("#urlBox").hidden=b.dataset.mode!=="url"});
 const d=$("#jdDrop");["dragenter","dragover"].forEach(n=>d.addEventListener(n,e=>{e.preventDefault();d.classList.add("over")}));["dragleave","drop"].forEach(n=>d.addEventListener(n,e=>{e.preventDefault();d.classList.remove("over")}));d.addEventListener("drop",()=>toast("截图识别已关闭，请粘贴岗位文本或使用公开招聘链接。"));
 document.addEventListener("paste",e=>{if($("#view-analyze").classList.contains("active")&&[...e.clipboardData.items].some(x=>x.type.startsWith("image/"))){e.preventDefault();toast("截图识别已关闭，请粘贴岗位文本或使用公开招聘链接。")}});
 $("#closeInterview").onclick=()=>{$("#interviewModal").classList.remove("open");recognition?.stop()};
 $("#startVoice").onclick=toggleVoice;
 $("#fillSample").onclick=fillSampleAnswer;
 $("#nextQuestion").onclick=nextQuestion;
 $("#finishInterview").onclick=finishInterview;
 $("#historyList").addEventListener("click",onHistoryClick);
}
function renderPresets(){
  const root=$("#demoPresets");
  if(!root)return;
  const items=window.__demoPresets||[];
  if(!items.length){root.innerHTML="";return}
  root.innerHTML=items.map((p,i)=>`<button type="button" class="chip" data-preset="${i}">${esc(p.label)}</button>`).join("");
  root.querySelectorAll("[data-preset]").forEach(b=>b.onclick=()=>applyPreset(items[Number(b.dataset.preset)]));
}
function applyPreset(p){
  if(!p)return;
  $("#jdText").hidden=false;$("#urlBox").hidden=true;
  $$(".input-tabs button").forEach(x=>x.classList.toggle("active",x.dataset.mode==="text"));
  $("#jdText").value=p.jd_text||"";
  $("#jobTitle").value=p.title||"";
  $("#company").value=p.company||"";
  $("#location").value=p.location||"";
  $("#employment").value=p.employment_type||"未知";
  analysis={jdProfile:{title:p.title,company:p.company,location:p.location,employment_type:p.employment_type}};
  toast("已填入示例岗位，点击「确认信息并开始分析」查看完整报告");
  $("#jdText").scrollIntoView({behavior:"smooth",block:"center"});
}
async function loadResumes(preferredId){
 const d=await api("/api/resumes");resumes=d.items||[];
 const wanted=preferredId||selectedResume?.id||localStorage.getItem(`offeros.resume.${getUser()?.id}`);
 selectedResume=resumes.find(r=>r.id===wanted)||resumes.find(r=>r.status==="parsed"&&!r.is_sample)||resumes[0]||null;
 window.archiveMaxUploadMb=d.max_upload_mb||5;
 $("#resumeUploadHint").textContent=`支持 PDF、DOCX、Markdown、TXT，单份不超过 ${window.archiveMaxUploadMb} MB。`;
 renderResumePicker();renderProfile();fillResumeSelect();
}
function renderResumePicker(){renderResumeArchivePicker()}
function arr(p,k){return Array.isArray(p?.[k])?p[k]:[]}
function profileItems(items){return items.length?items.map(x=>{const o=typeof x==="string"?{name:x}:x;return `<div class="item"><strong>${esc(o.name||o.role||o.text||"")}</strong>${o.source?`<span class="source">${esc(o.source)}</span>`:""}<div class="sub">${esc(o.evidence||o.reason||"")}</div></div>`}).join(""):'<div class="sub">暂无可靠信息，可手动补充。</div>'}
function renderProfile(){renderResumeArchive()}
function makeQuestions(p){const seeds=[...arr(p,"core_abilities"),...arr(p,"work_experience"),...arr(p,"knowledge_skills")].slice(0,5);return (seeds.length?seeds:[{name:"最有代表性的项目"}]).map(x=>({question:`请用一个具体案例说明你的「${x.name||x}」能力。`,framework:"用 STAR：情境与目标 → 你的关键动作 → 可验证结果 → 复盘。"}))}
async function uploadResume(file){
 if(!file||archiveUploading)return;
 const status=$("#resumeUploadStatus"),button=$("#resumeUploadButton");
 if(!/\.(pdf|docx|txt|md)$/i.test(file.name)){status.textContent="文件格式不支持，请选择 PDF、DOCX、Markdown 或 TXT。";status.classList.add("is-error");$("#resumeFile").value="";return}
 if(file.size>(window.archiveMaxUploadMb||5)*1024*1024||!file.size){status.textContent=file.size?`文件超过 ${window.archiveMaxUploadMb||5} MB，请压缩后重试。`:"文件为空，请重新选择。";status.classList.add("is-error");$("#resumeFile").value="";return}
 archiveUploading=true;button.disabled=true;$("#resumeFile").disabled=true;$("#resumeUpload").classList.add("is-loading");$("#resumeUpload").setAttribute("aria-busy","true");
 status.classList.remove("is-error");status.textContent=`正在上传并解析 ${file.name}，完成后会自动按模块归档…`;button.textContent="正在解析…";
 try{
  if(getUser()?.username==="demo"){
   const workspace=await api("/api/auth/workspace",{method:"POST"});
   if(workspace.token){setAuth(workspace.token,workspace.user);selectedResume=null;$("#userBadge").textContent="个人简历档案";}
  }
  const fd=new FormData();fd.append("file",file);
  const result=await api("/api/resumes/upload",{method:"POST",body:fd});
  await loadResumes(result.id);
  localStorage.setItem(`offeros.resume.${getUser()?.id}`,result.id);
  status.textContent=`${file.name} 已解析并保存，可以逐项查看原文依据。`;toast("简历档案已生成");
 }catch(error){status.textContent=error.message||"解析失败，请换一份包含文字的简历重试。";status.classList.add("is-error");await loadResumes().catch(()=>{});}
 finally{archiveUploading=false;button.disabled=false;$("#resumeFile").disabled=false;button.textContent="选择简历";$("#resumeFile").value="";$("#resumeUpload").classList.remove("is-loading");$("#resumeUpload").setAttribute("aria-busy","false");}
}
function fillResumeSelect(){const s=$("#matchResume");s.innerHTML=resumes.filter(r=>r.status==="parsed").map(r=>`<option value="${esc(r.id)}">${esc(r.name)}${r.is_sample?"（示例）":""}</option>`).join("");if(selectedResume)s.value=selectedResume.id}
async function preAnalyze(){try{const d=await api("/api/match/analyze-jd",{method:"POST",body:{jd_text:$("#jdText").value}});const p=d.jd_profile||{};$("#jobTitle").value=p.title||"";$("#company").value=p.company||"";$("#location").value=p.location||"";$("#employment").value=p.employment_type||"未知";analysis={jdProfile:p}}catch{}}
async function fetchUrl(){const url=$("#jdUrl").value.trim();if(!url)return toast("请填写岗位网页链接");$("#jdImportStatus").textContent="正在读取网页…";try{const d=await api("/api/match/extract-jd-url",{method:"POST",body:{url}});if(!d.ok)throw new Error(d.notes||"网页未提取到完整 JD");$("#jdText").value=d.jd_text||"";$("#jobTitle").value=d.title||"";$("#company").value=d.company||"";$("#location").value=d.location||"";$("#employment").value=d.employment_type||"未知";await preAnalyze();$("#jdImportStatus").textContent="网页读取完成，请确认岗位信息。"}catch(e){$("#jdImportStatus").textContent=e.message;toast(e.message)}}
function resetJd(){++analysisFlowVersion;lockAnalysisInputs(false);["#jdText","#jdUrl","#jobTitle","#company","#location"].forEach(x=>$(x).value="");$("#employment").value="未知";$("#analysisResult").innerHTML="";$("#analysisProgress").textContent="";$("#jdImportStatus").textContent="";analysis=null}
async function startAnalysis(){
  if(analysisFlowBusy)return;
  const jd=$("#jdText").value.trim(),resumeId=$("#matchResume").value;
  if(jd.length<20)return toast("请先提供完整岗位描述，或点上方示例岗位");
  if(!resumeId)return toast("请先选择职业档案");
  const parsed=analysis?.jdProfile;
  const body={jd_text:jd,resume_id:resumeId,jd_profile:parsed?.hard_gates&&Array.isArray(parsed.must_haves)?parsed:undefined,
    company:$("#company").value.trim(),location:$("#location").value.trim(),
    employment_type:$("#employment").value,source_url:$("#jdUrl").value.trim()||null,auto_report:true};
  const version=beginAnalysisResult({title:$("#jobTitle").value.trim()||"岗位分析",company:body.company});
  try{
    const run=await api("/api/match/run",{method:"POST",body});
    if(!analysisIsCurrent(version))return;
    const research=run.research||null;
    analysis={match:run,jdProfile:run.jd_profile||body.jd_profile||{},research};
    renderAnalysis(run,research,analysis.jdProfile);
    const background=loadCompanyBackground(run,version,body.company);
    if(run.reused||run.report_status==="done"){await background;$("#analysisProgress").textContent="分析完成";return}
    await Promise.all([pollMatch(run.match_id,version),background]);
  }catch(error){showAnalysisError(error,version);toast(error.message||"分析失败")}
  finally{finishAnalysisFlow(version)}
}
async function pollMatch(id,version=analysisFlowVersion){
  for(let i=0;i<90;i++){
    if(!analysisIsCurrent(version))return;
    const data=await api(`/api/match/runs/${id}`);
    if(!analysisIsCurrent(version))return;
    analysis.match=data;renderAnalysis(data,analysis.research,analysis.jdProfile);
    if(data.report_status==="done"||data.report_status==="failed"){
      $("#analysisProgress").textContent=data.report_status==="done"?(analysis.research?.status==="pending"?"面试准备已完成，公司背景仍在检索…":"分析完成"):"核心结论已完成，详细行动报告生成失败";return;
    }
    $("#analysisProgress").textContent="匹配结论已完成，正在生成面试准备…";
    await new Promise(resolve=>setTimeout(resolve,1800));
  }
  if(analysisIsCurrent(version))$("#analysisProgress").textContent="核心结论已保存，详细报告仍在生成，可稍后从历史分析继续查看。";
}

function sourceLinks(ids,sources){return (ids||[]).map(id=>{const s=(sources||[]).find(x=>x.id===id);return s?`<a class="citation" target="_blank" rel="noopener" href="${esc(s.url)}">[${id}] ${esc(s.title)}</a>`:""}).join(" · ")}
function researchSection(r){return companyBackgroundSection(r)}

function analysisSources(meta){
 const modules=meta.action?.modules;if(!modules)return "";
 const labels={m1:"岗位结论",m2:"要求对照",m4:"职位侧面试准备"};
 const stageSource=stage=>!stage?"未记录":stage.cached?"复用历史结果":stage.used?"百炼模型":"本地规则（模型未返回可用内容）";
 const parts=["JD解析："+stageSource(meta.jd),"评分："+stageSource(meta.judge),...Object.entries(labels).map(([key,label])=>{const stage=modules[key]||{};return label+"："+(stage.local?"本地原文":stage.used?"百炼模型":"本地规则（模型未返回可用内容）")})];
 return `<details class="discovery-report-source"><summary>查看报告生成来源</summary><p>${parts.map(esc).join("；")}。原文证据在本地绑定。</p></details>`;
}
function renderAnalysis(m,r,p){const j=m.judge||{},report=m.report||{},warnings=j.hard_gate_warnings||[];const provenance=m.discovery||m.llm_meta?.discovery||m.llm?.discovery||analysis?.discovery;const meta=m.llm_meta||m.llm||{};const origin=provenance?`<div class="discovery-report-source"><p>来自匹配岗位 · 列表快速分 ${esc(provenance.quick_score)}。列表按固定标签快速排序；下方长报告细化 JD 判断，两者口径不同，均不代表录用概率。</p><a href="${esc(provenance.url)}" target="_blank" rel="noopener noreferrer">查看招聘原页</a><span> · 重新核验于 ${esc(new Date(provenance.checked_at).toLocaleString('zh-CN'))}</span></div>`:'';const sourceNote=meta.judge&&!meta.judge.used&&!meta.judge.cached?'<p class="sub">判断来源：本地规则（百炼未返回可用判断）；请按原文逐条审阅。</p>':'';$("#analysisResult").innerHTML=`${origin}${sourceNote}${analysisSources(meta)}<div class="card hero-result"><div><div class="score">${esc(j.score??"—")}</div><div class="verdict">${esc(j.level||"")}</div></div><div><h2>${esc(p?.title||m.title||"岗位结论")}</h2><p>${esc(j.one_liner||"")}</p>${warnings.length?`<div class="warning"><strong>硬门槛提醒（不修改原分与档位）</strong>${warnings.map(x=>`<div>${esc(x.gate)}：${esc(x.requirement)} · ${esc(x.candidate||"简历未体现")}</div>`).join("")}</div>`:""}</div></div><div class="card evidence-layout"><div class="evidence-rail"></div><div><section class="result-section"><h2>岗位结论</h2><div class="dims">${(j.dims||[]).map(x=>`<div class="dim"><span>${esc(x.name)} ${Math.round((x.w||0)*100)}%</span><div class="bar"><i style="width:${x.v}%"></i></div><b>${x.v}</b></div>`).join("")}</div></section><section class="result-section"><h2>为什么</h2>${researchSection(r)}<h3>岗位解析</h3><div class="grid2"><div><strong>硬门槛</strong>${Object.entries(p?.hard_gates||{}).map(([k,v])=>`<div class="item">${esc(!v.requirement||v.requirement==="未要求"?"未提取到要求，请核对 JD":v.requirement)} <span class="source">${esc(!v.requirement||v.requirement==="未要求"?"待核对":v.strictness||"")}</span></div>`).join("")}</div><div>${requirementGroup("核心能力",p?.core_requirements)}${requirementGroup("加分项",p?.nice_to_haves)}</div></div></section><section class="result-section"><h2>怎么准备</h2>${interviewPreparationSection(report,m.report_status)}</section></div></div>`}

async function loadHistory(){
  const root=$("#historyList");
  if(!root)return;
  root.innerHTML='<div class="empty">正在加载历史分析…</div>';
  try{
    const d=await api("/api/jobs");
    const items=d.items||[];
    if(!items.length){root.innerHTML='<div class="empty">还没有历史分析。</div>';return}
    root.innerHTML=items.map(x=>{
      const m=(x.matches||[])[0]||{};
      return `<article><div class="row" style="justify-content:space-between"><strong>${esc(x.title)}</strong><span>${esc(m.level||"待分析")} · ${esc(m.score??"—")}</span></div><div class="sub">${esc([x.company,x.location,x.employment_type].filter(Boolean).join(" · "))}</div><button class="btn" style="margin-top:8px" data-job="${esc(x.id)}" data-match="${esc(m.id||"")}">打开分析</button></article>`;
    }).join("");
  }catch(e){
    root.innerHTML=`<div class="empty">历史分析加载失败：${esc(e.message||"请刷新后再试")}</div>`;
  }
}
async function onHistoryClick(e){
  const b=e.target.closest("[data-match]");
  if(!b||!b.dataset.match)return;
  b.disabled=true;
  try{
    const m=await api(`/api/match/runs/${b.dataset.match}`);
    const research=m.research||m.llm?.research||{sources:[],research_note:"历史分析未保存背调快照。"};
    openExistingAnalysis();
    analysis={match:m,jdProfile:m.jd_profile||{},research};
    renderAnalysis(m,research,m.jd_profile);
    go("analyze");
    $("#analysisProgress").textContent="已打开历史分析";
    focusAnalysisResult();
    loadCompanyBackground(m,analysisFlowVersion);
  }catch(err){toast(err.message||"无法打开分析")}
  finally{b.disabled=false}
}
function openInterview(){
  questions=makeQuestions(selectedResume?.profile||{});
  questionIndex=0;
  transcriptText="";
  $("#transcript").textContent="可以直接在这里打字，或点「填入示例回答」。";
  $("#interviewReport").innerHTML="";
  $("#interviewModal").classList.add("open");
  showQuestion();
}
function fillSampleAnswer(){
  const text=window.__demoSampleAnswer||"请用一个具体项目说明情境、你的动作和可验证结果。";
  $("#transcript").textContent=text;
  transcriptText=text;
  toast("已填入示例回答，可直接生成报告");
}
function currentTranscript(){
  const el=$("#transcript");
  const text=(el.innerText||el.textContent||"").trim();
  if(text && !text.startsWith("可以直接在这里") && !text.startsWith("转写内容")) return text;
  return transcriptText.trim();
}
async function finishInterview(){
  recognition?.stop();
  transcriptText=currentTranscript();
  if(transcriptText.length<10)return toast("请先打字回答、填入示例，或完成一段语音转写");
  $("#interviewReport").innerHTML='<div class="status">正在生成面试复盘…</div>';
  try{
    const d=await api(`/api/resumes/${selectedResume.id}/interview-report`,{method:"POST",body:{transcript:transcriptText,questions}});
    const r=d.report;
    $("#interviewReport").innerHTML=`<div class="card"><h3>面试报告</h3><p>${esc(r.overall)}</p><div class="grid2">${Object.entries(r.scores||{}).map(([k,v])=>`<div class="item"><strong>${esc(k)} ${esc(v)}</strong></div>`).join("")}</div><h4>做得好</h4>${profileItems(r.strengths||[])}<h4>需要改进</h4>${profileItems(r.improvements||[])}<h4>下一轮练习</h4>${profileItems(r.next_practice||[])}</div>`;
  }catch(e){toast(e.message||"报告生成失败")}
}
function showQuestion(){$("#interviewQuestion").textContent=`第 ${questionIndex+1}/${questions.length} 题：${questions[questionIndex]?.question||""}`}
function nextQuestion(){transcriptText+=`\n\n【${questions[questionIndex]?.question}】\n`;questionIndex=Math.min(questionIndex+1,questions.length-1);showQuestion()}
function toggleVoice(){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR)return toast("当前浏览器不支持实时语音转写，请使用最新版 Chrome 或 Edge");if(recognition){recognition.stop();recognition=null;$("#startVoice").textContent="继续实时转写";return}recognition=new SR();recognition.lang="zh-CN";recognition.continuous=true;recognition.interimResults=true;recognition.onresult=e=>{let interim="";for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i][0].transcript;if(e.results[i].isFinal)transcriptText+=t;else interim+=t}$("#transcript").textContent=transcriptText+interim};recognition.onend=()=>{recognition=null;$("#startVoice").textContent="继续实时转写"};recognition.start();$("#startVoice").textContent="停止转写"}
boot();
