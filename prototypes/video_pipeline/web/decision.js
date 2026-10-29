const $=id=>document.getElementById(id);
const mbps=value=>Number.isFinite(value)?`${(value/1e6).toLocaleString(undefined,{maximumFractionDigits:3})} Mb/s`:'—';
let edited=false,current=null;
export function initDecision(toast,layout){
  $('video-share').oninput=()=>edited=true;
  $('apply-video-share').onclick=async()=>{const button=$('apply-video-share');button.disabled=true;try{const value=Number($('video-share').value);if($('video-share').value.trim()===''||!Number.isFinite(value)||value<0||value>100)throw new Error('Use a video share from 0 to 100%');const response=await fetch('/api/encoding-decision/config',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({video_share_percent:value})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Cannot update allocation');edited=false;renderDecision(result);toast(`Video share set to ${value}%`);}catch(error){toast(error.message);}finally{button.disabled=false;}};
  $('toggle-plan').onclick=()=>{const opening=$('decision-json').hidden;$('decision-json').hidden=!opening;$('toggle-plan').setAttribute('aria-expanded',String(opening));$('toggle-plan').textContent=opening?'Hide plan contract':'Inspect plan contract';if(current)$('decision-json').textContent=JSON.stringify(current,null,2);layout('decision-node');};
}
export function renderDecision(plan){if(!plan)return;current=plan;const b=plan.budget,h=plan.hardware;
  if(!edited)$('video-share').value=plan.configuration.video_share_percent;
  $('plan-consumer').textContent=plan.encoder_connected?'REQUESTED PLAN → ENCODER ENABLED · ACTUAL RESULTS BELOW':'REQUESTED PLAN → ENCODER DISABLED';
  $('decision-process').textContent=`Lab PID ${plan.process_pid} · Python EncodingDecision`;
  $('decision-state').textContent=!plan.runtime_healthy?'PLANNER OFFLINE':plan.state==='no_video'?'NO VIDEO PLAN':plan.state==='waiting_inputs'?'WAITING':plan.state==='holding_upgrade'?'UPGRADE HOLD':plan.state==='degraded'?'STALE C2 ORDER':'PLAN READY';
  $('decision-budget').textContent=mbps(b.encoder_budget_bps);
  $('budget-formula').textContent=`${mbps(b.available_bandwidth_bps)} × ${plan.configuration.video_share_percent}% video × ${100-plan.configuration.headroom_percent}% after headroom`;
  $('planned-bitrate').textContent=mbps(b.planned_bitrate_bps);$('unused-budget').textContent=mbps(b.unallocated_bps);
  $('pixel-load').textContent=`${(h.planned_pixels_per_second/1e6).toFixed(1)} / ${(h.max_pixels_per_second/1e6).toFixed(1)} MP/s`;
  $('session-load').textContent=`${h.planned_streams} / ${h.max_streams} planned`;
  $('decision-revision').textContent=`Plan r${plan.plan_revision}`;
  $('decision-stability').textContent=plan.stability.upgrade_pending?`Upgrade hold: ${plan.stability.upgrade_remaining_s.toFixed(1)} s remaining · 25% spare capacity required`:plan.inputs.priorities_stale&&plan.inputs.priorities_received?'Last received C2 order is stale · automatic upgrades blocked':'Lower budgets apply promptly · automatic profile upgrades wait 4 s with 25% spare capacity';
  const list=$('camera-decisions');
  // All content comes from the local typed contract; textContent avoids HTML interpolation.
  for(const item of plan.cameras){let row=list.querySelector(`[data-camera="${item.id}"]`);if(!row){row=document.createElement('div');row.className='camera-decision';row.dataset.camera=item.id;for(const cls of ['decision-camera','decision-rate','decision-size','decision-fps','decision-reason']){const field=document.createElement('span');field.className=cls;row.append(field);}list.append(row);}row.classList.toggle('withheld',!item.selected);row.querySelector('.decision-camera').textContent=`${item.priority??'—'} · ${item.name}`;row.querySelector('.decision-rate').textContent=item.selected?mbps(item.target_bitrate_bps):'0 Mb/s';row.querySelector('.decision-size').textContent=item.selected?`${item.width} × ${item.height}`:'—';row.querySelector('.decision-fps').textContent=item.selected?`${item.fps} fps`:'—';row.querySelector('.decision-reason').textContent=item.reason;list.append(row);}
  $('wire-status-decision').classList.toggle('offline',plan.state==='waiting_inputs');
  if(!$('decision-json').hidden)$('decision-json').textContent=JSON.stringify(plan,null,2);
}
