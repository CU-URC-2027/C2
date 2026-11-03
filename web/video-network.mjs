export function initVideoNetwork(send,notice,doc=document){
  const $=id=>doc.getElementById(id);
  $('video-budget-apply').onclick=()=>send('video_link_budget',{
    available_bps:Math.round(Number($('video-budget-mbps').value)*1e6),
    video_share_percent:Number($('video-budget-share').value)
  }).catch(e=>notice(e.message,true));
  return (value,mine)=>{
    const active=value?.transport==='ros2_tcp';$('video-network-panel').hidden=!active;
    if(!active)return;
    for(const id of ['video-budget-apply','video-budget-mbps','video-budget-share'])$(id).disabled=!mine;
    if(doc.activeElement!==$('video-budget-mbps'))$('video-budget-mbps').value=value.link_budget.available_bps/1e6;
    if(doc.activeElement!==$('video-budget-share'))$('video-budget-share').value=value.link_budget.video_share_percent;
    const h=value.remote_health,p=value.remote_plan;
    $('video-network-status').textContent=h?
      h.execution_mode+' · '+h.connected_streams+'/5 TCP feeds · '+(value.receiver_fresh?'fresh rover health':'stale rover health')+(h.budget_fresh?'':' · stale budget: output inhibited'):
      'Waiting for the rover ROS video process';
    $('video-network-plan').textContent=p?JSON.stringify(p,null,2):'Waiting for an encoding plan';
  };
}
