import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Component harness, not a browser substitute: exercise resource ownership and
// route changes without a camera, decoder installation or controller authority.
function harness(hash='#drive') {
  const elements=new Map(),events=new Map(),documentEvents=new Map(),sockets=[],decoders=[];
  class Element {
    constructor(id){this.id=id;this.dataset={};this.classes=new Set();this.parentElement=null;this.clientWidth=640;
      this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
    set innerHTML(html){for(const [,id] of html.matchAll(/id="([^"]+)"/g)){const child=new Element(id);child.parentElement=this;elements.set(id,child);}}
    append(child){child.parentElement=this;}
    closest(){return this.parentElement;}
    getContext(){return {drawImage(){}};}
  }
  for(const id of ['live-codec-capability','live-video-toggle','live-video-panel','drive-video-slot',
    'cameras-video-slot','live-video-grid','live-primary-camera','live-restart-receiver','live-receiver-state'])elements.set(id,new Element(id));
  elements.get('live-primary-camera').value='cam-01';
  class Socket {
    static OPEN=1;
    constructor(url){this.url=url;this.readyState=1;this.sent=[];sockets.push(this);}
    send(message){this.sent.push(message);}
    close(){this.readyState=3;this.onclose?.();}
  }
  class Decoder {
    static async isConfigSupported(){return {supported:true};}
    constructor(){this.decodeQueueSize=0;this.closed=false;decoders.push(this);}
    configure(){} decode(){} close(){this.closed=true;}
  }
  const document={hidden:false,getElementById:id=>elements.get(id),createElement:()=>new Element('tile'),
    addEventListener:(name,callback)=>documentEvents.set(name,callback)};
  const location={hash,protocol:'http:',host:'127.0.0.1:8870'};
  vm.runInNewContext(readFileSync(new URL('../web/live-video.js',import.meta.url),'utf8'),{
    document,location,VideoDecoder:Decoder,EncodedVideoChunk:class{},WebSocket:Socket,isSecureContext:true,
    addEventListener:(name,callback)=>events.set(name,callback),setInterval(){},setTimeout(){},clearTimeout(){},
    requestAnimationFrame(){},cancelAnimationFrame(){},performance,TextDecoder,DataView,Uint8Array,devicePixelRatio:1,
  });
  return {elements,sockets,decoders,document,events,documentEvents,location,
    toggle:()=>elements.get('live-video-toggle').onclick(),
    route(value){location.hash=value;events.get('hashchange')();},
    live:()=>sockets.filter(socket=>socket.readyState===1)};
}

test('default off; Drive/Cameras reuse one set of five sockets and selecting a view never controls motion',()=>{
  const h=harness();assert.equal(h.sockets.length,0);
  assert.equal(h.elements.get('live-video-panel').parentElement.id,'drive-video-slot');
  h.toggle();assert.equal(h.live().length,5);
  h.route('#cameras');assert.equal(h.sockets.length,5);assert.equal(h.live().length,5);
  assert.equal(h.elements.get('live-video-panel').parentElement.id,'cameras-video-slot');
  h.route('#drive');const select=h.elements.get('live-primary-camera');select.value='cam-04';select.onchange();
  assert(h.elements.get('live-canvas-cam-04').closest().classes.has('primary-view'));
  assert.equal(h.sockets.length,5);assert(h.sockets.every(s=>s.url.includes('/ws/video/')&&s.sent.length===0));
});

test('pause, hidden document, unrelated route and page exit release only the intended video resources',()=>{
  const h=harness();h.toggle();h.elements.get('live-pause-cam-02').onclick();assert.equal(h.live().length,4);
  h.document.hidden=true;h.documentEvents.get('visibilitychange')();assert.equal(h.live().length,0);
  h.document.hidden=false;h.documentEvents.get('visibilitychange')();assert.equal(h.live().length,4);
  h.route('#telemetry');assert.equal(h.live().length,0);
  h.route('#drive');assert.equal(h.live().length,4);
  h.events.get('pagehide')();assert.equal(h.live().length,0);
  assert.equal(h.elements.get('live-video-toggle').textContent,'Start live video');
});

test('native decoder is retained across video workspaces and closed on hiding',async()=>{
  const h=harness();h.toggle();
  const meta=new TextEncoder().encode(JSON.stringify({connection_epoch:'one',session:'two',codec_string:'avc1.640028',width:640,height:360,keyframe:true,pts_us:1,sequence:1}));
  const buffer=new ArrayBuffer(12+meta.length+1),dv=new DataView(buffer);
  dv.setUint32(0,0x55524231);dv.setUint32(4,meta.length);dv.setUint32(8,1);new Uint8Array(buffer,12,meta.length).set(meta);
  h.sockets[0].onmessage({data:buffer});await new Promise(setImmediate);
  assert.equal(h.decoders.length,1);assert.equal(h.decoders[0].closed,false);
  h.route('#cameras');assert.equal(h.decoders[0].closed,false);
  h.route('#gps');assert.equal(h.decoders[0].closed,true);assert.equal(h.live().length,0);
});
