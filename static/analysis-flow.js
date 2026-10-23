/* Stable result destination: navigate before waiting for any network response. */
let analysisFlowVersion=0, analysisFlowBusy=false;

function setJdImportOpen(open){
  const panel=$("#jdImportPanel"),button=$("#toggleJdImport");
  panel.hidden=!open;
  button.setAttribute("aria-expanded",String(open));
  button.querySelector("span").textContent=open?"收起岗位导入":"导入一个岗位";
}

function wireAnalysisFlow(){
  $("#toggleJdImport").onclick=()=>setJdImportOpen($("#jdImportPanel").hidden);
}

function lockAnalysisInputs(locked){
  analysisFlowBusy=locked;
  $("#jdImportPanel").querySelectorAll("input,textarea,select,button").forEach(control=>{
    if(locked){control.dataset.analysisWasDisabled=String(control.disabled);control.disabled=true}
    else if(control.dataset.analysisWasDisabled!==undefined){control.disabled=control.dataset.analysisWasDisabled==="true";delete control.dataset.analysisWasDisabled}
  });
}

function focusAnalysisResult(){
  $("#analysisOutcome").focus({preventScroll:true});
  $("#analysisOutcome").scrollIntoView({block:"start",behavior:"instant"});
}

function beginAnalysisResult({title="岗位分析",company="",message="正在读取岗位并生成匹配结论…"}={}){
  const version=++analysisFlowVersion;
  lockAnalysisInputs(true);
  analysis=null;
  $("#analysisProgress").textContent=message;
  $("#analysisResult").setAttribute("aria-busy","true");
  $("#analysisResult").innerHTML=`<article class="card analysis-pending"><h2>${esc(title)}</h2>${company?`<p class="sub">${esc(company)}</p>`:""}<p>分析已开始，结果会直接显示在这里。</p><ol><li>核对岗位原文与简历依据</li><li>生成匹配结论</li><li>补充详细报告</li></ol><p class="sub">无需再次导入岗位。等待期间也可以通过上方按钮查看岗位信息。</p></article>`;
  go("analyze");
  setJdImportOpen(false);
  focusAnalysisResult();
  return version;
}

function analysisIsCurrent(version){return version===analysisFlowVersion}

function finishAnalysisFlow(version){
  if(!analysisIsCurrent(version))return;
  lockAnalysisInputs(false);
  $("#analysisResult").setAttribute("aria-busy","false");
}

function showAnalysisError(error,version,{fromDiscovery=false}={}){
  if(!analysisIsCurrent(version))return;
  $("#analysisProgress").textContent="本次分析未完成";
  $("#analysisResult").innerHTML=`<article class="card analysis-error" role="alert"><h2>暂时无法完成岗位分析</h2><p>${esc(error.message||"连接中断，请重试。")}</p><button type="button" class="btn" id="analysisRecover">${fromDiscovery?"返回匹配岗位":"展开岗位导入"}</button></article>`;
  $("#analysisRecover").onclick=()=>fromDiscovery?go("discover"):setJdImportOpen(true);
}

function openExistingAnalysis(){
  ++analysisFlowVersion;
  lockAnalysisInputs(false);
  $("#analysisResult").setAttribute("aria-busy","false");
  setJdImportOpen(false);
}
