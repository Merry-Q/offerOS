/* On-demand discovery; only allowlisted career signals reach the model. */
let discoveryConfig=null, discoveryRun=null, discoveryEpoch=0, discoveryBusy=false, discoveryAnalyzing=false, discoveryActiveTitle="";
let discoveryHistory=[], discoveryCache=new Map(), discoveryViewVersion=0, discoveryActiveRunId=null, discoveryViewLoading=false;
const discoveryStages={queued:"准备搜索",searching:"联网搜索岗位",verifying:"核验详情与在招依据",scoring:"计算快速匹配分",done:"搜索完成",failed:"搜索未完成"};
function wireDiscovery(){
  $("#discoverSearch").onclick=startDiscovery;
  $("#discoverResume").onchange=e=>{selectArchiveResume(e.target.value);loadDiscovery()};
  $("#discoverPrevious").onclick=()=>stepDiscoveryPage(-1);
  $("#discoverNext").onclick=()=>stepDiscoveryPage(1);
  $("#discoverPage").onchange=e=>viewDiscoveryPage(e.target.value);
  $("#discoverResults").addEventListener("click",e=>{const button=e.target.closest("[data-discover-analyze]");if(button)analyzeDiscovered(button);const page=e.target.closest("[data-discover-step]");if(page)stepDiscoveryPage(Number(page.dataset.discoverStep))});
}
function rememberDiscoveryPage(id){try{sessionStorage.setItem(`discoveryPage:${selectedResume.id}`,id)}catch{}}
function savedDiscoveryPage(){try{return sessionStorage.getItem(`discoveryPage:${selectedResume.id}`)}catch{return null}}
function cacheDiscoveryRun(run){
  discoveryCache.set(run.id,run);
  const entry=discoveryHistory.find(item=>item.id===run.id);
  const metadata={id:run.id,status:run.status,created_at:run.created_at,item_count:run.items.length,filters:run.filters};
  if(entry)Object.assign(entry,metadata);else discoveryHistory.push({...metadata,page:discoveryHistory.length+1});
}
function renderDiscoveryHistory(){
  const nav=$("#discoverHistory"),index=discoveryHistory.findIndex(item=>item.id===discoveryRun?.id);
  nav.hidden=!discoveryHistory.length;
  if(nav.hidden)return;
  const active=discoveryHistory.find(item=>item.id===discoveryActiveRunId);
  $("#discoverHistoryNote").textContent=`共 ${discoveryHistory.length} 页，每页保留当次结果。`+(active?`第 ${active.page} 页正在搜索，可先查看其他页。`:"再次搜索会新增一页。");
  $("#discoverPage").innerHTML=discoveryHistory.map(item=>`<option value="${esc(item.id)}" ${item.id===discoveryRun?.id?'selected':''}>第 ${item.page} 页 · ${esc(new Date(item.created_at).toLocaleString('zh-CN'))} · ${item.item_count} 个岗位${item.status==='running'?' · 搜索中':item.status==='failed'?' · 未完成':''}</option>`).join("");
  $("#discoverPage").disabled=discoveryAnalyzing||discoveryViewLoading;
  $("#discoverPrevious").disabled=index<=0||discoveryAnalyzing||discoveryViewLoading;
  $("#discoverNext").disabled=index<0||index>=discoveryHistory.length-1||discoveryAnalyzing||discoveryViewLoading;
}
function stepDiscoveryPage(step){
  const index=discoveryHistory.findIndex(item=>item.id===discoveryRun?.id),next=discoveryHistory[index+step];
  if(next)viewDiscoveryPage(next.id);
}
async function viewDiscoveryPage(id){
  const epoch=discoveryEpoch,version=++discoveryViewVersion;
  discoveryViewLoading=true;renderDiscoveryHistory();
  try{
    const run=discoveryCache.get(id)||await api(`/api/discovery/runs/${encodeURIComponent(id)}`);
    if(epoch!==discoveryEpoch||version!==discoveryViewVersion)return;
    discoveryRun=run;cacheDiscoveryRun(run);rememberDiscoveryPage(id);renderDiscoveryRun(run);
  }catch(error){if(epoch===discoveryEpoch&&version===discoveryViewVersion){toast('搜索页读取失败：'+error.message);$("#discoverStatus").textContent='搜索页读取失败，可重新翻页重试：'+error.message}}
  finally{if(epoch===discoveryEpoch&&version===discoveryViewVersion){discoveryViewLoading=false;renderDiscoveryHistory()}}
}
async function loadDiscovery(){
  const epoch=++discoveryEpoch;
  ++discoveryViewVersion;discoveryHistory=[];discoveryCache=new Map();discoveryActiveRunId=null;discoveryViewLoading=false;
  discoveryBusy=false;
  discoveryRun=null;
  renderDiscoveryHistory();$("#discoverStages").innerHTML='';
  $("#discoverResume").innerHTML=resumes.filter(r=>r.status==="parsed").map(r=>`<option value="${esc(r.id)}" ${r.id===selectedResume?.id?'selected':''}>${esc(r.name)}</option>`).join("");
  $("#discoverResults").innerHTML='';
  $("#discoverStatus").textContent="正在读取简历标签…";
  $("#discoverSearch").disabled=true;
  if(!selectedResume||selectedResume.status!=="parsed"){
    $("#discoverStatus").textContent="请先在简历档案上传并解析简历。";
    $("#discoverSignals").textContent="尚无可用简历标签";return;
  }
  try{
    const [config,history]=await Promise.all([api(`/api/discovery/profile/${encodeURIComponent(selectedResume.id)}`),api(`/api/discovery/runs?resume_id=${encodeURIComponent(selectedResume.id)}`)]);
    if(epoch!==discoveryEpoch)return;
    discoveryConfig=config;
    discoveryLock(false);
    for(const [id,values,label] of [["discoverCity",config.cities,"不限城市"],["discoverRole",config.roles,"按简历方向"],["discoverType",config.recruitment_types,"不限招聘类型"]]){
      const select=$("#"+id),previous=select.value;
      select.innerHTML=`<option value="">${label}</option>`+values.map(v=>`<option>${esc(v)}</option>`).join("");
      if(values.includes(previous))select.value=previous;
    }
    renderDiscoverySignals(config.signals);
    $("#discoverSearch").disabled=!config.enabled;
    $("#discoverStatus").textContent=config.enabled?"准备好后开始搜索，每次最多展示 "+config.limit+" 个通过核验的岗位。":"联网搜索尚未开启：请在本地配置 DASHSCOPE_API_KEY，设置 LLM_MODE=auto 并重启服务。";
    discoveryHistory=history.items||[];
    const page=discoveryHistory.find(item=>item.id===savedDiscoveryPage())||discoveryHistory.at(-1);
    if(page){
      await viewDiscoveryPage(page.id);
      if(epoch!==discoveryEpoch)return;
      if(!discoveryRun){renderDiscoveryHistory();return}
      for(const [id,key] of [["discoverCity","city"],["discoverRole","role"],["discoverType","recruitment_type"]])$("#"+id).value=discoveryRun.filters?.[key]||"";
      const active=discoveryHistory.find(item=>item.status==="running");
      if(active)pollDiscovery(active.id,epoch);
    }
    else $("#discoverResults").innerHTML='<div class="discovery-empty"><h2>从当前简历，找到值得细看的岗位</h2><p>搜索后只保留可读取完整职责与要求、并具有在招依据的详情页。未注明的信息保留为「未注明」。</p></div>';
  }catch(e){if(epoch===discoveryEpoch)$("#discoverStatus").textContent="读取失败："+e.message}
}
function renderDiscoverySignals(signals){
  const tags=[...(signals.roles||[]),...(signals.skills||[]),"学历："+signals.degree,"经验："+signals.experience_bucket];
  $("#discoverSignals").innerHTML=tags.map(tag=>`<span>${esc(tag)}</span>`).join("");
}
function discoveryLock(locked){
  discoveryBusy=locked;
  locked=locked||discoveryAnalyzing;
  for(const id of ["discoverResume","discoverCity","discoverRole","discoverType"])$("#"+id).disabled=locked;
  $("#discoverSearch").disabled=locked||!discoveryConfig?.enabled;
  $("#discoverSearch").textContent=discoveryAnalyzing?"正在分析所选岗位…":locked?"搜索进行中…":"搜索匹配岗位";
  renderDiscoveryHistory();
}
async function startDiscovery(){
  if(discoveryBusy||discoveryAnalyzing||!selectedResume)return;
  discoveryLock(true);
  const epoch=discoveryEpoch;
  const filters={city:$("#discoverCity").value,role:$("#discoverRole").value,recruitment_type:$("#discoverType").value};
  try{
    const privateSpace=await api("/api/auth/workspace",{method:"POST",body:{clone_resume_id:selectedResume.id}});
    if(privateSpace.token){setAuth(privateSpace.token,privateSpace.user);$("#userBadge").textContent="个人体验空间";await loadResumes(privateSpace.resume_id);$("#discoverResume").innerHTML=resumes.filter(r=>r.status==="parsed").map(r=>`<option value="${esc(r.id)}" ${r.id===selectedResume?.id?'selected':''}>${esc(r.name)}</option>`).join("")}
    if(epoch!==discoveryEpoch)return;
    discoveryRun=await api("/api/discovery/search",{method:"POST",body:{resume_id:selectedResume.id,...filters}});
    if(epoch!==discoveryEpoch)return;
    ++discoveryViewVersion;discoveryViewLoading=false;
    cacheDiscoveryRun(discoveryRun);rememberDiscoveryPage(discoveryRun.id);
    renderDiscoveryRun(discoveryRun);
    await pollDiscovery(discoveryRun.id,epoch);
  }catch(e){$("#discoverStatus").textContent=e.message;toast(e.message)}
  finally{if(epoch===discoveryEpoch)discoveryLock(false)}
}
async function pollDiscovery(id,epoch){
  discoveryActiveRunId=id;
  discoveryLock(true);
  try{
    for(let i=0;i<300;i++){
      const run=await api(`/api/discovery/runs/${encodeURIComponent(id)}`);
      if(epoch!==discoveryEpoch)return;
      cacheDiscoveryRun(run);
      if(discoveryRun?.id===id){discoveryRun=run;renderDiscoveryRun(run)}
      renderDiscoveryHistory();
      if(run.status!=="running")return;
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
    if(discoveryRun?.id===id)$("#discoverStatus").textContent="搜索仍在处理，稍后重新打开此页可恢复进度。";
  }catch(e){if(epoch===discoveryEpoch)$("#discoverStatus").textContent="进度读取中断，可重新打开此页恢复："+e.message}
  finally{if(epoch===discoveryEpoch){discoveryActiveRunId=null;discoveryLock(false)}}
}
function renderDiscoveryRun(run){
  renderDiscoveryHistory();
  const status=$("#discoverStatus");
  const stats=run.stats||{},running=run.status==="running";
  const counts=stats.checked?`已检查 ${stats.checked} 个网页，找到 ${run.items.length} 个已核验岗位。`:"";
  status.textContent=run.status==="failed"?run.error:run.status==="done"?`找到 ${run.items.length} 个已核验岗位，${run.rejected.length} 个链接未通过核验。`:(discoveryStages[run.stage]||"正在搜索")+"… "+counts;
  $("#discoverStages").innerHTML=["searching","verifying","scoring"].map(stage=>`<li class="${run.stage===stage?'is-current':run.status==='done'?'is-done':''}">${discoveryStages[stage]}</li>`).join("");
  const root=$("#discoverResults");root.setAttribute("aria-busy",String(run.status==="running"));
  if(running&&!run.items.length){root.innerHTML='<div class="discovery-empty"><p>正在从多个招聘来源搜索并核验页面。结果不足时会继续补搜，通过核验的岗位将逐步显示。</p></div>';return}
  if(run.status==="failed"&&!run.items.length){root.innerHTML='<div class="discovery-empty"><h2>这次搜索未能完成</h2><p>此页已保留，可翻阅之前的结果或重新搜索，新搜索会另存一页。</p></div>';return}
  const time=new Date(run.created_at).toLocaleString("zh-CN");
  const selectedFilters=Object.values(run.filters||{}).filter(Boolean).join(" · ")||"未限定城市与招聘类型";
  const searchNote=(running?'正在补充更多岗位，完成后可点击分析。':run.status==='failed'?'搜索中断，已保留此前核验通过的岗位。':stats.stop_reason==='target_reached'?`已达到本次展示上限 ${stats.result_limit} 个岗位。`:'')+(stats.previous_jobs?` 已排除 ${stats.history_excluded||0} 个历史重复结果。`:'');
  root.innerHTML=`<div class="discovery-list-heading"><div><h2>匹配岗位 <span>${run.items.length}</span></h2><p>${esc(time)} · ${esc(selectedFilters)}</p>${stats.checked?`<p>检查 ${esc(stats.checked)} 个网页 · 合并 ${esc(stats.duplicates||0)} 个重复结果</p>`:''}${searchNote?`<p>${esc(searchNote)}</p>`:''}</div><span>快速匹配分 ↓</span></div>`+
    (run.items.length?run.items.map(job=>`<article class="discovery-job"><div class="discovery-job-main"><div class="discovery-company">${esc(job.company)}</div><h3><button class="discovery-title" data-discover-analyze="${esc(job.id)}">${esc(job.title)}</button></h3><dl class="discovery-meta">${[["城市",job.city],["招聘类型",job.recruitment_type],["毕业届次",job.graduate_cohort],["职位类别",job.category]].map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl><p class="discovery-evidence">${esc(job.open_evidence)}</p><p class="discovery-source"><a href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">查看招聘原页 · ${esc(job.source_host)}</a><span>核验于 ${esc(new Date(job.checked_at).toLocaleString('zh-CN'))}</span></p>${job.gate_warnings?.length?`<p class="discovery-warning">${esc(job.gate_warnings.join("；"))}</p>`:''}<details class="discovery-basis"><summary>快速评分依据</summary><p>${esc(job.score_basis.formula)}</p><p>技能 ${job.score_basis.skill_points}/70 · 方向 ${job.score_basis.role_points}/30</p><p>匹配：${esc(job.matched_tags.join("、")||"暂无")}</p><p>未具备：${esc(job.missing_tags.join("、")||"暂无已识别缺口")}</p><p>仅识别固定标签与部分门槛，其余要求需在长报告中审阅。</p></details></div><div class="discovery-job-action"><div class="discovery-score">${job.score}<small>/100</small></div><span>快速匹配分</span><button class="btn primary" data-discover-analyze="${esc(job.id)}">分析此岗位</button></div></article>`).join(""):`<div class="discovery-empty"><h2>${stats.previous_jobs?'本次没有找到更多新的在招岗位':'本次没有可确认在招的岗位'}</h2><p>${stats.previous_jobs?'已过滤这份简历之前匹配过的岗位。可翻阅历史页，或调整条件后再搜索；旧岗位不会重新填入本页。':'部分招聘网站需要登录、验证码或脚本加载。可放宽城市、招聘类型后重试；系统不会用搜索摘要补成可靠岗位。'}</p></div>`)+
    (run.rejected.length?`<details class="discovery-rejected"><summary>${run.rejected.length} 个链接未进入结果 · 查看原因</summary>${run.rejected.map(item=>`<p>${esc(item.reason)}<br><span>${esc(item.url)}</span></p>`).join("")}</details>`:'');
  if(discoveryHistory.length>1){const index=discoveryHistory.findIndex(item=>item.id===run.id);root.innerHTML+=`<nav class="discovery-page-footer" aria-label="结果列表翻页"><button class="btn" data-discover-step="-1" ${index<=0?'disabled':''}>上一页</button><span>第 ${index+1} / ${discoveryHistory.length} 页</span><button class="btn" data-discover-step="1" ${index>=discoveryHistory.length-1?'disabled':''}>下一页</button></nav>`}
  if(discoveryAnalyzing)lockDiscoveryAnalysis(true);
  if(running)root.querySelectorAll("[data-discover-analyze]").forEach(button=>button.disabled=true);
}
function lockDiscoveryAnalysis(locked){
  discoveryAnalyzing=locked;
  const root=$("#discoverResults");
  root.setAttribute("aria-busy",String(locked));
  root.querySelectorAll("[data-discover-analyze]").forEach(control=>control.disabled=locked);
  if(locked)$("#discoverStatus").textContent=`正在分析「${discoveryActiveTitle}」：重新核验与报告生成中…`;
  discoveryLock(discoveryBusy);
}
async function analyzeDiscovered(button){
  if(discoveryAnalyzing||discoveryViewLoading||analysisFlowBusy||!discoveryRun||discoveryRun.status==='running')return;
  const sourceRun=discoveryRun,job=sourceRun.items.find(item=>item.id===button.dataset.discoverAnalyze);
  if(!job)return;
  discoveryActiveTitle=job.title;
  // Keep the optional import panel on this job while its latest JD is fetched.
  $("#jdText").value="";$("#jobTitle").value=job.title||"";$("#company").value=job.company||"";$("#location").value=job.city==="未注明"?"":job.city||"";$("#jdUrl").value=job.url||"";$("#matchResume").value=sourceRun.resume_id;
  $("#employment").value="未知";
  lockDiscoveryAnalysis(true);let returned=false;
  const version=beginAnalysisResult({title:job.title,company:job.company,message:"正在重新核验招聘原页、读取 JD 并生成匹配结论…"});
  try{
    const run=await api(`/api/discovery/runs/${encodeURIComponent(sourceRun.id)}/items/${encodeURIComponent(job.id)}/analyze`,{method:"POST"});
    if(!analysisIsCurrent(version))return;
    analysis={match:run,discovery:run.discovery,jdProfile:run.jd_profile||{},research:null};
    $("#jdText").value=run.jd_text;$("#jobTitle").value=run.title||"";$("#company").value=run.company||"";$("#location").value=run.location||"";$("#jdUrl").value=run.source_url||"";$("#matchResume").value=run.resume_id;
    renderAnalysis(run,analysis.research,analysis.jdProfile);
    $("#analysisProgress").textContent=`已从招聘原页读取 JD。列表快速分 ${run.discovery.quick_score}；长报告会细化判断。`;
    await Promise.all([pollMatch(run.match_id,version),loadCompanyBackground(run,version,job.company)]);
    returned=analysisIsCurrent(version);
  }catch(error){
    showAnalysisError(error,version,{fromDiscovery:true});
    $("#discoverStatus").textContent=error.message;toast(error.message);
  }finally{
    finishAnalysisFlow(version);lockDiscoveryAnalysis(false);
    if(returned)$("#discoverStatus").textContent=analysis?.match?.report_status==="done"?`「${discoveryActiveTitle}」分析完成，可在「分析岗位」查看报告。`:"核心结论已返回，请在「分析岗位」查看详细报告状态。";
  }
}
