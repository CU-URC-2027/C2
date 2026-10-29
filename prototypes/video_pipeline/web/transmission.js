const $=id=>document.getElementById(id);
const rate=n=>`${((n||0)/1e6).toFixed(3)} Mb/s`;
let state=null;
export function initTransmission(toast,layout){
  const post=async(path,body)=>{try{const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}),s=await r.json();if(!r.ok)throw new Error(s.detail||'Transmission operation failed');renderTransmission(s);}catch(error){toast(error.message);}};
  $('toggle-transmission').onclick=()=>post('/api/transmission/config',{enabled:!state?.enabled});
  $('transmission-target').onclick=()=>post('/api/transmission/config',{host:$('transmission-host').value,port:Number($('transmission-port').value)});
  $('transmission-reconnect').onclick=()=>post('/api/transmission/reconnect');
  $('transmission-inspect').onclick=()=>{const el=$('transmission-json');el.hidden=!el.hidden;$('transmission-inspect').textContent=el.hidden?'Inspect transmission state':'Hide transmission state';layout();};
}
export function renderTransmission(s){if(!s)return;state=s;
  $('transmission-process').textContent=`Lab PID ${s.process_pid} · real TCP sockets`;
  $('transmission-status').textContent=!s.enabled?'OFF':s.connected_streams?`${s.connected_streams} CONNECTED`:'WAITING / RECONNECTING';
  $('toggle-transmission').textContent=s.enabled?'Disable transmission':'Enable transmission';
  if(document.activeElement!==$('transmission-host'))$('transmission-host').value=s.destination.host;
  if(document.activeElement!==$('transmission-port'))$('transmission-port').value=s.destination.port;
  $('transmission-rate').textContent=rate(s.wire_bitrate_bps);
  $('transmission-capacity').textContent=rate(s.shared_video_capacity_bps);
  $('transmission-latency').textContent=`${s.simulated_one_way_delay_ms} ms`;
  $('transmission-error').textContent=s.error||'One shared video allowance · paced encoded bytes, including record headers';
  const box=$('transmission-cameras');
  for(const r of s.cameras){let row=$(`transmission-${r.id}`);if(!row){row=document.createElement('div');row.id=`transmission-${r.id}`;row.className='transmission-camera';box.append(row);}
    const rx=r.connected&&r.ack_age_s!=null&&r.ack_age_s<2?(r.receiver||{}):{};row.textContent=`${r.name} · ${r.connected?'TCP CONNECTED':r.active?'RECONNECTING':'INACTIVE'}\nTX ${rate(r.sent_bitrate_bps)} · ${r.sent_frames||0} frames · queue ${r.queue_frames||0} / ${((r.queue_bytes||0)/1024).toFixed(1)} KiB · ${(r.oldest_queue_age_ms||0).toFixed(0)} ms\nC2 PID ${rx.receiver_pid||'—'} · RX ${(rx.receive_fps||0).toFixed(1)} / browser ${(rx.render_fps||0).toFixed(1)} fps · ACK ${r.ack_sequence||'—'} · reconnects ${r.reconnects||0} · dropped ${r.dropped_frames||0}${r.active&&r.error?'\n'+r.error:''}`;
  }
  if(!$('transmission-json').hidden)$('transmission-json').textContent=JSON.stringify(s,null,2);
  $('wire-encoder-transmission').classList.toggle('offline',!s.connected_streams);$('wire-transmission-c2').classList.toggle('offline',!s.connected_streams);
}
