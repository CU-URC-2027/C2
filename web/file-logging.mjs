export function initFileLogging(send, notice, doc=document) {
  const folder=doc.getElementById('log-directory'),toggle=doc.getElementById('file-logging-toggle');
  const status=doc.getElementById('file-logging-status'),path=doc.getElementById('file-logging-path'),error=doc.getElementById('file-logging-error');
  let current={enabled:false},mine=false,requesting=false;
  function controls(){
    const busy=current.configuring||current.stopping;
    toggle.disabled=!mine||requesting||busy||(!current.enabled&&!folder.value.trim());
    folder.disabled=!mine||current.enabled||busy;
  }
  folder.addEventListener('input',controls);
  toggle.addEventListener('click',async()=>{
    if(toggle.disabled)return;
    requesting=true;controls();
    try{await send('file_logging',{enabled:!current.enabled,directory:folder.value.trim()});}
    catch(e){notice(e.message,true);}
    finally{requesting=false;} // Next backend state confirms success/error and reenables.
  });
  return function render(log,ownsControls){
    current=log;mine=ownsControls;
    if(log.directory&&(log.enabled||(!folder.value&&doc.activeElement!==folder)))folder.value=log.directory;
    toggle.textContent=log.configuring||log.stopping?'Updating file logging…':log.enabled?'Stop file logging':'Enable file logging';
    toggle.setAttribute('aria-checked',String(log.enabled));
    status.textContent=`${log.enabled?'LOGGING ON':log.configuring||log.stopping?'UPDATING':'LOGGING OFF'} · ${log.written_records} records · ${log.queued_records} queued · ${log.dropped_records} dropped`;
    path.textContent=log.path||'No file created. Choose a folder and enable logging before connecting.';
    error.textContent=log.error||'';
    controls();
  };
}
