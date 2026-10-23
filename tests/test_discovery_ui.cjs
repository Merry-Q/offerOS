const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/job-discovery.js', 'utf8');
const run = (id, status = 'done') => ({id, resume_id:'cv_a', status, stage:status, created_at:'2026-10-23T00:00:00Z', items:[], rejected:[], stats:{}, filters:{}});
function page(api) {
  const elements = new Map();
  const storage = new Map();
  const context = vm.createContext({
    api, selectedResume:{id:'cv_a'}, analysisFlowBusy:false, analysis:null,
    sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)},
    $:id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',setAttribute(){},querySelectorAll(){return []}});return elements.get(id)},
    esc:s=>String(s), toast(){}, setTimeout,
    beginAnalysisResult:()=>1,analysisIsCurrent:()=>true,renderAnalysis(){},finishAnalysisFlow(){},
    pollMatch:async()=>{},loadCompanyBackground:async()=>{},showAnalysisError:e=>{throw e},
  });
  vm.runInContext(source, context);
  return {context,elements,storage,eval:code=>vm.runInContext(code,context)};
}

test('polling a new search never replaces the historical page being viewed', async()=>{
  let polls=0, release;
  const p=page(async()=>run('new',++polls===1?'running':'done'));
  p.context.setTimeout=fn=>{release=fn};
  p.eval(`discoveryRun=${JSON.stringify(run('new','running'))};cacheDiscoveryRun(${JSON.stringify(run('old'))});cacheDiscoveryRun(discoveryRun)`);
  const polling=p.eval("pollDiscovery('new',discoveryEpoch)");
  await new Promise(setImmediate);
  await p.eval("viewDiscoveryPage('old')");
  release();await polling;
  assert.equal(p.eval('discoveryRun.id'),'old');
  assert.equal(p.eval("discoveryCache.get('new').status"),'done');
  assert.equal(p.storage.get('discoveryPage:cv_a'),'old');
  assert.equal(p.eval('discoveryBusy'),false);
});

test('analyzing a historical job works while another search is running',async()=>{
  let path;
  const p=page(async url=>{path=url;return {match_id:'match_old',jd_text:'公开 JD',discovery:{quick_score:80},resume_id:'cv_a'}});
  const old={...run('old'),items:[{id:'job_old',title:'产品经理',company:'公开公司',url:'https://jobs.test/old'}]};
  p.eval(`discoveryRun=${JSON.stringify(old)};cacheDiscoveryRun(discoveryRun);discoveryBusy=true;discoveryActiveRunId='new'`);
  await p.eval("analyzeDiscovered({dataset:{discoverAnalyze:'job_old'}})");
  assert.equal(path,'/api/discovery/runs/old/items/job_old/analyze');
  assert.equal(p.elements.get('#matchResume').value,'cv_a');
  assert.equal(p.eval('discoveryRun.id'),'old');
  assert.equal(p.eval('discoveryBusy'),true);
});

test('a late page response cannot replace a newer selection or another resume',async()=>{
  let release;
  const p=page(()=>new Promise(resolve=>{release=resolve}));
  p.eval(`cacheDiscoveryRun(${JSON.stringify(run('new'))})`);
  const older=p.eval("viewDiscoveryPage('old')");
  await p.eval("viewDiscoveryPage('new')");
  release(run('old'));await older;
  assert.equal(p.eval('discoveryRun.id'),'new');
  const stale=p.eval("viewDiscoveryPage('another')");
  p.eval("++discoveryEpoch;discoveryRun=null;selectedResume={id:'cv_b'}");
  release(run('another'));await stale;
  assert.equal(p.eval('discoveryRun'),null);
  assert.equal(p.storage.has('discoveryPage:cv_b'),false);
});

test('returning during report generation still restores the selected history page',async()=>{
  const p=page(async()=>run('old'));
  p.eval('discoveryAnalyzing=true');
  await p.eval("viewDiscoveryPage('old')");
  assert.equal(p.eval('discoveryRun.id'),'old');
  assert.equal(p.elements.get('#discoverPage').disabled,true);
  assert.equal(p.storage.get('discoveryPage:cv_a'),'old');
});
