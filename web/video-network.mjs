export function initVideoNetwork(send,notice,doc=document){
  const $=id=>doc.getElementById(id);
  let edited=false;
  for(const id of ['video-budget-mbps','video-budget-share'])$(id).oninput=()=>{edited=true;};
  $('video-budget-apply').onclick=async()=>{
    try{
      await send('video_link_budget',{
        available_bps:Math.round(Number($('video-budget-mbps').value)*1e6),
        video_share_percent:Number($('video-budget-share').value)
      });
      edited=false;
    }catch(e){notice(e.message,true);}
  };
  return (value,mine)=>{
    const active=value?.transport==='ros2_tcp';$('video-network-panel').hidden=!active;
    if(!active)return;
    if(!mine)edited=false;
    for(const id of ['video-budget-apply','video-budget-mbps','video-budget-share'])$(id).disabled=!mine;
    if(!edited){
      $('video-budget-mbps').value=value.link_budget.available_bps/1e6;
      $('video-budget-share').value=value.link_budget.video_share_percent;
    }
    const h=value.remote_health,p=value.remote_plan;
    $('video-network-status').textContent=h?
      h.execution_mode+' · '+h.connected_streams+'/5 TCP feeds · '+(value.receiver_fresh?'fresh rover health':'stale rover health')+(h.budget_fresh?'':' · stale budget: output inhibited'):
      'Waiting for the rover ROS video process';
    $('video-network-plan').textContent=p?JSON.stringify(p,null,2):'Waiting for an encoding plan';
  };
}
