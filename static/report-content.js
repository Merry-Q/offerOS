/* Report content: company sources, separated requirements, and two interview tracks. */
function companyBackgroundSection(research){
  const r=research||{},sources=r.sources||[];
  const rows=r.company_background||[...(r.industry_status||[]),...(r.company_moves||[]),...(r.financing_valuation||[])].filter(row=>(row.source_ids||[]).length);
  const content=r.status==='pending'?'<p class="sub" role="status">正在通过百炼联网检索公司背景，核对公开来源…</p>':rows.length?rows.map(row=>`<div class="item company-background-item">${row.topic?`<strong>${esc(row.topic)}${row.kind==='分析'?' · 分析':row.kind==='原文摘录'?' · 原文摘录':''}</strong>`:''}<p>${esc(row.conclusion)}</p><div>${sourceLinks(row.source_ids,sources)}</div>${row.evidence_quotes?.length?`<details class="question-evidence"><summary>查看背景原文依据</summary>${row.evidence_quotes.map(e=>`<blockquote>${esc(e.quote)}</blockquote>`).join("")}</details>`:""}</div>`).join(''):'<p class="sub">暂无可引用的公司背景结论。</p>';
  return `<section class="company-background"><h3>公司背景</h3>${content}${r.research_note?`<p class="sub">${esc(r.research_note)}</p>`:''}${r.checked_at?`<p class="sub">检索于 ${esc(new Date(r.checked_at).toLocaleString('zh-CN'))} · 基于公开来源，事实与分析分别标示。</p>`:''}${r.status==='unavailable'?'<button type="button" class="btn" data-research-retry>重新背调</button>':''}</section>`;
}
document.addEventListener('click',event=>{
  if(event.target.closest('[data-research-retry]')&&analysis?.match&&analysis.research?.status!=='pending')loadCompanyBackground(analysis.match,analysisFlowVersion);
});
function requirementGroup(title,items){
  return `<section class="requirement-group"><h4>${title}</h4>${items?.length?profileItems(items):'<p class="sub">JD 未明确列出。</p>'}</section>`;
}
function questionList(title,items,{resume=false,pending=false}={}){
  if(!items?.length)return `<section class="interview-track"><h4>${title}</h4><p class="sub">${pending?'正在生成这一部分的面试准备…':resume?'当前简历未提供可定位的项目或工作经历，暂不生成经历问题。':'当前 JD 没有足够明确的业务或专业要求。'}</p></section>`;
  const bullets=(label,values)=>(values||[]).length?`<h5>${label}</h5><ul>${values.map(value=>`<li>${esc(value)}</li>`).join('')}</ul>`:'';
  return `<section class="interview-track"><h4>${title} <span class="sub">${items.length} 题</span></h4><p class="sub">${resume?'根据当前简历原文生成，在本地保留经历依据。':'围绕 JD 练习业务与专业知识，不预设已具备这些能力。'}</p>${items.map((q,i)=>`<article class="interview-question"><h5>${i+1}. ${esc(q.question)}</h5>${q.why_asked?`<p class="sub">考察点：${esc(q.why_asked)}</p>`:''}${q.requirement?`<p class="question-requirement">岗位依据：${esc(q.requirement)}</p>`:''}${q.evidence?`<details class="question-evidence"><summary>简历原文依据${q.line_start?' · 第 '+esc(q.line_start)+' 行':''}</summary><blockquote>${esc(q.evidence)}</blockquote></details>`:''}<p><strong>回答结构</strong>　${esc(q.framework||'先澄清问题和约束，再说明方案、取舍与验证。')}</p>${bullets('回答要点',q.answer_points)}<details class="question-depth"><summary>查看${resume?'追问与易错点':'知识点、追问与易错点'}</summary>${bullets('知识点',q.knowledge_points)}${bullets('继续追问',q.followups)}${bullets('避免踩坑',q.pitfalls)}</details><p class="sub">${q.source==='model_jd'?'百炼生成 · 公开 JD':q.source==='local_resume'?'本地生成 · 简历原文':'本地准备提纲 · 岗位要求'}</p></article>`).join('')}</section>`;
}
function interviewPreparationSection(report,status){
  const prep=report.interview_preparation||{},pending=status!=='done'&&status!=='failed';
  return `<h3>面试准备</h3>${questionList('简历侧问题 · 经历深挖',prep.resume_questions,{resume:true,pending})}${questionList('职位侧问题 · 业务与专业知识',prep.role_questions,{pending})}${prep.questions_to_ask?.length?`<section class="interview-track"><h4>可以反问面试官</h4><ul>${prep.questions_to_ask.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></section>`:''}`;
}
async function loadCompanyBackground(run,version,company=''){
  company=run.company||run.jd_profile?.company||company;
  if(!company){analysis.research={status:'unavailable',research_note:'JD 未提供公司名称，暂时无法背调。'};renderAnalysis(analysis.match,analysis.research,analysis.jdProfile);return;}
  if(analysis.research?.research_version===5&&['done','demo'].includes(analysis.research.status))return;
  analysis.research={status:'pending',sources:[]};
  renderAnalysis(analysis.match,analysis.research,analysis.jdProfile);
  try{
    const data=await api('/api/match/research',{method:'POST',body:{company,title:run.title||'',match_id:run.match_id}});
    if(!analysisIsCurrent(version))return;
    analysis.research=data.research;
  }catch(error){
    if(!analysisIsCurrent(version))return;
    analysis.research={status:'unavailable',research_note:error.message||'公司背景检索未完成，可稍后重新打开报告重试。'};
  }
  if(analysisIsCurrent(version)){
    renderAnalysis(analysis.match,analysis.research,analysis.jdProfile);
    if(analysis.match?.report_status==='done')$('#analysisProgress').textContent='分析完成';
  }
}
