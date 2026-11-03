import {test} from 'node:test';
import assert from 'node:assert/strict';
import {initVideoNetwork} from '../web/video-network.mjs';

test('video budget keeps both edited fields across state ticks until explicit publish',async()=>{
  const elements=new Map();
  const doc={getElementById:id=>{
    if(!elements.has(id))elements.set(id,{value:'',disabled:false});
    return elements.get(id);
  }};
  const $=doc.getElementById,sent=[];
  const render=initVideoNetwork(async(...args)=>sent.push(args),()=>assert.fail('unexpected notice'),doc);
  const state={transport:'ros2_tcp',link_budget:{available_bps:20e6,video_share_percent:70}};
  render(state,true);
  $('video-budget-mbps').value='8';$('video-budget-mbps').oninput();
  render(state,true);
  $('video-budget-share').value='50';$('video-budget-share').oninput();
  render(state,true);
  assert.equal($('video-budget-mbps').value,'8');
  assert.equal($('video-budget-share').value,'50');
  await $('video-budget-apply').onclick();
  assert.deepEqual(sent,[['video_link_budget',{available_bps:8e6,video_share_percent:50}]]);
  render({...state,link_budget:{available_bps:8e6,video_share_percent:50}},true);
  assert.equal($('video-budget-mbps').value,8);
  $('video-budget-mbps').value='99';$('video-budget-mbps').oninput();
  render(state,false);
  assert.equal($('video-budget-mbps').disabled,true);
  assert.equal($('video-budget-mbps').value,20);
});
