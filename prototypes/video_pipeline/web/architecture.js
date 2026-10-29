const $=id=>document.getElementById(id);
const names=Object.fromEntries(Array.from({length:5},(_,i)=>[`cam-0${i+1}`,`Camera 0${i+1}`]));
const fixed=value=>Number.isFinite(value)?value.toFixed(1):'—';
let current=null,notify=()=>{},onLayout=()=>{},linkEdited=false;
async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Request failed');return result;}
function receivedList(order,count){if(!order.length)return 'Waiting for the C2 backend';const rows=[];for(let i=0;i<=order.length;i++){if(i===count)rows.push(`<div class="received-divider">${count<order.length?'OMITTED BELOW':'NO OMITTED FEEDS'}</div>`);if(i===order.length)break;const omitted=i>=count;rows.push(`<div class="received-row ${omitted?'omitted':''}"><span>${omitted?'—':i+1}</span><span>${names[order[i]]??'Unknown camera'}</span><small>${omitted?'OMITTED':'ENABLED'}</small></div>`);}return rows.join('');}
export function initArchitecture(toast,layout){notify=toast;onLayout=layout;
  $('bandwidth').oninput=()=>{linkEdited=true;$('bandwidth-slider').value=Math.min(100,Number($('bandwidth').value)||0);};
  $('bandwidth-slider').oninput=()=>{linkEdited=true;$('bandwidth').value=$('bandwidth-slider').value;};
  $('latency').oninput=()=>{linkEdited=true;};
  $('apply-link').onclick=applyLink;
  document.querySelectorAll('[data-bandwidth]').forEach(button=>button.onclick=()=>{$('bandwidth').value=button.dataset.bandwidth;$('bandwidth-slider').value=button.dataset.bandwidth;linkEdited=true;applyLink();});
  $('toggle-output').onclick=()=>{const opening=$('manager-json').hidden;$('manager-json').hidden=!opening;$('toggle-output').setAttribute('aria-expanded',String(opening));$('toggle-output').textContent=opening?'Hide output contract':'Inspect output contract';if(current)$('manager-json').textContent=JSON.stringify(current.status_manager,null,2);onLayout('status-node');};
}
async function applyLink(){const mbps=Number($('bandwidth').value),latency=Number($('latency').value);if(!Number.isFinite(mbps)||mbps<0||mbps>1000||!Number.isFinite(latency)||latency<0||latency>2000){notify('Use 0–1000 Mb/s and 0–2000 ms one-way delay');return;}$('apply-link').disabled=true;try{const response=await post('/api/link',{bandwidth_bps:Math.round(mbps*1_000_000),latency_ms:latency});linkEdited=false;renderArchitecture(response);}catch(error){notify(error.message);}finally{$('apply-link').disabled=false;}}
export function renderArchitecture(architecture){if(!architecture)return;current=architecture;const{c2,link,status_manager:s,process:p}=current;
  $('actual-c2-process').textContent=c2.publisher_pid?`Python backend PID ${c2.publisher_pid}`:'Waiting for actual publisher';
  $('actual-c2-status').textContent=c2.connected?'LIVE':'OFFLINE';$('c2-node').classList.toggle('offline',!c2.connected);
  const endpoint=address=>address?`${address[0]}:${address[1]}`:'waiting';
  $('actual-c2-endpoints').textContent=`Publisher: ${endpoint(c2.publisher_address)}\nLab ingress: ${endpoint(c2.ingress_address)}\nSession: ${c2.session?.slice(0,12)??'—'} · packet #${c2.sequence??'—'}\nLast packet: ${fixed(c2.backend_age_s)} s ago`;
  $('actual-c2-revision').textContent=c2.revision===null?'Waiting':`r${c2.revision} · ${c2.enabled_count} enabled`;
  $('external-c2-list').innerHTML=receivedList(c2.ordered_stream_ids,c2.enabled_count);
  $('c2-revision').textContent=c2.revision===null?'—':`r${c2.revision}`;$('ack-revision').textContent=c2.ack_revision===null?'—':`r${c2.ack_revision}`;$('c2-rtt').textContent=c2.rtt_ms===null?'—':`${fixed(c2.rtt_ms)} ms`;
  const acknowledged=c2.ack_revision===c2.revision&&c2.ack_age_s!==null&&c2.ack_age_s<3;
  $('c2-delivery').textContent=!c2.connected?'C2 backend offline · no generated replacement priorities':!link.link_up?'Link down · backend publications cannot reach the rover':acknowledged?`Rover acknowledged revision ${c2.ack_revision}`:`Waiting for rover acknowledgment of revision ${c2.revision}`;
  $('c2-delivery').classList.toggle('pending',!acknowledged||!link.link_up||!c2.connected);
  $('link-up').textContent=link.link_up?'UP':'DOWN';$('link-node').classList.toggle('offline',!link.link_up);$('wire-c2-link').classList.toggle('offline',!link.link_up||!c2.connected);$('wire-link-status').classList.toggle('offline',!link.link_up||s.priorities_stale);
  $('link-process').textContent=`Lab PID ${p.pid} · real UDP shaper`;$('manager-process').textContent=`Lab PID ${p.pid} · Python StatusManager`;
  if(!linkEdited){$('bandwidth').value=link.bandwidth_bps/1_000_000;$('bandwidth-slider').value=Math.min(100,link.bandwidth_bps/1_000_000);$('latency').value=link.latency_ms;}
  $('up-packets').textContent=`${link.c2_to_rover.sent_packets} delivered`;$('down-packets').textContent=`${link.rover_to_c2.sent_packets} delivered`;$('queue-drops').textContent=`${link.c2_to_rover.queued_packets+link.rover_to_c2.queued_packets} / ${link.c2_to_rover.dropped_packets+link.rover_to_c2.dropped_packets}`;
  $('manager-ready').textContent=!s.inputs_ready?'WAITING':s.priorities_stale||s.bandwidth_stale?'STALE INPUT':'READY';
  $('priority-freshness').textContent=!s.priorities_received?'Waiting':`${s.priorities_stale?'Stale':'Fresh'} · ${fixed(s.priority_age_s)} s`;$('priority-freshness').parentElement.classList.toggle('stale',s.priorities_stale);
  $('bandwidth-freshness').textContent=!s.bandwidth_received?'Waiting':s.bandwidth_stale?'Stale':'Local simulated input';$('bandwidth-freshness').parentElement.classList.toggle('stale',s.bandwidth_stale);
  $('manager-bandwidth').textContent=s.available_bandwidth_bps===null?'—':`${(s.available_bandwidth_bps/1_000_000).toLocaleString(undefined,{maximumFractionDigits:3})} Mb/s`;$('received-revision').textContent=s.priority_revision===null?'—':`C2 revision ${s.priority_revision}`;
  $('received-list').innerHTML=receivedList(s.ordered_stream_ids,s.enabled_count);
  $('output-sequence').textContent=`#${s.output_sequence}`;if(!$('manager-json').hidden)$('manager-json').textContent=JSON.stringify(s,null,2);
}
