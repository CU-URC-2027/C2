const $=id=>document.getElementById(id);
const ids=Array.from({length:5},(_,i)=>`cam-0${i+1}`);
const rate=n=>`${((n||0)/1e6).toFixed(2)} Mb/s`;
let wanted=false,visible=!document.hidden;
const views=new Map();
const supported=typeof VideoDecoder==='function'&&typeof EncodedVideoChunk==='function';
$('live-codec-capability').textContent=supported?`WebCodecs available · ${isSecureContext?'secure local context':'insecure context'}`:'WebCodecs is unavailable in this browser. Open this local station in current Chrome or Safari.';
$('live-video-toggle').disabled=!supported;

// Move one panel between workspaces. A route change must not create another set
// of video sockets or decoders, or publish any operator input.
const panel=$('live-video-panel');
let primary='cam-01';
function videoPage(){
  const page=location.hash.slice(1);
  if(page==='cameras')return 'cameras';
  return ['gps','telemetry','connections','development'].includes(page)?null:'drive';
}
function active(){return wanted&&visible&&videoPage()!==null;}
function layout(){
  const page=videoPage();
  if(page){
    const slot=$(`${page}-video-slot`);
    if(panel.parentElement!==slot)slot.append(panel);
    panel.dataset.layout=page;
  }
  for(const [id,view] of views)view.canvas.closest('.live-video-tile').classList.toggle('primary-view',id===primary);
}
class CameraView{
  constructor(id){
    this.id=id;this.paused=false;this.socket=null;this.decoder=null;this.config=null;this.epoch=null;this.generation=0;
    this.pending=[];this.processing=false;this.waiting=true;this.latest=null;this.frames=[];this.submitted=new Map();this.anchor=null;this.raf=0;this.reconnect=null;
    this.decoded=this.rendered=this.dropped=this.lastSequence=0;this.decodeTimes=[];this.renderTimes=[];
    this.overwrites=this.pendingDrops=this.decoderOverflows=this.epochChanges=0;this.lastKeyframeRequest=-Infinity;this.lastDraw=0;this.lastArrival=0;this.arrivalToRender=0;this.error=null;this.server=null;
    const tile=document.createElement('article');tile.className='live-video-tile';tile.id=`live-${id}`;
    tile.innerHTML=`<div class="live-video-head"><h3>Camera ${id.slice(-2)}</h3><span id="live-status-${id}">OFF</span><button id="live-pause-${id}">Pause view</button></div><div class="live-video-picture"><canvas id="live-canvas-${id}" aria-label="Camera ${id.slice(-2)} received H.264 video"></canvas><div id="live-overlay-${id}" class="live-video-overlay">Video playback off</div></div><div id="live-metrics-${id}" class="live-video-metrics">No received video</div>`;
    $('live-video-grid').append(tile);this.canvas=$(`live-canvas-${id}`);this.ctx=this.canvas.getContext('2d',{alpha:false});
    $(`live-pause-${id}`).onclick=()=>{this.paused=!this.paused;$(`live-pause-${id}`).textContent=this.paused?'Resume view':'Pause view';sync();};
  }
  overlay(text){$(`live-overlay-${this.id}`).textContent=text;$(`live-overlay-${this.id}`).hidden=!text;}
  resetDecoder(){
    this.generation++;this.pending=[];this.waiting=true;this.config=null;this.epoch=null;
    if(this.decoder){try{this.decoder.close();}catch{}this.decoder=null;}
    if(this.latest){this.latest.frame.close();this.latest=null;}
    for(const item of this.frames)item.frame.close();this.frames=[];this.submitted.clear();this.anchor=null;
    if(this.raf)cancelAnimationFrame(this.raf);this.raf=0;
  }
  disconnect(){
    clearTimeout(this.reconnect);this.reconnect=null;
    if(this.socket){this.socket.onclose=null;this.socket.close();this.socket=null;}
    this.resetDecoder();this.overlay(this.paused?'View paused':wanted?'Video view hidden':'Video playback off');
    $(`live-status-${this.id}`).textContent=this.paused?'PAUSED':'OFF';
  }
  connect(){
    if(this.socket||!active()||this.paused)return;
    const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/video/${this.id}`);
    this.socket=socket;socket.binaryType='arraybuffer';this.error=null;this.overlay('Waiting for received H.264…');
    socket.onmessage=({data})=>{
      if(this.socket!==socket)return;
      if(typeof data==='string'){
        const status=JSON.parse(data);this.server=status.camera;
        if(!this.server.fresh){this.overlay(this.server.connected?'Video stale · waiting for fresh frames':'Not currently transmitted');if(this.decoder)this.resetDecoder();}
        this.metrics();return;
      }
      if(this.pending.length>=6){this.pendingDrops+=this.pending.length;this.dropped+=this.pending.length;this.pending=[];this.waiting=true;this.keyframe();}
      this.pending.push({data,arrival:performance.now()});this.process();
    };
    socket.onclose=()=>{
      if(this.socket!==socket)return;this.socket=null;this.resetDecoder();this.overlay('Video connection lost · reconnecting');
      $(`live-status-${this.id}`).textContent='DISCONNECTED';
      if(active()&&!this.paused)this.reconnect=setTimeout(()=>this.connect(),500);
    };
    socket.onerror=()=>socket.close();
  }
  keyframe(){const now=performance.now();if(now-this.lastKeyframeRequest<250)return;this.lastKeyframeRequest=now;if(this.socket?.readyState===WebSocket.OPEN)this.socket.send(JSON.stringify({type:'keyframe'}));}
  async process(){
    if(this.processing)return;this.processing=true;
    try{
      while(this.pending.length&&this.socket){
        const item=this.pending.shift(),dv=new DataView(item.data);
        if(dv.byteLength<12||dv.getUint32(0)!==0x55524231)throw new Error('Invalid video framing');
        const m=dv.getUint32(4),p=dv.getUint32(8);
        if(m>4096||p>16*1024*1024||12+m+p!==dv.byteLength)throw new Error('Invalid video record size');
        const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(item.data,12,m)));
        if(Number.isFinite(meta.received_wall_ms)&&Date.now()-meta.received_wall_ms>750){this.dropped++;this.socket.close();continue;}
        const epoch=`${meta.connection_epoch}:${meta.session}:${meta.codec_string}:${meta.width}x${meta.height}`;
        if(epoch!==this.epoch){
          this.epochChanges++;
          if(!meta.keyframe){this.dropped++;this.keyframe();continue;}
          // Preserve only this fresh keyframe while configuration is being checked.
          this.resetDecoder();const generation=this.generation;
          const config={codec:meta.codec_string,codedWidth:meta.width,codedHeight:meta.height,optimizeForLatency:true,hardwareAcceleration:'prefer-hardware'};
          const support=await VideoDecoder.isConfigSupported(config);
          if(generation!==this.generation||!this.socket)continue;
          if(!support.supported)throw new Error(`Unsupported H.264 configuration ${meta.codec_string} ${meta.width}×${meta.height}`);
          this.config=config;this.epoch=epoch;this.waiting=true;
          this.decoder=new VideoDecoder({output:frame=>this.output(frame,generation),error:error=>{
            this.error=error.message;this.overlay(`Decoder recovery: ${error.message}`);this.resetDecoder();this.keyframe();
          }});this.decoder.configure(config);
        }
        if(this.waiting&&!meta.keyframe){this.dropped++;continue;}
        if(this.decoder.decodeQueueSize>4){this.decoderOverflows++;this.dropped++;this.resetDecoder();this.keyframe();continue;}
        this.waiting=false;this.lastArrival=item.arrival;
        this.submitted.set(meta.pts_us,{sequence:meta.sequence,arrival:item.arrival});
        while(this.submitted.size>32)this.submitted.delete(this.submitted.keys().next().value);
        this.decoder.decode(new EncodedVideoChunk({type:meta.keyframe?'key':'delta',timestamp:meta.pts_us,data:new Uint8Array(item.data,12+m,p)}));
      }
    }catch(error){this.error=error.message;this.overlay(error.message);this.resetDecoder();this.keyframe();}
    finally{this.processing=false;}
  }
  output(frame,generation){
    if(generation!==this.generation||!active()||this.paused){frame.close();return;}
    this.decoded++;this.decodeTimes.push(performance.now());
    const meta=this.submitted.get(frame.timestamp)||{arrival:performance.now(),sequence:0};this.submitted.delete(frame.timestamp);
    this.frames.push({frame,...meta});
    if(!this.anchor)this.anchor={pts:frame.timestamp,time:performance.now()+80};
    while(this.frames.length>5){this.frames.shift().frame.close();this.dropped++;this.overwrites++;}
    if(!this.raf)this.raf=requestAnimationFrame(()=>this.draw());
  }
  draw(){
    this.raf=0;if(!this.frames.length)return;
    if(!active()||this.paused){for(const item of this.frames)item.frame.close();this.frames=[];return;}
    const now=performance.now();let item=null;
    // A short PTS-based playout queue smooths batched native decoder callbacks.
    // Never build an unbounded display queue when the tab or renderer stalls.
    while(this.frames.length&&this.anchor.time+(this.frames[0].frame.timestamp-this.anchor.pts)/1000<=now){
      if(item){item.frame.close();this.dropped++;this.overwrites++;}item=this.frames.shift();
    }
    if(item){try{
      const frame=item.frame;
      this.decodedWidth=frame.displayWidth;this.decodedHeight=frame.displayHeight;
      const width=Math.min(frame.displayWidth,960,Math.max(320,Math.round(this.canvas.clientWidth*(devicePixelRatio||1)))),height=Math.round(width*frame.displayHeight/frame.displayWidth);
      if(this.canvas.width!==width||this.canvas.height!==height){this.canvas.width=width;this.canvas.height=height;}
      this.ctx.drawImage(frame,0,0,width,height);this.rendered++;this.lastSequence=item.sequence;this.lastDraw=now;this.renderTimes.push(now);
      this.arrivalToRender=now-item.arrival;this.error=null;this.overlay('');$(`live-status-${this.id}`).textContent='LIVE';
    }finally{item.frame.close();}}
    if(this.frames.length)this.raf=requestAnimationFrame(()=>this.draw());
  }
  metrics(){
    const now=performance.now();this.decodeTimes=this.decodeTimes.filter(t=>now-t<2000);this.renderTimes=this.renderTimes.filter(t=>now-t<2000);
    const fps=a=>a.length>1?(a.length-1)*1000/(a.at(-1)-a[0]):0;
    this.renderFps=now-this.lastDraw<1000?fps(this.renderTimes):0;this.decodeFps=fps(this.decodeTimes);
    const s=this.server;
    $(`live-metrics-${this.id}`).textContent=`${this.decodedWidth||0}×${this.decodedHeight||0} decoded · RX ${(s?.receive_fps||0).toFixed(1)} / decode ${this.decodeFps.toFixed(1)} / render ${this.renderFps.toFixed(1)} fps · ${rate(s?.received_bitrate_bps)} · ${this.rendered} rendered · ${this.dropped} skipped${this.error?' · '+this.error:''}`;
    this.canvas.dataset.decodedWidth=String(this.decodedWidth||0);this.canvas.dataset.decodedHeight=String(this.decodedHeight||0);this.canvas.dataset.rendered=String(this.rendered);this.canvas.dataset.sequence=String(this.lastSequence);
    this.canvas.dataset.renderFps=this.renderFps.toFixed(2);this.canvas.dataset.codec=this.config?.codec||'';this.canvas.dataset.diagnostics=JSON.stringify({overwrites:this.overwrites,pendingDrops:this.pendingDrops,decoderOverflows:this.decoderOverflows,epochChanges:this.epochChanges,decoded:this.decoded});
    if(active()&&!this.paused&&this.lastDraw&&now-this.lastDraw>1000){this.overlay('Video stale · last frame is no longer current');$(`live-status-${this.id}`).textContent='STALE';}
  }
  report(){
    this.metrics();
    if(this.socket?.readyState===WebSocket.OPEN)this.socket.send(JSON.stringify({type:'render',rendered_frames:this.rendered,decoded_frames:this.decoded,
      last_sequence:this.lastSequence,render_fps:this.renderFps||0,decode_fps:this.decodeFps||0,decoder_queue:this.decoder?.decodeQueueSize||0,client_dropped:this.dropped,arrival_to_render_ms:Math.max(0,this.arrivalToRender)}));
  }
}
for(const id of ids)views.set(id,new CameraView(id));
function sync(){layout();for(const view of views.values()){if(active()&&!view.paused)view.connect();else view.disconnect();}}
$('live-primary-camera').onchange=()=>{primary=$('live-primary-camera').value;layout();};
$('live-video-toggle').onclick=()=>{wanted=!wanted;$('live-video-toggle').textContent=wanted?'Stop live video':'Start live video';sync();};
$('live-restart-receiver').onclick=async()=>{try{const r=await fetch('/api/live-video/restart',{method:'POST'});if(!r.ok)throw new Error('Receiver restart failed');}catch(error){$('live-receiver-state').textContent=error.message;}};
addEventListener('hashchange',sync);document.addEventListener('visibilitychange',()=>{visible=!document.hidden;sync();});
addEventListener('pagehide',()=>{wanted=false;$('live-video-toggle').textContent='Start live video';sync();});
setInterval(()=>{for(const view of views.values())view.report();},500);
setInterval(async()=>{if(!videoPage()||document.hidden)return;try{
  const r=await fetch('/api/live-video/state'),s=await r.json();
  $('live-receiver-state').textContent=`Python PID ${s.process_pid} · TCP ${s.host}:${s.port} · ${s.cameras.filter(c=>c.connected).length}/5 connected · receiver restarts ${s.restart_count}`;
}catch{}},1000);
sync();
