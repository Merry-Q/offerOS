const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const api=(p,o={})=>apiAuth(p,o);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const toast=m=>{const e=$("#toast");e.textContent=m;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),2600)};
let resumes=[],selectedResume=null,currentImages=[],analysis=null,questions=[],questionIndex=0,recognition=null,transcriptText="";
const titles={home:["下一步从这里开始","今天解决哪件事？","先建立可信的职业档案，再用岗位证据做决策。"],profile:["你的求职基线","我的职业档案","画像可补充，但每条能力都保留来源。"],analyze:["从岗位证据出发","分析一个岗位","输入、确认、结论、依据和准备，保持在一条链路里。"],history:["可复用的判断","历史分析","回到任何一次岗位分析，继续准备。"]};
function go(v){$$(".view").forEach(x=>x.classList.toggle("active",x.id==="view-"+v));$$(".nav button").forEach(x=>x.classList.toggle("active",x.dataset.view===v));const t=titles[v];$("#pageEyebrow").textContent=t[0];$("#pageTitle").textContent=t[1];$("#pageSub").textContent=t[2];if(v==="history")loadHistory();scrollTo(0,0)}
async function boot(){
  const u=await requireLogin({admin:false});
  if(!u)return;
  $("#userBadge").textContent="林知夏（演示）";
  $$("[data-view]").forEach(b=>b.onclick=()=>go(b.dataset.view));
  $$("[data-go]").forEach(b=>b.onclick=()=>go(b.dataset.go));
  wire();
  renderPresets();
  await loadResumes();
}
function wire(){
 $("#resumeFile").onchange=e=>uploadResume(e.target.files[0]);
 $("#jdFiles").onchange=e=>addImages([...e.target.files]);
 $("#resetJd").onclick=resetJd;$("#fetchUrl").onclick=fetchUrl;$("#startAnalysis").onclick=startAnalysis;
 $$(".input-tabs button").forEach(b=>b.onclick=()=>{$$(".input-tabs button").forEach(x=>x.classList.toggle("active",x===b));$("#jdText").hidden=b.dataset.mode==="url";$("#urlBox").hidden=b.dataset.mode!=="url"});
 const d=$("#jdDrop");["dragenter","dragover"].forEach(n=>d.addEventListener(n,e=>{e.preventDefault();d.classList.add("over")}));["dragleave","drop"].forEach(n=>d.addEventListener(n,e=>{e.preventDefault();d.classList.remove("over")}));d.addEventListener("drop",e=>addImages([...e.dataTransfer.files].filter(f=>f.type.startsWith("image/"))));
 document.addEventListener("paste",e=>{if(!$("#view-analyze").classList.contains("active"))return;const fs=[...e.clipboardData.items].filter(x=>x.type.startsWith("image/")).map(x=>x.getAsFile());if(fs.length){e.preventDefault();addImages(fs)}});
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
async function loadResumes(){const d=await api("/api/resumes");resumes=d.items||[];selectedResume=resumes.find(r=>r.status==="parsed"&&!r.is_sample)||resumes.find(r=>r.status==="parsed")||null;renderResumePicker();renderProfile();fillResumeSelect()}
function renderResumePicker(){const root=$("#resumePicker");if(!resumes.length){root.innerHTML='<div class="empty">还没有职业档案，上传简历开始。</div>';return}root.innerHTML=`<select id="profileResumeSelect">${resumes.map(r=>`<option value="${esc(r.id)}" ${r.id===selectedResume?.id?"selected":""}>${esc(r.name)}${r.is_sample?"（示例）":""}</option>`).join("")}</select>`;$("#profileResumeSelect").onchange=e=>{selectedResume=resumes.find(r=>r.id===e.target.value);renderProfile();fillResumeSelect()}}
function arr(p,k){return Array.isArray(p?.[k])?p[k]:[]}
function profileItems(items){return items.length?items.map(x=>{const o=typeof x==="string"?{name:x}:x;return `<div class="item"><strong>${esc(o.name||o.role||o.text||"")}</strong>${o.source?`<span class="source">${esc(o.source)}</span>`:""}<div class="sub">${esc(o.evidence||o.reason||"")}</div></div>`}).join(""):'<div class="sub">暂无可靠信息，可手动补充。</div>'}
function renderProfile(){const root=$("#profileContent");if(!selectedResume){root.innerHTML="";return}const p=selectedResume.profile||{};const roles=arr(p,"suitable_roles");root.innerHTML=`<div class="card"><div class="section-head"><div><h2>${esc(selectedResume.name)}</h2><div class="sub">${esc(p.summary||"画像待完善")}</div></div>${selectedResume.is_sample?"":'<button class="btn" id="addAbility">添加简历外能力</button>'}</div><div class="profile-grid"><div class="profile-block"><h3>知识技能</h3>${profileItems(arr(p,"knowledge_skills").length?arr(p,"knowledge_skills"):arr(p,"skills"))}</div><div class="profile-block"><h3>工作经验</h3>${profileItems(arr(p,"work_experience"))}</div><div class="profile-block"><h3>核心能力</h3>${profileItems(arr(p,"core_abilities").length?arr(p,"core_abilities"):arr(p,"strengths"))}</div><div class="profile-block"><h3>个性特质</h3>${profileItems(arr(p,"personality_traits"))}</div></div></div><div class="card"><div class="section-head"><div><h2>适合投的职位 / 行业</h2></div></div>${roles.length?roles.map(r=>`<div class="item"><strong>${esc(r.role)}</strong> · ${esc((r.industries||[]).join("、"))}<div class="sub">${esc(r.reason)}</div></div>`).join(""):'<div class="empty">画像证据不足，补充经历后会生成方向建议。</div>'}</div><div class="card"><div class="section-head"><div><h2>面试题库与回答框架</h2><div class="sub">题目直接绑定你的真实能力证据。</div></div><button class="btn teal" id="openInterview">开始模拟面试</button></div><div id="questionBank">${makeQuestions(p).map((q,i)=>`<div class="item"><strong>${i+1}. ${esc(q.question)}</strong><div class="sub">${esc(q.framework)}</div></div>`).join("")}</div></div>`;$("#addAbility")?.addEventListener("click",addAbility);$("#openInterview").onclick=openInterview}
function makeQuestions(p){const seeds=[...arr(p,"core_abilities"),...arr(p,"work_experience"),...arr(p,"knowledge_skills")].slice(0,5);return (seeds.length?seeds:[{name:"最有代表性的项目"}]).map(x=>({question:`请用一个具体案例说明你的「${x.name||x}」能力。`,framework:"用 STAR：情境与目标 → 你的关键动作 → 可验证结果 → 复盘。"}))}
async function uploadResume(file){if(!file)return;const fd=new FormData();fd.append("file",file);toast("正在解析简历并建立画像…");try{await api("/api/resumes/upload",{method:"POST",body:fd});await loadResumes();toast("职业档案已生成")}catch(e){toast(e.message||"简历解析失败")}}
async function addAbility(){const name=prompt("填写要补充的能力（需真实可举证）");if(!name)return;const evidence=prompt("填写能证明这项能力的经历或事实");if(!evidence)return;const p=structuredClone(selectedResume.profile||{});p.core_abilities=arr(p,"core_abilities");p.core_abilities.push({name,evidence,source:"用户补充"});selectedResume=await api(`/api/resumes/${selectedResume.id}/profile`,{method:"PUT",body:{profile:p}});await loadResumes();toast("已加入职业档案")}
function fillResumeSelect(){const s=$("#matchResume");s.innerHTML=resumes.filter(r=>r.status==="parsed").map(r=>`<option value="${esc(r.id)}">${esc(r.name)}${r.is_sample?"（示例）":""}</option>`).join("");if(selectedResume)s.value=selectedResume.id}
function renderShots(){$("#shots").innerHTML=currentImages.map((x,i)=>`<div class="shot"><img src="${x.url}" alt="第${i+1}张岗位截图"><button aria-label="移除" data-i="${i}">×</button><div class="sub">第 ${i+1} 页 · ${esc(x.status)}</div></div>`).join("");$$(".shot button").forEach(b=>b.onclick=()=>{URL.revokeObjectURL(currentImages[b.dataset.i].url);currentImages.splice(b.dataset.i,1);renderShots()})}
async function addImages(files){for(const f of files){if(f.size>30*1024*1024){toast(`${f.name} 超过 30MB`);continue}currentImages.push({file:f,url:URL.createObjectURL(f),status:"等待识别"});renderShots()}await recognizePending()}
async function recognizePending(){const pending=currentImages.filter(x=>x.status==="等待识别");for(let i=0;i<pending.length;i++){const x=pending[i];x.status="识别中";renderShots();$("#ocrStatus").textContent=`正在识别 ${i+1}/${pending.length}，已识别内容会自动合并…`;const fd=new FormData();fd.append("file",x.file);try{const d=await api("/api/match/extract-jd-image",{method:"POST",body:fd});x.status="已识别";const text=(d.jd_text||"").trim();if(text)$("#jdText").value=[$("#jdText").value.trim(),text].filter(Boolean).join("\n\n")}catch(e){x.status="识别失败";x.error=e.message;toast(e.message||"截图识别失败")}renderShots()}$("#ocrStatus").textContent=pending.length?"识别完成。请确认合并文字与岗位信息。":"";if($("#jdText").value.trim().length>=20)await preAnalyze()}
async function preAnalyze(){try{const d=await api("/api/match/analyze-jd",{method:"POST",body:{jd_text:$("#jdText").value}});const p=d.jd_profile||{};$("#jobTitle").value=p.title||"";$("#company").value=p.company||"";$("#location").value=p.location||"";$("#employment").value=p.employment_type||"未知";analysis={jdProfile:p}}catch{}}
async function fetchUrl(){const url=$("#jdUrl").value.trim();if(!url)return toast("请填写岗位网页链接");$("#ocrStatus").textContent="正在读取网页…";try{const d=await api("/api/match/extract-jd-url",{method:"POST",body:{url}});if(!d.ok)throw new Error(d.notes||"网页未提取到完整 JD");$("#jdText").value=d.jd_text||"";$("#jobTitle").value=d.title||"";$("#company").value=d.company||"";$("#location").value=d.location||"";$("#employment").value=d.employment_type||"未知";await preAnalyze();$("#ocrStatus").textContent="网页读取完成，请确认岗位信息。"}catch(e){$("#ocrStatus").textContent=e.message;toast(e.message)}}
function resetJd(){currentImages.forEach(x=>URL.revokeObjectURL(x.url));currentImages=[];renderShots();["#jdText","#jdUrl","#jobTitle","#company","#location"].forEach(x=>$(x).value="");$("#employment").value="未知";$("#analysisResult").innerHTML="";$("#analysisProgress").textContent="";analysis=null}
async function startAnalysis(){
  const jd=$("#jdText").value.trim(),resumeId=$("#matchResume").value;
  if(jd.length<20)return toast("请先提供完整岗位描述，或点上方示例岗位");
  if(!resumeId)return toast("请先选择职业档案");
  $("#startAnalysis").disabled=true;
  $("#analysisProgress").textContent="正在匹配职业档案与岗位…";
  try{
    const run=await api("/api/match/run",{method:"POST",body:{
      jd_text:jd,resume_id:resumeId,jd_profile:analysis?.jdProfile||undefined,
      company:$("#company").value.trim(),location:$("#location").value.trim(),
      employment_type:$("#employment").value,source_url:$("#jdUrl").value.trim()||null,auto_report:true
    }});
    const research=run.research||{sources:[],research_note:run.reused?"已载入演示背调。":"正在补充公司背调…"};
    analysis={...run,jdProfile:run.jd_profile||analysis?.jdProfile||{},research};
    renderAnalysis(run,research,run.jd_profile||analysis.jdProfile);
    if(run.reused||run.report_status==="done"){
      $("#analysisProgress").textContent="分析完成";
      if(!run.research && $("#company").value.trim()){
        api("/api/match/research",{method:"POST",body:{company:$("#company").value.trim(),title:$("#jobTitle").value.trim()}})
          .then(d=>{analysis.research=d.research;renderAnalysis(analysis.match||run,d.research,analysis.jdProfile)}).catch(()=>{});
      }
      return;
    }
    const researchPromise=$("#company").value.trim()?api("/api/match/research",{method:"POST",body:{company:$("#company").value.trim(),title:$("#jobTitle").value.trim()}}).catch(()=>({research:{sources:[],research_note:"背调暂时不可用"}})):Promise.resolve({research:{sources:[],research_note:"JD 未提供公司名称，未执行公司背调。"}});
    const researchData=await researchPromise;
    analysis.research=researchData.research;
    await pollMatch(run.match_id);
  }catch(e){
    toast(e.message||"分析失败");
    $("#analysisProgress").textContent="分析失败："+(e.message||"请稍后重试。也可直接打开「历史分析」里的示例报告。");
  }finally{$("#startAnalysis").disabled=false}
}
async function pollMatch(id){for(let i=0;i<90;i++){const d=await api(`/api/match/runs/${id}`);analysis.match=d;renderAnalysis(d,analysis.research,analysis.jdProfile);if(d.report_status==="done"||d.report_status==="failed"){ $("#analysisProgress").textContent=d.report_status==="done"?"分析完成":"核心结论已完成，详细行动报告生成失败";return}$("#analysisProgress").textContent="匹配结论已完成，正在生成简历与面试建议…";await new Promise(r=>setTimeout(r,1800))}}
function sourceLinks(ids,sources){return (ids||[]).map(id=>{const s=(sources||[]).find(x=>x.id===id);return s?`<a class="citation" target="_blank" rel="noopener" href="${esc(s.url)}">[${id}] ${esc(s.title)}</a>`:""}).join(" · ")}
function researchSection(r){const sources=r?.sources||[];const block=(title,items)=>`<h3>${title}</h3>${(items||[]).length?(items||[]).map(x=>`<div class="item">${esc(x.conclusion)}<div>${sourceLinks(x.source_ids,sources)}</div></div>`).join(""):'<div class="sub">未检索到可核验信息。</div>'}`;return block("行业现状",r?.industry_status)+block("近半年业务动作",r?.company_moves)+block("融资与估值",r?.financing_valuation)+`<div class="sub">${esc(r?.research_note||"")}</div>`}
function renderAnalysis(m,r,p){const j=m.judge||{},report=m.report||{},warnings=j.hard_gate_warnings||[];$("#analysisResult").innerHTML=`<div class="card hero-result"><div><div class="score">${esc(j.score??"—")}</div><div class="verdict">${esc(j.level||"")}</div></div><div><h2>${esc(p?.title||m.title||"岗位结论")}</h2><p>${esc(j.one_liner||"")}</p>${warnings.length?`<div class="warning"><strong>硬门槛提醒（不修改原分与档位）</strong>${warnings.map(x=>`<div>${esc(x.gate)}：${esc(x.requirement)} · ${esc(x.candidate||"简历未体现")}</div>`).join("")}</div>`:""}</div></div><div class="card evidence-layout"><div class="evidence-rail"></div><div><section class="result-section"><h2>岗位结论</h2><div class="dims">${(j.dims||[]).map(x=>`<div class="dim"><span>${esc(x.name)} ${Math.round((x.w||0)*100)}%</span><div class="bar"><i style="width:${x.v}%"></i></div><b>${x.v}</b></div>`).join("")}</div></section><section class="result-section"><h2>为什么</h2>${researchSection(r)}<h3>岗位解析</h3><div class="grid2"><div><strong>硬门槛</strong>${Object.entries(p?.hard_gates||{}).map(([k,v])=>`<div class="item">${esc(v.requirement||"未要求")} <span class="source">${esc(v.strictness||"")}</span></div>`).join("")}</div><div><strong>加分项与核心能力</strong>${profileItems([...(p?.nice_to_haves||[]),...(p?.core_requirements||[])])}</div></div></section><section class="result-section"><h2>怎么准备</h2><h3>简历修改建议</h3>${renderRewrites(report.resume_rewrite||[])}<h3>面试准备</h3>${(report.interview||[]).slice(0,6).map(q=>`<div class="item"><strong>${esc(q.question)}</strong><div class="sub">${esc(q.framework||q.sample_outline||"")}</div></div>`).join("")||'<div class="sub">详细报告生成中…</div>'}</section></div></div>`}
function renderRewrites(xs){return xs.length?xs.map(x=>`<div class="item"><strong>${esc(x.section)}</strong><div class="sub">问题：${esc(x.problem)}</div><div>${esc(x.rewrite)}</div><div class="sub">${esc(x.why_better)}</div></div>`).join(""):'<div class="sub">详细报告生成中…</div>'}
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
    analysis={match:m,jdProfile:m.jd_profile||{},research};
    go("analyze");
    renderAnalysis(m,research,m.jd_profile);
    $("#analysisProgress").textContent="已打开历史分析";
    $("#analysisResult").scrollIntoView({behavior:"smooth",block:"start"});
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
