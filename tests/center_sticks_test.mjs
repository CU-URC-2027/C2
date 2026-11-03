import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {readController} from '../web/controller.mjs';
import {initFileLogging} from '../web/file-logging.mjs';
import {initVideoNetwork} from '../web/video-network.mjs';

// Run the actual event bindings/rendering against a DOM/socket component harness.
// No physical gamepad, network chassis, browser codec or OS focus is simulated here.
function harness() {
  const elements=[],byId=new Map(),events=new Map(),intervals=[],sockets=[];
  class Element {
    constructor(tag,attrs='') {
      this.tag=tag;this.dataset={};this.style={};this.handlers=new Map();this.value='';this.textContent='';
      this.classes=new Set();this.disabled=/\bdisabled\b/.test(attrs);this.scrollTop=this.scrollLeft=0;
      for(const [,key,value] of attrs.matchAll(/([\w-]+)="([^"]*)"/g)){
        if(key.startsWith('data-'))this.dataset[key.slice(5)]=value;
        if(key==='id'){this.id=value;byId.set(value,this);}
        if(key==='value')this.value=value;
        if(key==='class')this.classes=new Set(value.split(' '));
      }
      this.classList={toggle:(key,on)=>on?this.classes.add(key):this.classes.delete(key),add:key=>this.classes.add(key),remove:key=>this.classes.delete(key)};
      elements.push(this);
    }
    addEventListener(name,fn){const list=this.handlers.get(name)||[];list.push(fn);this.handlers.set(name,list);}
    emit(name,details={}){const e={button:0,pointerId:1,clientX:10,clientY:10,target:this,preventDefault(){},...details};for(const fn of this.handlers.get(name)||[])fn(e);this['on'+name]?.(e);}
    matches(){return false;}
    insertAdjacentHTML(_,html){parse(html);}
    setAttribute(key,value){this[key]=value;}
    replaceChildren(){} setPointerCapture(id){this.pointer=id;}
    hasPointerCapture(id){return this.pointer===id;}
    releasePointerCapture(){this.pointer=null;}
    getBoundingClientRect(){return {left:0,top:0,right:100,bottom:40,width:0,height:0};}
    set innerHTML(value){this.html=value;}
  }
  function parse(html){for(const [,tag,attrs] of html.matchAll(/<(\w+)([^>]*)>/g))new Element(tag,attrs);}
  parse(readFileSync(new URL('../web/index.html',import.meta.url),'utf8'));
  byId.get('controller-stick').value='left';
  const select=selector=>elements.filter(el=>selector.split(',').some(s=>{
    s=s.trim();if(s==='[data-action]')return !!el.dataset.action;if(s==='[data-jog]')return !!el.dataset.jog;
    if(s==='[data-route]')return !!el.dataset.route;if(s.startsWith('.'))return el.classes.has(s.slice(1));
    const a=s.match(/^\[data-action="([^"]+)"\]$/);return a&&el.dataset.action===a[1];
  }));
  const document={hidden:false,hasFocus:()=>true,activeElement:null,getElementById:id=>byId.get(id),
    querySelectorAll:select,addEventListener:(name,fn)=>events.set('document:'+name,fn)};
  class Socket {
    static OPEN=1;
    constructor(){this.readyState=1;this.sent=[];sockets.push(this);}
    send(raw){const msg=JSON.parse(raw);this.sent.push(msg);if(msg.request_id)queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'ack',request_id:msg.request_id,ok:true})}));}
  }
  const location={hash:'#drive',protocol:'http:',host:'127.0.0.1:8870'};
  let pad=null;
  vm.runInNewContext(readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,''),{
    readController,initFileLogging:(send,notice)=>initFileLogging(send,notice,document),initVideoNetwork:(send,notice)=>initVideoNetwork(send,notice,document),initPriorities(){},renderPriorities(){},document,location,WebSocket:Socket,
    navigator:{getGamepads:()=>[pad]},Option:class{},fetch:async()=>({json:async()=>[]}),
    addEventListener:(name,fn)=>events.set(name,fn),setInterval:fn=>intervals.push(fn),
    setTimeout(){return 1;},clearTimeout(){},performance,devicePixelRatio:1,
  });
  const socket=sockets[0];socket.onmessage({data:JSON.stringify({type:'hello',client:'a'})});
  let state={owner:'a',clients:1,uptime_s:0,mode:'model',input_mode:'virtual',input:{deadman:false},
    control:{enabled:false,stop_latched:false,left:0,right:0,reason:'Disarmed',arm_preview:{}},
    drive_readiness:{enable_allowed:true,enable_blockers:[],reset_allowed:false,reset_blockers:[],enable_pending:false},
    rover:{connected:false},gps:{mode:'disconnected',comparison:{label:'No comparison',metrics:{},pairs:[]}},
    file_logging:{enabled:false,written_records:0,queued_records:0,dropped_records:0},events:[],pose:[0,0,0],log_rows:0,history:[],cameras:[],speed_limit:.25,video_priorities:{}};
  const update=patch=>{state={...state,...patch};socket.onmessage({data:JSON.stringify({type:'state',state})});};
  update({});
  return {byId,events,socket,location,update,elements,setPad:value=>{pad=value;},
    input:()=>intervals[1](),lastInput:()=>socket.sent.filter(s=>s.action==='input').at(-1)?.data,
    key:(name,code,repeat=false)=>events.get(name)({code,repeat,target:byId.get('joystick'),preventDefault(){}})};
}

test('Center sticks zeros sliders/vector and releases jog/keyboard/pointer holds without enabling',()=>{
  const h=harness();h.byId.get('throttle-slider').value='.6';h.byId.get('throttle-slider').emit('input');
  h.key('keydown','Space');h.input();assert.equal(h.lastInput().deadman,true);
  h.byId.get('deadman').emit('pointerdown');
  h.elements.find(e=>e.dataset.jog==='1').emit('pointerdown');assert.equal(h.lastInput().jog,1);
  h.byId.get('center-sticks').onclick();assert.equal(h.lastInput().throttle,0);assert.equal(h.lastInput().deadman,false);
  assert.equal(h.byId.get('throttle-slider-value').textContent,'0.00');assert.equal(h.lastInput().jog,0);
  h.key('keydown','Space',true);h.input();assert.equal(h.lastInput().deadman,false);
  h.key('keyup','Space');h.key('keydown','Space');h.input();assert.equal(h.lastInput().deadman,true);
  assert(!h.socket.sent.some(s=>s.action==='enable'));
});

test('Center sticks is unavailable for a physical gamepad and view-only sessions',()=>{
  const h=harness();h.update({input_mode:'gamepad'});assert(h.byId.get('center-sticks').disabled);
  const count=h.socket.sent.length;h.byId.get('center-sticks').onclick();assert.equal(h.socket.sent.length,count);
  h.update({input_mode:'virtual',owner:'other'});assert(h.byId.get('center-sticks').disabled);
});
