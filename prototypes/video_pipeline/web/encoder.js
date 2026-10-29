const $=id=>document.getElementById(id);
const ids=Array.from({length:5},(_,i)=>`cam-0${i+1}`);
const rate=value=>Number.isFinite(value)?`${(value/1e6).toFixed(3)} Mb/s`:'—';
const ms=value=>Number.isFinite(value)?`${value.toFixed(1)} ms`:'—';
const client=crypto.randomUUID();
let current=null,expanded=false,active=!document.hidden,busy=false;
const inFlight=new Set(),last=new Map();
function clear(id){const img=$(`encoded-image-${id}`);img.removeAttribute('src');if(img.dataset.url){URL.revokeObjectURL(img.dataset.url);delete img.dataset.url;}last.delete(id);}
function monitorVisible(){return expanded&&active&&getComputedStyle($('encoder-node')).visibility!=='hidden';}
async function lease(){try{await fetch(`/api/encoder/previews/${client}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({visible:monitorVisible()}),keepalive:true});}catch{}}
export function initEncoder(toast,layout){
  for(const id of ids){const row=document.createElement('div');row.className='encoder-camera';row.id=`encoder-${id}`;
    for(const cls of ['encoder-camera-title','encoder-camera-request','encoder-camera-actual','encoder-camera-timing','encoder-camera-status']){const span=document.createElement('span');span.className=cls;row.append(span);}
    const download=document.createElement('a');download.className='encoder-capture';download.href=`/api/encoder/capture/${id}`;download.textContent='Download recent H.264';download.setAttribute('download','');row.append(download);$('encoder-cameras').append(row);
    const article=document.createElement('article');article.className=`monitor ${id}`;article.innerHTML=`<div class="monitor-head">Camera ${id.slice(-2)}<span>DECODED OUTPUT</span></div><div class="monitor-view">WAITING FOR ENCODED VIDEO<img id="encoded-image-${id}" alt="Camera ${id.slice(-2)} decoded H.264 preview"></div><div class="monitor-foot"><span id="encoded-preview-${id}">Hidden / inactive</span><b>480 × 270</b></div>`;$('encoded-preview-grid').append(article);
  }
  $('toggle-encoder').onclick=async()=>{if(busy)return;busy=true;$('toggle-encoder').disabled=true;try{const response=await fetch('/api/encoder/enabled',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({enabled:!current?.enabled})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Encoder control failed');renderEncoder(result);toast(result.enabled?'Hardware encoder enabled':'Hardware sessions stopped');}catch(error){toast(error.message);}finally{busy=false;$('toggle-encoder').disabled=false;}};
  $('toggle-encoded-previews').onclick=()=>{expanded=!expanded;$('encoded-previews').hidden=!expanded;$('toggle-encoded-previews').textContent=expanded?'Hide encoded previews':'Show encoded previews';$('toggle-encoded-previews').setAttribute('aria-expanded',String(expanded));if(!expanded)ids.forEach(clear);lease();layout();};
  $('toggle-encoder-output').onclick=()=>{const opening=$('encoder-json').hidden;$('encoder-json').hidden=!opening;$('toggle-encoder-output').textContent=opening?'Hide encoder state':'Inspect encoder state';$('toggle-encoder-output').setAttribute('aria-expanded',String(opening));if(current)$('encoder-json').textContent=JSON.stringify(current,null,2);layout();};
  document.addEventListener('visibilitychange',()=>{active=!document.hidden;if(!active)ids.forEach(clear);lease();});
  addEventListener('pagehide',()=>{active=false;lease();});
  document.addEventListener('lab-view-change',()=>{if(!monitorVisible())ids.forEach(clear);lease();});setInterval(lease,1500);
  setInterval(()=>{if(monitorVisible()&&current?.enabled)for(const camera of current.cameras)if(camera.state==='encoding'&&camera.preview_count)image(camera);},167);
}
async function image(camera){const id=camera.id,key=`${camera.session}:${camera.preview_count}`;if(inFlight.has(id)||last.get(id)===key)return;inFlight.add(id);try{const response=await fetch(`/api/encoder/preview/${id}.jpg?frame=${key}`);if(!response.ok)return;const blob=await response.blob();if(!monitorVisible())return;const img=$(`encoded-image-${id}`),old=img.dataset.url,url=URL.createObjectURL(blob);img.src=url;img.dataset.url=url;if(old)URL.revokeObjectURL(old);last.set(id,key);}catch{}finally{inFlight.delete(id);}}
export function renderEncoder(state){if(!state)return;current=state;
  $('encoder-process').textContent=`Lab PID ${state.process_pid} · native workers per active camera`;
  $('encoder-status').textContent=state.error?'ERROR':!state.enabled?'OFF':state.active_sessions?'ENCODING':'WAITING FOR PLAN';
  $('toggle-encoder').textContent=state.enabled?'Disable encoding':'Enable encoding';
  $('encoder-backend').textContent=state.backend;
  $('encoder-version').textContent=state.gstreamer_version??'Native runtime checked when enabled';
  $('encoder-total-rate').textContent=rate(state.cameras.reduce((n,c)=>n+(c.actual_bitrate_bps??0),0));
  $('encoder-session-count').textContent=`${state.active_sessions} / 5 active`;
  $('encoder-error').textContent=state.error??`H.264 / NV12 · requested CBR · hardware required · ${state.transmission_connected?'TCP consumer connected':'TCP consumer idle'}`;
  for(const camera of state.cameras){const row=$(`encoder-${camera.id}`),desired=camera.desired;
    row.querySelector('.encoder-camera-title').textContent=`${camera.name} · ${camera.state.toUpperCase()}${camera.process_pid?` · PID ${camera.process_pid}`:''}`;
    row.querySelector('.encoder-camera-request').textContent=desired?.selected?`REQUEST ${desired.width}×${desired.height} / ${desired.fps} fps · ${rate(desired.target_bitrate_bps)}`:'REQUEST — · no selected video profile';
    row.querySelector('.encoder-camera-actual').textContent=camera.state==='encoding'?`OUTPUT ${camera.observed_width}×${camera.observed_height} · ${(camera.actual_fps??0).toFixed(1)} fps · ${rate(camera.actual_bitrate_bps)} · HW confirmed`:'OUTPUT —';
    row.querySelector('.encoder-camera-timing').textContent=`Accepted target ${rate(camera.accepted_bitrate_bps)} · delay p50 ${ms(camera.submit_to_output_p50_ms)} / p95 ${ms(camera.submit_to_output_p95_ms)} · ${camera.output_frames??0} frames`;
    row.querySelector('.encoder-camera-status').textContent=camera.error??camera.preview_error??(camera.state==='encoding'?`Accepted plan r${camera.accepted_plan_revision??'—'} · ${camera.reconfiguration_count} format restarts · ${camera.skipped_source_frames??0} source frames skipped beyond intentional FPS selection`:desired?.reason??'Encoder disabled');
    const link=row.querySelector('.encoder-capture');link.hidden=camera.state!=='encoding';
    $(`encoded-preview-${camera.id}`).textContent=camera.state==='encoding'?`${camera.preview_decoder??'Decoder off'} · preview #${camera.preview_count??0}`:'Encoder inactive';
    if(camera.state!=='encoding')clear(camera.id);
  }
  $('wire-decision-encoder').classList.toggle('offline',!state.enabled);$('wire-cameras-encoder').classList.toggle('offline',!state.active_sessions);
  if(!$('encoder-json').hidden)$('encoder-json').textContent=JSON.stringify(state,null,2);
}
