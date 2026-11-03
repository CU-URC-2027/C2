import assert from 'node:assert/strict';
import test from 'node:test';
import {initFileLogging} from '../web/file-logging.mjs';

function harness(){
  const ids=['log-directory','file-logging-toggle','file-logging-status','file-logging-path','file-logging-error'];
  const elements=new Map(ids.map(id=>[id,{value:'',handlers:{},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.handlers[k]=f;}}]));
  const sent=[],notices=[];
  const render=initFileLogging(async(action,data)=>sent.push({action,data}),(...args)=>notices.push(args),{getElementById:id=>elements.get(id)});
  const state={enabled:false,written_records:0,queued_records:0,dropped_records:0};
  const folder=elements.get('log-directory'),toggle=elements.get('file-logging-toggle');
  return {elements,sent,notices,folder,toggle,render:patch=>render({...state,...patch},true)};
}

test('logging stays off until an explicit toggle with a user-selected directory',async()=>{
  const h=harness();h.render({});assert(h.toggle.disabled);assert.equal(h.sent.length,0);
  h.folder.value='/a folder/chosen by user';h.folder.handlers.input();assert(!h.toggle.disabled);
  await h.toggle.handlers.click();
  assert.deepEqual(h.sent,[{action:'file_logging',data:{enabled:true,directory:'/a folder/chosen by user'}}]);
  h.render({configuring:true});assert(h.toggle.disabled);assert(h.folder.disabled);
  h.render({enabled:true,directory:h.folder.value,path:'/a folder/chosen by user/c2-diagnostics-test.jsonl',written_records:42});
  assert.equal(h.toggle['aria-checked'],'true');assert(h.folder.disabled);
  assert.match(h.elements.get('file-logging-path').textContent,/c2-diagnostics-test.jsonl/);
  await h.toggle.handlers.click();assert.equal(h.sent.at(-1).data.enabled,false);
});

test('write errors and dropped records remain visible and stopped paths are editable',()=>{
  const h=harness();h.render({directory:'/old',path:'/old/previous.jsonl',error:'disk full',dropped_records:5});
  assert.equal(h.toggle['aria-checked'],'false');assert.match(h.elements.get('file-logging-error').textContent,/disk full/);
  assert.match(h.elements.get('file-logging-status').textContent,/5 dropped/);
  h.folder.value='/new';h.render({directory:'/old'});assert.equal(h.folder.value,'/new');
  assert.equal(h.sent.length,0); // State/rendering never starts logging implicitly.
});
