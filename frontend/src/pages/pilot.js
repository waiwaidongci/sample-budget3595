import {pilotStore,loadPlans,loadDetail,writable} from '../stores/pilot.js';
import {pilot} from '../api/pilot.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {bindForm} from '../hooks/forms.js';
import {esc,fmt} from '../utils/format.js';

function planOptions(){
  return `<label>试投计划<select id="pilot-select">${pilotStore.plans.map(p=>`<option value="${p.id}" ${p.id===pilotStore.planId?'selected':''}>#${p.id} ${esc(p.name)} · ${esc(p.treated_city)} · ${p.sealed?'已封存':'未封存'}</option>`).join('')}</select></label>`;
}

function sealBlock(d){
  if(!d.sealed){
    return `<div class="method-note"><strong>尚未封存对照权重</strong><p>封存前只接收投放首日（${esc(d.launch_date)}）之前的逐城日报。封存时只用投放前数据拟合非负且总和为 1 的权重，之后不再重配。</p></div>`;
  }
  const s=d.seal;
  return `<div class="method-note"><strong>对照权重已封存</strong><p>投放前窗口 ${esc(s.pre_start)} 至 ${esc(s.pre_end)} · 拟合 ${s.pre_dates.length} 天 · SHA256 <span class="checksum">${esc(s.input_sha256)}</span></p><small>${esc(s.created_by)} · ${esc(s.created_at)}</small></div>
  <h2>封存权重 <small>非负、总和为 1，投放后不再重配</small></h2>
  ${table(['对照城市','封存权重'],Object.entries(s.weights).map(([c,w])=>[c,fmt(w)]))}
  <p class="method-note">拟合边界：${esc(Object.entries(s.metrics).map(([k,v])=>k+' '+(typeof v==='number'?fmt(v):v)).join(' · '))}</p>`;
}

function dailyBlock(d){
  const canWrite=writable();
  const sealed=d.sealed;
  const allowed=sealed?[...Object.keys(d.seal.weights),d.treated_city]:null;
  const defaultDate=sealed
    ? esc(d.post_days.slice(-1)[0]||d.launch_date)
    : esc(d.pre_days.slice(-1)[0]||'2026-11-01');
  return `${canWrite?`<h2>录入逐城日报 <small>${sealed?'投放后数据：城市须在封存权重内':'仅投放前数据，日期须早于 '+esc(d.launch_date)}</small></h2>
  <form id="daily-form" class="inline-form">
    <label>城市<input name="city" required maxlength="60" ${sealed?`list="sealed-cities"`:''}></label>
    ${sealed?`<datalist id="sealed-cities">${allowed.map(c=>`<option value="${esc(c)}"></option>`).join('')}</datalist>`:''}
    <label>日期<input name="date" type="date" required value="${defaultDate}"></label>
    <label>触达数<input name="impressions" type="number" min="1" step="1" required></label>
    <label>点击数<input name="clicks" type="number" min="0" step="1" required></label>
    <button type="submit">保存日报</button>
  </form>`:''}
  <details><summary>逐城日报明细（${d.daily.length} 条）</summary>${table(['城市','日期','触达','点击','阶段',...(canWrite?['操作']:[])],d.daily.map(r=>[r.city,r.date,fmt(r.impressions),fmt(r.clicks),r.date<d.launch_date?'投放前':'投放后',...(canWrite?[{html:`<button class="text" data-daily-del="${r.id}">移除</button>`}]:[])]))}</details>`;
}

function sealControls(d){
  if(!writable())return '';
  if(!d.sealed){
    return `<h2>封存对照权重</h2><p>封存后投放前数据锁定，权重不可重新拟合。请确认投放前逐城日报已补齐。</p><form id="seal-form"><button type="submit">用投放前数据拟合并封存权重 →</button></form>`;
  }
  return `<h2>迟到串投登记</h2><p>某对照城市事后被发现也已开始投放时，登记其实际开始日。该城自此日起的投放后数据全部失效，其封存权重按 0–1 端点计入区间，不转给其他城市。</p>
  ${d.spillovers.length?table(['城市','实际开始日','说明'],d.spillovers.map(s=>[s.city,s.actual_start_date,s.note||'—'])):''}
  <form id="spill-form" class="inline-form"><label>城市<input name="city" required maxlength="60"></label><label>实际开始日<input name="actual_start_date" type="date" required></label><label>说明<input name="note" maxlength="2000"></label><button type="submit">登记串投</button></form>
  <h2>提交增量核算</h2><p>快照当前版本（计划版本 ${d.revision}）与全部观测，后台计算每日增量范围。</p><form id="pilot-run-form" class="inline-form"><label>本次核算名称<input name="name" required minlength="2" maxlength="120" value="单城增量核算 · 版本${d.revision}"></label><button type="submit">冻结并排队核算 →</button></form>`;
}

function runBlock(d){
  if(!d.runs.length)return '<h2>核算记录</h2><p class="method-note">尚无核算记录。</p>';
  return `<h2>核算记录 <small>历史结论保留可查；旧版本结果不得作为当前结论</small></h2>
  ${table(['编号 / 运行','状态','输入版本','当前计划版本','提交','结论'],d.runs.map(r=>[
    {html:`<a href="#pilotresult/${r.id}">#${r.id} ${esc(r.name)}</a>`},
    {html:status(r.status)},
    r.input_revision,
    r.current_revision,
    esc(r.created_at),
    r.is_current?'当前有效结论':(r.superseded?esc(r.superseded_reason||'基于旧版本，不得作为当前结论'):'非当前版本'),
  ]))}`;
}

export async function render(id){
  await loadPlans();
  if(id)pilotStore.planId=+id;
  const d=await loadDetail(pilotStore.planId);
  const createForm=writable()?`<details><summary>新建试投计划</summary><form id="pilot-plan-form" class="inline-form"><label>名称<input name="name" required minlength="2" maxlength="120"></label><label>试验城<input name="treated_city" required maxlength="60"></label><label>投放首日<input name="launch_date" type="date" required></label><label>说明<input name="description" maxlength="2000"></label><button type="submit">保存计划</button></form></details>`:'';
  if(!d)return `<div class="eyebrow">06 / SINGLE-CITY PILOT</div><h1>单城试投增量</h1><p class="lead">没有随机对照的城市试投，用其他城市投放前数据拟合对照权重，封存后再估算投放后的点击率增量。</p>${createForm}<p class="method-note">尚无试投计划。</p>`;
  return `<div class="eyebrow">06 / SINGLE-CITY PILOT · PLAN ${d.id}</div><h1>${esc(d.name)} ${d.sealed?'<span class="status completed">已封存</span>':'<span class="status queued">未封存</span>'}</h1>
  <p>试验城 <strong>${esc(d.treated_city)}</strong> · 投放首日 ${esc(d.launch_date)} · 当前计划版本 ${d.revision}。${esc(d.description||'')}</p>
  <div class="toolbar">${planOptions()}</div>
  ${createForm}
  ${sealBlock(d)}
  ${dailyBlock(d)}
  ${sealControls(d)}
  ${runBlock(d)}`;
}

export function bind(refresh){
  const sel=document.getElementById('pilot-select');
  if(sel)sel.onchange=async()=>{pilotStore.planId=+sel.value;location.hash='pilot/'+sel.value;};
  bindForm('pilot-plan-form',async data=>{const p=await pilot.createPlan(data);pilotStore.planId=p.id;location.hash='pilot/'+p.id;});
  bindForm('daily-form',async data=>{await pilot.daily(pilotStore.planId,{city:data.city,date:data.date,impressions:+data.impressions,clicks:+data.clicks});refresh();});
  bindForm('seal-form',async()=>{await pilot.seal(pilotStore.planId);refresh();});
  bindForm('spill-form',async data=>{await pilot.spillover(pilotStore.planId,data);refresh();});
  bindForm('pilot-run-form',async data=>{const r=await pilot.run(pilotStore.planId,{name:data.name});location.hash='pilotresult/'+r.id;});
  document.querySelectorAll('[data-daily-del]').forEach(el=>el.onclick=async()=>{try{await pilot.removeDaily(pilotStore.planId,+el.dataset.dailyDel);refresh();}catch(e){document.getElementById('notice').textContent=e.message;}});
}
