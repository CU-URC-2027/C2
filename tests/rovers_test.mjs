import assert from 'node:assert/strict';
import test from 'node:test';
import {initRovers} from '../web/rovers.mjs';

function harness(){
  const ids=['find-rovers','found-rovers','connect-found','saved-rovers','connect-saved','save-rover','rover-name','discovery-host','discovery-port','discovery-bind','discovery-status','profiles-status'];
  const elements=new Map(ids.map(id=>[id,{value:'',handlers:{},addEventListener(name,f){this.handlers[name]=f;},replaceChildren(...children){this.options=children;this.value=children[0]?.value||'';}}]));
  const sent=[],doc={getElementById:id=>elements.get(id),createElement:()=>({}),defaultView:{location:{hash:'#connections'}}};
  const render=initRovers(async(action,data)=>sent.push({action,data}),()=>{},doc);
  const state={control:{enabled:false},rover:{ready:true,state:null},rover_discovery:{scanning:false,candidates:[]},saved_rovers:{profiles:[]}};
  return {elements,sent,doc,render:(patch={})=>render({...state,...patch},true)};
}

test('render never discovers, claims or enables; a scan is explicit and uses the selected network',async()=>{
  const h=harness();h.render();assert.equal(h.sent.length,0);
  for(const[id,value]of[['discovery-host','127.0.0.1'],['discovery-port','4210'],['discovery-bind','0.0.0.0']])h.elements.get(id).value=value;
  await h.elements.get('find-rovers').handlers.click();
  assert.deepEqual(h.sent,[{action:'find_rovers',data:{host:'127.0.0.1',port:4210,local_ipv4:'0.0.0.0'}}]);
});

test('selecting a discovered identity connects disarmed and returns to Drive without Enable',async()=>{
  const h=harness(),row={device_id:'rover-test-01',host:'127.0.0.1',control_port:4210,build:'test',busy:false};
  h.render({rover_discovery:{candidates:[row]}});
  const select=h.elements.get('found-rovers');select.value='rover-test-01@127.0.0.1:4210';select.handlers.change();
  assert(!h.elements.get('connect-found').disabled);
  await h.elements.get('connect-found').handlers.click();
  assert.deepEqual(h.sent.map(r=>r.action),['disarm','connect_discovered']);
  assert.equal(h.doc.defaultView.location.hash,'drive');
});

test('busy, active and in-progress scans block selection; saved profiles never auto-connect',()=>{
  const h=harness(),row={device_id:'rover-test-01',host:'127.0.0.1',control_port:4210,busy:true};
  h.render({rover_discovery:{candidates:[row]},saved_rovers:{profiles:[{id:'saved-01',name:'Test',host:'127.0.0.1',port:4210}]}});
  h.elements.get('found-rovers').value='rover-test-01@127.0.0.1:4210';h.elements.get('found-rovers').handlers.change();
  assert(h.elements.get('connect-found').disabled);assert.equal(h.sent.length,0);
  h.render({control:{enabled:true}});assert(h.elements.get('find-rovers').disabled);
  h.render({rover_discovery:{scanning:true,candidates:[]}});assert(h.elements.get('find-rovers').disabled);
});
