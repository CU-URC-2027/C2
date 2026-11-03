export function initRovers(send,notice,doc=document){
  const $=id=>doc.getElementById(id);
  let mine=false,armed=false,scan={candidates:[]},profiles=[],signatures={};
  function options(id,rows,key,label){
    const signature=JSON.stringify(rows);if(signatures[id]===signature)return;signatures[id]=signature;
    const select=$(id),previous=select.value;
    const make=(text,value)=>{const o=doc.createElement('option');o.textContent=text;o.value=value;return o;};
    select.replaceChildren(make('Select a rover…',''),...rows.map(row=>make(label(row),key(row))));
    if(rows.some(row=>key(row)===previous))select.value=previous;
  }
  const foundKey=r=>`${r.device_id}@${r.host}:${r.control_port}`;
  function controls(){
    $('find-rovers').disabled=!mine||armed||scan.scanning;
    const found=scan.candidates.find(r=>foundKey(r)===$('found-rovers').value);
    $('connect-found').disabled=!mine||armed||scan.scanning||!found||found.busy;
    $('connect-saved').disabled=!mine||armed||!profiles.some(r=>r.id===$('saved-rovers').value);
  }
  $('found-rovers').addEventListener('change',controls);$('saved-rovers').addEventListener('change',controls);
  $('find-rovers').addEventListener('click',()=>send('find_rovers',{host:$('discovery-host').value.trim(),port:Number($('discovery-port').value),local_ipv4:$('discovery-bind').value.trim()||'0.0.0.0'}).catch(e=>notice(e.message,true)));
  async function connect(action,id){try{await send('disarm');await send(action,{id});doc.defaultView.location.hash='drive';}catch(e){notice(e.message,true);}}
  $('connect-found').addEventListener('click',()=>connect('connect_discovered',$('found-rovers').value));
  $('connect-saved').addEventListener('click',()=>connect('connect_saved',$('saved-rovers').value));
  $('save-rover').addEventListener('click',()=>send('save_rover',{name:$('rover-name').value.trim()}).catch(e=>notice(e.message,true)));
  return function render(s,owns){
    mine=owns;armed=s.control.enabled||s.rover.state?.enabled||s.rover.pending_enable||s.rover.disarm_pending;
    scan=s.rover_discovery||{candidates:[]};profiles=s.saved_rovers?.profiles||[];
    options('found-rovers',scan.candidates,foundKey,r=>`${r.device_id} · ${r.host}:${r.control_port}${r.busy?' · BUSY':''} · ${r.build}`);
    options('saved-rovers',profiles,r=>r.id,r=>`${r.name} · ${r.host}:${r.port}${r.device_id?' · identity checked':' · legacy address only'}`);
    $('discovery-status').textContent=scan.scanning?'Looking for rovers…':scan.error||`${scan.candidates.length} compatible rover(s) found. ${scan.rejected_replies||0} unrelated replies ignored. Armed hardware may not reply; manual UDP remains available.`;
    $('profiles-status').textContent=s.saved_rovers?.error||(s.saved_rovers?.saving?'Saving profile…':'Saved profiles never connect or enable automatically.');
    $('save-rover').disabled=!mine||!s.rover.ready||s.saved_rovers?.saving;
    controls();
  };
}
