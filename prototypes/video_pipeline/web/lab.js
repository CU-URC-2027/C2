import {initArchitecture,renderArchitecture} from './architecture.js';
import {initDecision,renderDecision} from './decision.js';
import {initEncoder,renderEncoder} from './encoder.js';
import {initTransmission,renderTransmission} from './transmission.js';
const $=id=>document.getElementById(id);
const client=crypto.randomUUID();
const canvas=$('canvas'),node=$('camera-node'),world=$('world');
let expanded=false,state=null,view={x:100,y:145,scale:1},drag=null,toastTimer,polling=false;
let pageActive=!document.hidden,previewInFlight=new Set(),lastPreview=new Map();
let sourcesWantRunning=false;
const specs=[
  ['cam-01','Camera 01',3840,2160,'#e9b86d'],
  ['cam-02','Camera 02',1920,1080,'#6edcc4'],
  ['cam-03','Camera 03',1920,1080,'#7cabef'],
  ['cam-04','Camera 04',1920,1080,'#bc99ec'],
  ['cam-05','Camera 05',1920,1080,'#ed91a7'],
];
for(const[id,name,w,h,color]of specs){
  $('source-list').insertAdjacentHTML('beforeend',`<div class="source-row ${id}"><span class="source-swatch"></span><span class="source-name">${name}</span><span class="source-spec">${w} × ${h} <small>/ 30</small></span><span class="source-fps" id="fps-${id}">STARTING</span><span class="source-meta" id="meta-${id}">NV12 · 8-bit</span><button class="endpoint-button" id="copy-${id}" title="Copy raw stream URL" aria-label="Copy ${name} raw stream URL">↗</button><span class="source-port" title="${name} · raw NV12 output"></span></div>`);
  $('preview-grid').insertAdjacentHTML('beforeend',`<article class="monitor ${id}"><div class="monitor-head">${name}<span>${w===3840?'4K30':'1080p30'}</span></div><div class="monitor-view">WAITING FOR SOURCE<img id="image-${id}" alt="${name} live synthetic source preview"></div><div class="monitor-foot"><span id="preview-frame-${id}">PREVIEW STARTING</span><b id="preview-rate-${id}">480 × 270</b></div></article>`);
  $(`copy-${id}`).onclick=async()=>{try{await navigator.clipboard.writeText(`${location.origin}/sources/${id}.nv12`);toast(`${name} raw stream URL copied`);}catch{toast(`Source: ${location.origin}/sources/${id}.nv12`);}};
}
function toast(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').style.display='none';},5000);}
function transform(){world.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;$('zoom-label').textContent=`${Math.round(view.scale*100)}%`;}
const initialPositions={'c2-node':[0,0],'link-node':[520,0],'status-node':[975,0],'decision-node':[1510,0],'camera-node':[0,720],'encoder-node':[975,1180],'transmission-node':[1980,1180]};
function resetLayout(){for(const[id,[x,y]]of Object.entries(initialPositions)){$(id).style.left=`${x}px`;$(id).style.top=`${y}px`;}updateWires();}
function updateWires(){for(const[pathId,from,to,offset]of[['wire-c2-link','c2-node','link-node',148],['wire-link-status','link-node','status-node',148],['wire-bandwidth','link-node','status-node',208],['wire-status-decision','status-node','decision-node',470]]){const a=$(from),b=$(to),x1=a.offsetLeft+a.offsetWidth,y1=a.offsetTop+offset,x2=b.offsetLeft,y2=b.offsetTop+offset,dx=Math.max(35,Math.abs(x2-x1)*.45);$(pathId).setAttribute('d',`M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`);}
  const d=$('decision-node'),e=$('encoder-node'),c=$('camera-node'),t=$('transmission-node');
  $('wire-encoder-transmission').setAttribute('d',`M ${e.offsetLeft+e.offsetWidth} ${e.offsetTop+160} C ${e.offsetLeft+e.offsetWidth+70} ${e.offsetTop+160}, ${t.offsetLeft-70} ${t.offsetTop+160}, ${t.offsetLeft} ${t.offsetTop+160}`);
  const c2=$('c2-node'),returnY=Math.max(e.offsetTop+e.offsetHeight,t.offsetTop+t.offsetHeight)+80;
  $('wire-transmission-c2').setAttribute('d',`M ${t.offsetLeft+t.offsetWidth} ${t.offsetTop+160} C ${t.offsetLeft+t.offsetWidth+100} ${t.offsetTop+160}, ${t.offsetLeft+t.offsetWidth+100} ${returnY}, ${t.offsetLeft+t.offsetWidth} ${returnY} L -80 ${returnY} L -80 ${c2.offsetTop+300} L ${c2.offsetLeft} ${c2.offsetTop+300}`);
  const dx=d.offsetLeft+d.offsetWidth/2,dy=d.offsetTop+d.offsetHeight,ex=e.offsetLeft+e.offsetWidth/2,ey=e.offsetTop;
  $('wire-decision-encoder').setAttribute('d',`M ${dx} ${dy} C ${dx} ${dy+70}, ${ex} ${ey-70}, ${ex} ${ey}`);
  const cx=c.offsetLeft+c.offsetWidth,cy=c.offsetTop+50,tx=e.offsetLeft,ty=e.offsetTop+175;
  $('wire-cameras-encoder').setAttribute('d',`M ${cx} ${cy} C ${cx+120} ${cy}, ${tx-120} ${ty}, ${tx} ${ty}`);
}
function fit(){const rect=canvas.getBoundingClientRect(),focus=$('focus-node').value,nodes=[...document.querySelectorAll('#world>.node')],elements=focus==='all'?nodes:[$(focus)];world.classList.toggle('focused',focus!=='all'&&$('isolate-node').checked);for(const item of nodes)item.classList.toggle('focused-node',item.id===focus);const minX=Math.min(...elements.map(e=>e.offsetLeft)),minY=Math.min(...elements.map(e=>e.offsetTop)),maxX=Math.max(...elements.map(e=>e.offsetLeft+e.offsetWidth)),maxY=Math.max(...elements.map(e=>e.offsetTop+e.offsetHeight));const width=maxX-minX,height=maxY-minY,scale=Math.min(1.1,(rect.width-75)/(width+40),(rect.height-145)/(height+35));view.scale=Math.max(.12,scale);view.x=(rect.width-width*view.scale)/2-minX*view.scale;view.y=115+(rect.height-145-height*view.scale)/2-minY*view.scale;transform();updateWires();document.dispatchEvent(new Event('lab-view-change'));}
function zoom(factor,x=canvas.clientWidth/2,y=canvas.clientHeight/2){const next=Math.max(.24,Math.min(1.6,view.scale*factor)),ratio=next/view.scale;view.x=x-(x-view.x)*ratio;view.y=y-(y-view.y)*ratio;view.scale=next;transform();}
$('zoom-in').onclick=()=>zoom(1.15);$('zoom-out').onclick=()=>zoom(1/1.15);$('fit').onclick=fit;$('focus-node').onchange=fit;$('isolate-node').onchange=fit;$('reset').onclick=()=>{resetLayout();$('focus-node').value='all';fit();};
canvas.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return;e.preventDefault();const rect=canvas.getBoundingClientRect();zoom(e.deltaY>0?1/1.1:1.1,e.clientX-rect.left,e.clientY-rect.top);},{passive:false});
canvas.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('button,input,select,pre'))return;const header=e.target.closest('.node-head'),target=header?.closest('.node');if(!header&&e.target.closest('.node'))return;e.preventDefault();drag={id:e.pointerId,x:e.clientX,y:e.clientY,vx:view.x,vy:view.y,target,nx:target?.offsetLeft,ny:target?.offsetTop};canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(drag?.id!==e.pointerId)return;if(drag.target){drag.target.style.left=`${drag.nx+(e.clientX-drag.x)/view.scale}px`;drag.target.style.top=`${drag.ny+(e.clientY-drag.y)/view.scale}px`;updateWires();}else{view.x=drag.vx+e.clientX-drag.x;view.y=drag.vy+e.clientY-drag.y;transform();}});
for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>drag=null);
addEventListener('resize',fit);

function sourceMonitorVisible(){return expanded&&pageActive&&getComputedStyle(node).visibility!=='hidden';}
async function lease(){try{await fetch(`/api/previews/${client}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({visible:sourceMonitorVisible()}),keepalive:true});}catch{}}
function clearPreviews(){for(const[id]of specs){const img=$(`image-${id}`);img.removeAttribute('src');const old=img.dataset.url;if(old){URL.revokeObjectURL(old);delete img.dataset.url;}lastPreview.delete(id);}}
$('toggle').onclick=()=>{expanded=!expanded;node.classList.toggle('collapsed',!expanded);$('toggle').innerHTML=expanded?'Hide previews <span>⌃</span>':'Show previews <span>⌃</span>';$('toggle').setAttribute('aria-expanded',String(expanded));if(!expanded)clearPreviews();lease();updateWires();};
document.addEventListener('visibilitychange',()=>{pageActive=!document.hidden;if(!pageActive)clearPreviews();lease();});
addEventListener('pagehide',()=>{pageActive=false;lease();});
document.addEventListener('lab-view-change',()=>{if(!sourceMonitorVisible())clearPreviews();lease();});
setInterval(lease,1500);lease();

$('pause').onclick=async()=>{const button=$('pause');button.disabled=true;try{const running=state?.sources.some(s=>s.running)??false;sourcesWantRunning=!running;if(!sourcesWantRunning)clearPreviews();const response=await fetch('/api/sources',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({running:sourcesWantRunning})});if(!response.ok)throw new Error('Source operation failed');state=await response.json();render();}catch(error){toast(error.message);}finally{button.disabled=false;}};

function render(){if(!state)return;const active=state.sources.filter(s=>s.running).length;
  renderArchitecture(state.architecture);
  renderDecision(state.architecture?.encoding_decision);
  renderEncoder(state.architecture?.encoder);
  renderTransmission(state.architecture?.transmission);
  $('server-status').textContent='● Local lab connected';$('server-status').style.color='#7ea99c';
  $('bank-status').textContent=active?`${active} / 5 sources running`:'Video streams off';$('bank-dot').style.background=active?'#7bd5bf':'#8496a7';
  $('preview-status').textContent=!active?'Generators stopped · no source workload':state.previews_enabled?'Preview conversion active':'Preview conversion off';$('pause').textContent=active?'Disable video streams':'Enable video streams';
  const rate=state.sources.reduce((sum,s)=>sum+(s.running?s.raw_mb_s:0),0);$('total-rate').textContent=`${rate.toFixed(1)} MB/s raw source payload`;
  for(const s of state.sources){$(`fps-${s.id}`).textContent=s.error?'ERROR':!s.running?'PAUSED':s.fps_actual?`${s.fps_actual.toFixed(1)} fps`:'STARTING';$(`fps-${s.id}`).classList.toggle('paused',!s.running);$(`meta-${s.id}`).textContent=`NV12 · PID ${s.process_pid??'—'} · #${String(s.sequence).padStart(6,'0')}`;$(`preview-frame-${s.id}`).textContent=!s.running?'SOURCE PAUSED':`SOURCE FRAME ${s.preview_sequence}`;if(s.error)toast(s.error);}
}
async function poll(){if(polling)return;polling=true;try{const response=await fetch('/api/state');if(!response.ok)throw new Error('No state');state=await response.json();render();}catch{$('server-status').textContent='● Local lab disconnected';$('server-status').style.color='#d68e8e';}finally{polling=false;}}
let lastPollAt=0;setInterval(()=>{const now=performance.now();if(now-lastPollAt>(pageActive?200:1000)){lastPollAt=now;poll();}},100);poll();
async function image(source){const id=source.id;if(previewInFlight.has(id)||!source.running||source.preview_sequence===lastPreview.get(id))return;previewInFlight.add(id);try{const response=await fetch(`/preview/${id}.jpg?frame=${source.preview_sequence}`);if(!response.ok)return;const blob=await response.blob();if(!sourceMonitorVisible())return;const img=$(`image-${id}`),old=img.dataset.url,url=URL.createObjectURL(blob);img.src=url;img.dataset.url=url;if(old)URL.revokeObjectURL(old);lastPreview.set(id,source.preview_sequence);}catch{}finally{previewInFlight.delete(id);}}
setInterval(()=>{if(sourceMonitorVisible()&&state?.previews_enabled)for(const source of state.sources)image(source);},167);
initArchitecture(toast,updateWires);initDecision(toast,updateWires);initEncoder(toast,updateWires);initTransmission(toast,updateWires);resetLayout();requestAnimationFrame(fit);
