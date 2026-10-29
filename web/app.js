import {readController} from './controller.mjs';
import {initPriorities,renderPriorities} from './priorities.mjs';
const $ = id => document.getElementById(id);
const fmt = (v, digits=2, suffix='') => Number.isFinite(v) ? `${v.toFixed(digits)}${suffix}` : '—';
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const text = (id, value) => { const el=$(id),next=String(value);if(el.textContent===next)return;const top=el.scrollTop,left=el.scrollLeft;el.textContent=next;el.scrollTop=top;el.scrollLeft=left; };
const pages = {
  drive: ['Drive & arm', 'Operator control, chassis feedback, and arm command preview.'],
  cameras: ['Cameras', 'Received Camera 01–05 video, feed priorities, and prototype snapshots.'],
  gps: ['Position & GPS', 'Validated fixes, local scatter, and reference comparisons.'],
  telemetry: ['Telemetry', 'Guarded output and receiver feedback, with bounded local logs.'],
  connections: ['Connections', 'Bring up the link, then exercise its failure behavior.'],
  development: ['Development', 'A portable architecture, with explicit hardware boundaries.'],
};
let ws, client, state, page='drive', seq=0, request=0, reconnect, noticeTimer;
let axes={throttle:0,steering:0,jog:0,deadman:false}, keys=new Set(), pointerHold=false, gamepadConnected=false;
let pointerStick=null, snapshotTime=0, lastStateAt=0;
const pending=new Map();

function notice(message, error=false) {
  if (!message) return;
  $('notice').textContent=message; $('notice').classList.toggle('error', error); $('notice').style.display='block';
  clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>{$('notice').style.display='none';},6000);
}
function send(action, data={}, acknowledge=true) {
  if (ws?.readyState!==WebSocket.OPEN || !client) {
    if (acknowledge) notice('Backend disconnected. Controls are unavailable.',true);
    return Promise.reject(new Error('Backend disconnected'));
  }
  const request_id=acknowledge ? ++request : undefined;
  ws.send(JSON.stringify({action,data,request_id}));
  if (!acknowledge) return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(request_id);reject(new Error('Backend request timed out'));notice('Backend request timed out',true);},10000);
    pending.set(request_id,{resolve,reject,timer});
  });
}
function act(action,data={}) { return send(action,data).catch(()=>{}); }
function zero(disarm=true) {
  axes={throttle:0,steering:0,jog:0,deadman:false};keys.clear();pointerHold=false;pointerStick=null;
  $('throttle-slider').value=$('steering-slider').value='0';
  $('stick').style.transform='translate(0,0)';$('deadman').classList.remove('pressed');
  if (client && ws?.readyState===WebSocket.OPEN && state?.owner===client) {
    input(); if(disarm) act('disarm');
  }
}
function route() {
  const next=location.hash.slice(1) in pages ? location.hash.slice(1) : 'drive';
  if(next!==page) zero(); page=next;
  document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id===`page-${page}`));
  document.querySelectorAll('[data-route]').forEach(el=>el.classList.toggle('active',el.dataset.route===page));
  text('page-title',pages[page][0]);text('page-subtitle',pages[page][1]);text('breadcrumb',pages[page][0].toUpperCase());
  if(state) render(state);
}
addEventListener('hashchange',route);route();

function connect() {
  clearTimeout(reconnect);
  ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  ws.onmessage=({data})=>{
    const message=JSON.parse(data);
    if(message.type==='hello') { client=message.client; seq=0; zero(false);text('ws-label','Backend connected');$('ws-dot').style.background='var(--teal)'; }
    if(message.type==='state') {state=message.state;lastStateAt=performance.now();render(state);}
    if(message.type==='ack') {
      const task=pending.get(message.request_id);
      if(task){clearTimeout(task.timer);pending.delete(message.request_id);message.ok?task.resolve(message):task.reject(new Error(message.message));}
      if(!message.ok) notice(message.message,true);
    }
  };
  ws.onclose=()=>{
    zero(false);client=null;state=null;text('ws-label','Backend disconnected');$('ws-dot').style.background='var(--red)';
    text('control-label','DISCONNECTED');text('control-reason','Fresh operator input stopped');text('owner-label','Reconnecting…');
    document.querySelectorAll('.safety-actions button:not(.stop)').forEach(b=>b.disabled=true);
    for(const task of pending.values()){clearTimeout(task.timer);task.reject(new Error('Backend disconnected'));}pending.clear();
    reconnect=setTimeout(connect,1500);
  };
  ws.onerror=()=>ws.close();
}
connect();
setInterval(()=>{if(client && state?.owner===client)send('heartbeat',{},false).catch(()=>{});},1000);

function input() {
  if(!client || state?.owner!==client || page!=='drive' || document.hidden || !document.hasFocus())return;
  if(state.input_mode==='gamepad') {
    const config={stick:$('controller-stick').value,throttleAxis:Number($('raw-throttle').value),steeringAxis:Number($('raw-steering').value),holdButton:Number($('raw-hold').value)};
    const pad=[...(navigator.getGamepads?.()||[])].find(p=>p?.connected&&(config.stick==='raw'||p.mapping==='standard'));
    try{Object.assign(axes,readController(pad,config));gamepadConnected=true;text('gamepad-status',`${pad.id} · ${config.stick} mapping · axes ${pad.axes.map(v=>v.toFixed(2)).join(' / ')}`);}
    catch(error){axes.throttle=axes.steering=0;axes.deadman=false;gamepadConnected=false;text('gamepad-status',error.message+' · press a controller button to expose it to the browser');}
  } else {
    gamepadConnected=false;
    if(['KeyW','KeyA','KeyS','KeyD'].some(k=>keys.has(k))){axes.throttle=(keys.has('KeyW')?1:0)-(keys.has('KeyS')?1:0);axes.steering=(keys.has('KeyD')?1:0)-(keys.has('KeyA')?1:0);}
    axes.deadman=pointerHold||keys.has('Space');
    text('gamepad-status',state.input_mode==='rc-demo'?'RC emulation only · no physical RC receiver connected.':'Drag the stick, or use W A S D. Hold Space to drive.');
  }
  send('input',{...axes,seq:++seq,gamepad_connected:gamepadConnected},false).catch(()=>{});
  $('throttle-slider').value=axes.throttle;$('steering-slider').value=axes.steering;text('throttle-slider-value',fmt(axes.throttle));text('steering-slider-value',fmt(axes.steering));
  text('throttle-value',fmt(axes.throttle));text('steering-value',fmt(axes.steering));
  $('stick').style.transform=`translate(${axes.steering*65}px,${-axes.throttle*65}px)`;
  $('deadman').classList.toggle('pressed',axes.deadman);
}
setInterval(input,50);
addEventListener('blur',()=>zero());
document.addEventListener('visibilitychange',()=>{if(document.hidden)zero();});
addEventListener('pagehide',()=>zero());
addEventListener('keydown',event=>{
  if(event.code==='Escape'){event.preventDefault();zero(false);act('stop');return;}
  if(page!=='drive'||event.target.matches('input:not([type=range]),select,textarea'))return;
  if(['KeyW','KeyA','KeyS','KeyD','Space'].includes(event.code)){event.preventDefault();keys.add(event.code);}
});
addEventListener('keyup',event=>{
  if(keys.has(event.code)){event.preventDefault();keys.delete(event.code);if(['KeyW','KeyS'].includes(event.code))axes.throttle=0;if(['KeyA','KeyD'].includes(event.code))axes.steering=0;input();}
});
function hold(element,on,off) {
  element.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();element.setPointerCapture(e.pointerId);on();input();});
  for(const name of ['pointerup','pointercancel','lostpointercapture']) element.addEventListener(name,()=>{off();input();});
  element.addEventListener('contextmenu',e=>e.preventDefault());
}
hold($('deadman'),()=>{pointerHold=true;},()=>{pointerHold=false;axes.deadman=false;});
document.querySelectorAll('[data-jog]').forEach(b=>hold(b,()=>{axes.jog=Number(b.dataset.jog);},()=>{axes.jog=0;}));
const joystick=$('joystick');
joystick.addEventListener('pointerdown',e=>{
  if(state?.input_mode==='gamepad'||e.button!==0)return;
  e.preventDefault();keys.clear();pointerStick=e.pointerId;joystick.setPointerCapture(e.pointerId);stickMove(e);
});
function stickMove(e){if(pointerStick!==e.pointerId)return;const r=joystick.getBoundingClientRect(),dx=(e.clientX-r.left-r.width/2)/70,dy=(e.clientY-r.top-r.height/2)/70;const scale=Math.max(1,Math.hypot(dx,dy));axes.steering=Math.max(-1,Math.min(1,dx/scale));axes.throttle=Math.max(-1,Math.min(1,-dy/scale));input();}
joystick.addEventListener('pointermove',stickMove);
for(const name of ['pointerup','pointercancel','lostpointercapture'])joystick.addEventListener(name,()=>{pointerStick=null;axes.throttle=axes.steering=0;input();});
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{if(['stop','disarm','reset_model'].includes(b.dataset.action))zero(false);act(b.dataset.action);}));
$('ownership').onclick=()=>act(state?.owner===client?'release':'claim');
$('input-mode').onchange=()=>{zero();act('input_mode',{mode:$('input-mode').value});};
$('speed').oninput=()=>text('speed-value',`${$('speed').value}%`);
$('speed').onchange=()=>act('speed_limit',{value:Number($('speed').value)/100});
for(const key of ['throttle','steering']) $(`${key}-slider`).oninput=()=>{axes[key]=Number($(`${key}-slider`).value);input();};
for(const id of ['controller-stick','raw-throttle','raw-steering','raw-hold'])$(id).onchange=()=>zero();
$('controller-rescan').onclick=()=>zero();
$('connect-oc').onclick=()=>{zero();act('connect',{mode:'oc-mock'});};
$('connect-ros').onclick=()=>{zero();act('connect',{mode:'ros2',namespace:$('ros-namespace').value.trim()});};
$('mock-apply').onclick=()=>act('mock_options',{reply_delay_ms:Number($('mock-delay').value),drop_commands:$('mock-drop').value==='true'});
initPriorities(send,notice);
$('joint').onchange=()=>{axes.jog=0;act('joint',{joint:$('joint').value});};
$('connect-mock').onclick=()=>{zero();act('connect',{mode:'mock'});};
$('connect-udp').onclick=()=>{zero();act('connect',{mode:'udp',host:$('rover-host').value.trim(),port:Number($('rover-port').value)});};
$('gps-connect').onclick=()=>act('gps_mode',{mode:$('gps-mode').value,port:$('serial-port').value,baud:Number($('baud').value)});
async function ports(){try{const rows=await(await fetch('/api/ports')).json();$('serial-port').replaceChildren(new Option('Select port',''),...rows.map(r=>new Option(`${r.device} · ${r.description}`,r.device)));}catch{notice('Unable to list serial ports',true);}}
$('refresh-ports').onclick=ports;ports();
$('comparison-file').onchange=async()=>{const file=$('comparison-file').files[0];if(!file)return;if(file.size>512000){notice('Comparison must be smaller than 512 KB',true);return;}await act('gps_compare',{content:await file.text()});$('comparison-file').value='';};

function render(s) {
  const mine=s.owner===client, c=s.control, r=s.rover, g=s.gps;
  const modeLabel=({'model':'MODEL ONLY','mock':'NET5 LOCAL MOCK','udp':'NET5 CHASSIS UDP','oc-mock':'OC LOOPBACK','ros2':'ONBOARD ROS 2'})[s.mode]||s.mode;
  text('mode-tag',modeLabel);renderPriorities(s.video_priorities,mine);
  const seconds=Math.floor(s.uptime_s);text('uptime',`T+${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`);
  text('owner-label',mine?'You own the controls':s.owner?'View-only browser':'Controls available');text('ownership',mine?'Release control':'Acquire control');$('ownership').disabled=!!s.owner&&!mine;
  text('control-label',c.stop_latched?'STOP LATCHED':c.enabled?'ENABLED':'DISARMED');text('control-reason',c.reason);
  $('control-light').style.background=c.stop_latched?'var(--red)':c.enabled?'var(--teal)':'var(--amber)';
  $('enable').disabled=!mine||page!=='drive'||c.enabled||c.stop_latched;$('reset-stop').disabled=!mine||!c.stop_latched;
  document.querySelectorAll('[data-action="disarm"], [data-action="stop"]').forEach(b=>b.disabled=false);
  for(const id of ['input-mode','speed','joint','arm-mode','connect-mock','connect-udp','connect-oc','gps-connect','input-pause'])$(id).disabled=!mine;
  document.querySelectorAll('.jog').forEach(b=>b.disabled=!mine||!s.arm_mode||!c.enabled);
  $('mock-silent').disabled=$('mock-apply').disabled=!mine||s.mode!=='mock';$('claim-oc').disabled=!mine||!s.onboard;$('connect-ros').disabled=!mine||!s.ros2_available;$('throttle-slider').disabled=$('steering-slider').disabled=!mine||s.input_mode==='gamepad';
  text('ros-availability',s.ros2_available?'ROS 2 interfaces available in this Python environment':'ROS 2/DDS unavailable here; OC loopback exercises the same upstream Python supervisor on this Mac.');
  text('left-value',`${fmt(c.left*100,1)}%`);text('right-value',`${fmt(c.right*100,1)}%`);
  $('left-meter').style.width=`${Math.abs(c.left)*400}%`;$('right-meter').style.width=`${Math.abs(c.right)*400}%`;
  text('input-age',fmt(s.input_age_s===null?null:s.input_age_s*1000,0,' ms'));
  text('link-value',s.onboard?(s.onboard.fault?'OC feedback fault':s.onboard.state?.mcu_ready?'OC / MCU ready':'Waiting for OC/MCU'):r.fault?'Link fault':r.pending_enable?'Enabling…':s.connection_degraded?'Degraded':r.ready?'Ready':r.connected?'Handshaking':'Disconnected');
  text('link-detail',r.fault|| (r.connected?`${s.mode==='mock'?'Local mock · ':''}ACK ${fmt(r.rtt_ms,1,' ms')}`:'Model runs without motor hardware'));
  if(document.activeElement!==$('input-mode'))$('input-mode').value=s.input_mode;
  text('input-badge',s.input_mode==='virtual'?'VIRTUAL STICK':s.input_mode==='gamepad'?'GAMEPAD':'RC PREVIEW');
  if(document.activeElement!==$('speed')){$('speed').value=s.speed_limit*100;text('speed-value',`${Math.round(s.speed_limit*100)}%`);}
  text('arm-mode',s.arm_mode?'Leave arm preview':'Enter arm preview');$('joint').value=s.joint;text('arm-preview',JSON.stringify(c.arm_preview,null,2));
  text('pose-e',fmt(s.pose[0],2,' m'));text('pose-n',fmt(s.pose[1],2,' m'));text('pose-yaw',fmt(((s.pose[2]*180/Math.PI)%360+360)%360,1,'°'));
  $('events').innerHTML=s.events.slice(0,18).map(e=>`<div class="${esc(e.kind)}"><time>T+${e.time_s.toFixed(1)}s</time><span>${esc(e.text)}</span></div>`).join('');
  text('gps-status',g.mode==='demo'?(g.fresh?'SYNTHETIC FIX':'SYNTHETIC / WAITING'):g.fresh?'VALID FIX':'NO FRESH FIX');
  $('gps-status').classList.toggle('teal',g.fresh);text('gps-lat',fmt(g.latitude,7,'°'));text('gps-lon',fmt(g.longitude,7,'°'));
  text('gps-quality',`${g.satellites??'—'} / ${fmt(g.hdop,1)}`);text('gps-scatter',g.scatter?fmt(g.scatter[2],3,' m'):'—');
  text('gps-error',g.error||'');text('gps-meta',`${g.samples} fixes · ${g.bad} rejected · ${g.duplicates} duplicates · Fix age ${fmt(g.age_s,1,' s')} · Speed ${fmt(g.speed_mps,2,' m/s')}`);
  text('comparison-label',g.comparison.label);const m=g.comparison.metrics;text('compare-count',m.count);text('compare-rmse',fmt(m.rmse_m,3,' m'));text('compare-bias',`${fmt(m.bias_e_m,2)} / ${fmt(m.bias_n_m,2)} m`);text('compare-skipped',g.comparison.skipped);
  text('rtt',fmt(r.rtt_ms,2,' ms'));text('rx-age',fmt(r.age_s,2,' s'));text('rejected',r.rejected);text('log-rows',`${s.log_rows.toLocaleString()} / 12,000 rows`);
  text('telemetry-state',r.state?.state||r.state?.type|| (r.ready?'READY':'DISCONNECTED'));
  text('rover-json',r.state?JSON.stringify(r.state,null,2):'No telemetry received');text('command-json',JSON.stringify({...c,onboard_request_preview:s.onboard_request_preview},null,2));
  text('connection-tag',modeLabel);
  text('connection-detail',s.connection_summary||'Disconnected');
  text('diagnostics-json',JSON.stringify(s.diagnostics,null,2));text('fault-json',s.first_fault?JSON.stringify(s.first_fault,null,2):'No captured fault');text('onboard-json',s.onboard?JSON.stringify(s.onboard,null,2):'No onboard transport connected');text('onboard-summary',s.onboard?`Owns OC: ${s.onboard.owned} · feedback fresh: ${s.onboard.fresh}\nSupervisor enabled: ${s.onboard.state?.supervisor_enabled??'unknown'} · MCU enabled: ${s.onboard.state?.mcu_enabled??'unknown'}\n${s.onboard.state?.reason||'Waiting for onboard state'}`:'No onboard transport connected');
  const enc=s.onboard?.state?{counts:s.onboard.state.encoder_counts.map((v,i)=>s.onboard.state.encoder_valid[i]?v:null),rates:s.onboard.state.encoder_count_rate,rate_valid:s.onboard.state.encoder_rate_valid,fresh:s.onboard.fresh&&s.onboard.state.mcu_ready}:s.encoders;
  $('encoder-rows').innerHTML=['FL','RL','FR','RR'].map((wheel,i)=>`<tr><td>${wheel}</td><td>${enc?.fresh&&enc.counts[i]!==null?esc(enc.counts[i]):'N/A'}</td><td>${enc?.fresh&&enc.rate_valid[i]?fmt(enc.rates[i],1):'N/A'}</td></tr>`).join('');
  text('mock-silent',r.mock_silent?'Restore ACKs':'Drop ACKs');text('input-pause',s.input_paused?'Resume input':'Pause input');
  text('authority-detail',`${s.clients} browser session${s.clients===1?'':'s'} connected. ${mine?'This browser owns the controls.':s.owner?'Another browser owns the controls.':'No operator currently owns the controls.'}`);
  if(page==='drive')drawMap('drive-map',[{points:s.path,color:'#67ddbf'}],s.pose,2);
  if(page==='gps') {drawMap('gps-map',[{points:g.track,color:'#67ddbf'}],null,1);drawMap('compare-map',[{points:g.comparison.pairs.map(p=>p.slice(1,3)),color:'#e5b86e'},{points:g.comparison.pairs.map(p=>p.slice(3,5)),color:'#67ddbf'}],null,1);}
  if(page==='telemetry')drawHistory(s.history);
  if(page==='cameras')renderCameras(s);
}

function canvas(id){const el=$(id),rect=el.getBoundingClientRect();if(!rect.width||!rect.height)return null;const scale=devicePixelRatio||1;el.width=Math.round(rect.width*scale);el.height=Math.round(rect.height*scale);const ctx=el.getContext('2d');ctx.scale(scale,scale);return{ctx,w:rect.width,h:rect.height};}
function drawMap(id,series,pose,minRange){const c=canvas(id);if(!c)return;const{ctx,w,h}=c;const all=series.flatMap(s=>s.points);if(pose)all.push(pose);let minX=-minRange,maxX=minRange,minY=-minRange,maxY=minRange;for(const p of all){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}const midX=(minX+maxX)/2,midY=(minY+maxY)/2,span=Math.max(maxX-minX,maxY-minY)*1.4,unit=Math.min(w,h)/span;const xy=p=>[w/2+(p[0]-midX)*unit,h/2-(p[1]-midY)*unit];ctx.clearRect(0,0,w,h);const step=Math.pow(10,Math.floor(Math.log10(span/5)));ctx.strokeStyle='#1e3443';ctx.lineWidth=1;ctx.font='9px monospace';ctx.fillStyle='#536f83';for(let x=Math.floor(minX/step)*step-span;x<=maxX+span;x+=step){let a=xy([x,0])[0];ctx.beginPath();ctx.moveTo(a,0);ctx.lineTo(a,h);ctx.stroke();if(a>15&&a<w-25)ctx.fillText(x.toFixed(step<1?1:0),a+4,h-28);}for(let y=Math.floor(minY/step)*step-span;y<=maxY+span;y+=step){let b=xy([0,y])[1];ctx.beginPath();ctx.moveTo(0,b);ctx.lineTo(w,b);ctx.stroke();}const origin=xy([0,0]);ctx.strokeStyle='#496475';ctx.beginPath();ctx.moveTo(origin[0]-6,origin[1]);ctx.lineTo(origin[0]+6,origin[1]);ctx.moveTo(origin[0],origin[1]-6);ctx.lineTo(origin[0],origin[1]+6);ctx.stroke();for(const s of series){ctx.strokeStyle=s.color;ctx.lineWidth=2;ctx.beginPath();s.points.forEach((p,i)=>{const a=xy(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.stroke();if(s.points.length){const a=xy(s.points.at(-1));ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(...a,3,0,Math.PI*2);ctx.fill();}}if(pose){const p=xy(pose);ctx.save();ctx.translate(...p);ctx.rotate(-pose[2]+Math.PI/2);ctx.fillStyle='#67ddbf';ctx.strokeStyle='#a3f0da';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(0,-14);ctx.lineTo(9,10);ctx.lineTo(0,6);ctx.lineTo(-9,10);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();}}
function drawHistory(rows){const c=canvas('history-plot');if(!c)return;const{ctx,w,h}=c;ctx.clearRect(0,0,w,h);const pad=35;ctx.font='9px monospace';ctx.fillStyle='#6b8a9e';for(const v of [-.25,0,.25]){const y=h/2-v*(h-60);ctx.strokeStyle='#29404e';ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-15,y);ctx.stroke();ctx.fillText(`${v*100}%`,3,y+3);}if(rows.length<2)return;const end=rows.at(-1).t;for(const[key,color]of[['left','#67ddbf'],['right','#e5b86e']]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();rows.forEach((r,i)=>{const x=pad+(r.t-(end-20))/20*(w-pad-15),y=h/2-r[key]*(h-60);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}ctx.fillText('−20 s',pad,h-10);ctx.fillText('NOW',w-35,h-10);}
addEventListener('resize',()=>state&&render(state));

const cameraNames={front:'Front navigation',gripper:'Gripper',aux1:'Auxiliary 01',aux2:'Auxiliary 02'};
for(const[key,label]of Object.entries(cameraNames)){
  $('camera-grid').insertAdjacentHTML('beforeend',`<article class="panel camera-panel" data-camera="${key}"><div class="panel-head"><h2>${label}</h2><span class="tag" id="cam-tag-${key}">OFFLINE</span></div><div class="camera-view"><div class="camera-placeholder"><span>▣</span>NO IMAGE SOURCE</div><img id="cam-img-${key}" class="hidden" alt="${label} snapshot"><span class="camera-overlay" id="cam-overlay-${key}">SOURCE OFF</span></div><div class="camera-settings"><label class="field">Source<select id="cam-mode-${key}"><option value="demo">Generated demo</option><option value="snapshot">HTTP JPEG / PNG snapshot</option></select></label><label class="field">Snapshot URL<input id="cam-url-${key}" placeholder="http://camera/snapshot.jpg"></label><div class="button-row"><button id="cam-start-${key}" class="primary">Apply source</button><button id="cam-stop-${key}">Turn off</button></div><div class="camera-error" id="cam-error-${key}" role="status"></div></div></article>`);
  $(`cam-start-${key}`).onclick=()=>act('camera',{camera:key,mode:$(`cam-mode-${key}`).value,url:$(`cam-url-${key}`).value.trim()});
  $(`cam-stop-${key}`).onclick=()=>act('camera',{camera:key,mode:'off'});
  $(`cam-img-${key}`).onerror=()=>{$(`cam-img-${key}`).classList.add('hidden');};
}
function renderCameras(s){
  const refresh=performance.now()-snapshotTime>450;
  for(const cam of s.cameras){
    const key=cam.id,img=$(`cam-img-${key}`),active=['demo','snapshot'].includes(cam.mode);
    text(`cam-tag-${key}`,cam.mode==='off'?'OFFLINE':cam.error?'SOURCE ERROR':cam.age_s!==null&&cam.age_s<2?'RECEIVING':'WAITING');
    text(`cam-overlay-${key}`,cam.mode==='demo'?'GENERATED DEMO':cam.mode==='off'?'SOURCE OFF':cam.age_s!==null&&cam.age_s>2?'STALE FRAME':'HTTP SNAPSHOT');
    if(active&&refresh){img.classList.remove('hidden');img.src=`/api/cameras/${key}/image?t=${s.sequence}`;}
    else if(!active)img.classList.add('hidden');
    text(`cam-error-${key}`,cam.error||'');
    $(`cam-start-${key}`).disabled=s.owner!==client;$(`cam-stop-${key}`).disabled=s.owner!==client;
  }
  if(refresh)snapshotTime=performance.now();
}
setInterval(()=>{if(state&&performance.now()-lastStateAt>1500){zero();notice('State updates stalled. Controls disarmed.',true);}},1000);
