import {pilot} from '../api/pilot.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt} from '../utils/format.js';
import {download} from '../utils/download.js';

export async function render(id){
  if(!id)return `<h1>单城试投增量结果</h1><p>请从单城试投页选择一个核算记录。</p>`;
  const r=await pilot.getRun(id);
  const result=r.result;
  const stale=r.superseded
    ||(r.status==='completed'&&!r.is_current)
    ||(['queued','running'].includes(r.status)&&r.input_revision<r.current_revision);
  const currentNote=r.is_current
    ?'<span class="status completed">当前有效结论</span>'
    :(stale?'<span class="status superseded">非当前结论</span>':'<span class="status queued">尚未成为当前结论</span>');
  const banner=stale
    ?`<div class="error">此结果基于版本 ${r.input_revision} 的快照，当前计划已更新到版本 ${r.current_revision}（或计算期间发生更正）。${esc(r.superseded_reason||'')}不得作为当前结论发布；历史结果仍保留可查。</div>`:'';
  const history=stale&&result?`<p class="method-note">以下为历史归档内容，仅供追溯，请勿据此发布当前结论。</p>`:'';
  const body=result?`
  <section class="result-intro"><strong>${esc(result.interpretation)}</strong><p>${esc(result.caveat)}</p></section>
  ${result.warnings?.length?`<div class="method-note"><strong>区间来源与失效</strong><ul>${result.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}
  <h2>核心数值</h2>${table(['业务指标','计算值'],Object.entries(result.metrics).map(([k,v])=>[k,fmt(v)]))}
  <h2>每日增量范围 <small>${esc(result.post_start)} 至 ${esc(result.post_end)} · 增量单位：百分点</small></h2>
  ${table(result.columns,result.rows)}
  <h2>受影响城市 <small>缺报或串投失效，权重按 0–1 端点计入，不重配</small></h2>
  ${table(['城市','原因','首日','末日','天数','封存权重'],result.affected_cities.map(a=>[a.city,a.reasons,a.first_date,a.last_date,a.days,fmt(a.sealed_weight)]))}
  <h2>本次使用的封存权重</h2>${table(['对照城市','权重'],result.seal_weights.map(w=>[w.city,fmt(w.weight)]))}
  <div class="toolbar"><button id="pilot-export">下载核算 CSV</button><a class="button secondary" href="#pilot/${r.plan_id}">返回试投计划 →</a></div>`:'<p class="method-note">任务正在队列中或尚未完成，此页每2秒刷新。</p>';
  return `<div class="eyebrow">06 / PILOT RESULT · RUN ${r.id}</div><h1>${esc(r.name)} ${status(r.status)} ${currentNote}</h1>
  <div class="checksum">INPUT SHA256 ${esc(r.checksum)}</div>
  <p>计划 #${r.plan_id} · 输入版本 ${r.input_revision} · 当前计划版本 ${r.current_revision} · 提交 ${esc(r.created_at)}${r.completed_at?' · 完成 '+esc(r.completed_at):''}</p>
  ${banner}${history}
  ${r.status==='failed'?`<div class="error">核算失败：${esc(r.error)}</div>`:body}`;
}

export function bind(){
  const button=document.getElementById('pilot-export');
  if(button)button.onclick=async()=>{
    const id=Number(location.hash.split('/')[1]);
    try{download(await pilot.exportRun(id),'pilot-'+id+'.csv');}catch(e){document.getElementById('notice').textContent=e.message;}
  };
}
