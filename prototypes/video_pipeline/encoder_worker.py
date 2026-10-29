"""Python ownership/lifecycle and measurements for one native hardware session."""
from collections import deque
import json
import math
import os
import select
import struct
import subprocess
import threading
import time
import uuid

from encoded_output import EncodedAccessUnit


class EncoderWorker:
    def __init__(self, source, settings, revision, native, hub):
        self.source,self.settings,self.revision,self.native,self.hub=source,dict(settings),revision,native,hub
        self.id=source.spec.id;self.session=uuid.uuid4().hex
        self.process=None;self.control_fd=None;self.threads=[];self.stop=threading.Event()
        self.lock=threading.Lock();self.control_lock=threading.Lock()
        self.origin_ns=time.monotonic_ns();self.started=time.monotonic()
        self.pending={};self.events=deque(maxlen=180);self.latencies=deque(maxlen=180)
        self.output_frames=self.output_bytes=self.input_frames=self.skipped_source_frames=0
        self.accepted_bitrate_bps=self.accepted_plan_revision=None
        self.observed_width=self.observed_height=None
        self.error=self.preview_error=None;self.ready=False;self.verified_hardware=False
        self.preview_wanted=False;self.preview_decoder=None;self.jpeg=None;self.jpeg_pts=None;self.preview_count=0
        self.last_output=None;self.logs=deque(maxlen=8)

    def start(self):
        read_fd,self.control_fd=os.pipe()
        s=self.settings
        args=[self.native['binary'],self.native['factory'],str(self.source.spec.width),str(self.source.spec.height),
              str(s['width']),str(s['height']),str(s['fps']),str(s['target_bitrate_bps']),str(read_fd),str(self.revision)]
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                pass_fds=(read_fd,),bufsize=0,env=self.native['environment'])
        finally:os.close(read_fd)
        os.set_blocking(self.process.stdin.fileno(),False)
        os.set_blocking(self.control_fd,False)
        for name,function in (('input',self.send_frames),('output',self.read_output),('logs',self.read_logs)):
            t=threading.Thread(target=function,daemon=True,name=f'encoder-{self.id}-{name}');t.start();self.threads.append(t)
        self.command(f"RATE {s['target_bitrate_bps']} {self.revision}")

    def command(self, line):
        with self.control_lock:
            if self.stop.is_set() or self.control_fd is None:return False
            try:os.write(self.control_fd,(line+'\n').encode());return True
            except (OSError,BlockingIOError):return False

    def update(self, settings, revision):
        changed=settings['target_bitrate_bps']!=self.settings['target_bitrate_bps'] or revision!=self.revision
        if changed:
            if not self.command(f"RATE {settings['target_bitrate_bps']} {revision}"):
                raise RuntimeError('Encoder control pipe is unavailable')
            with self.lock:self.settings=dict(settings);self.revision=revision

    def preview(self, visible):
        if visible!=self.preview_wanted:
            if self.command(f'PREVIEW {int(visible)}'):
                self.preview_wanted=visible
                if not visible:
                    with self.lock:self.jpeg=None;self.jpeg_pts=None;self.preview_decoder=None

    def send_frames(self):
        previous=-1;stride=max(1,round(self.source.spec.fps/self.settings['fps']))
        try:
            while not self.stop.is_set() and self.process.poll() is None:
                seq,frame,received=self.source.latest()
                if frame is None or received is None or time.monotonic()-received>1 or seq==previous or (previous>=0 and seq-previous<stride):
                    self.stop.wait(.002);continue
                pts_ns=max(0,int(received*1e9)-self.origin_ns)
                with self.lock:
                    self.pending[pts_ns]=(seq,int(received*1e9),time.monotonic_ns(),self.revision)
                    while len(self.pending)>128:self.pending.pop(next(iter(self.pending)))
                header=struct.pack('>QQI',pts_ns,seq,len(frame))
                self.write_input(header);self.write_input(frame)
                with self.lock:
                    self.input_frames+=1
                    if previous>=0:self.skipped_source_frames+=max(0,seq-previous-stride)
                previous=seq
        except (OSError,ValueError,BrokenPipeError):
            if not self.stop.is_set():self.error='Native encoder input closed'

    def write_input(self, data):
        view=memoryview(data)
        while view and not self.stop.is_set():
            _,writable,_=select.select([],[self.process.stdin],[],.1)
            if not writable:continue
            try:written=os.write(self.process.stdin.fileno(),view[:65536])
            except BlockingIOError:continue
            if not written:raise BrokenPipeError()
            view=view[written:]

    def read_exact(self, count):
        result=bytearray()
        while len(result)<count:
            part=self.process.stdout.read(count-len(result))
            if not part:raise EOFError()
            result.extend(part)
        return bytes(result)

    def read_output(self):
        try:
            while True:
                meta_len,payload_len=struct.unpack('>II',self.read_exact(8))
                if not 1<=meta_len<=8192 or payload_len>16*1024*1024:raise ValueError('Invalid native record size')
                meta=json.loads(self.read_exact(meta_len));payload=self.read_exact(payload_len)
                if self.stop.is_set():continue
                self.handle(meta,payload)
        except EOFError:
            if not self.stop.is_set() and not self.error:self.error='Hardware worker exited before being stopped'
        except (ValueError,KeyError,TypeError,OSError) as exc:
            if not self.stop.is_set():self.error=str(exc)

    def handle(self, meta, payload):
        kind=meta.get('type');now=time.monotonic();now_ns=time.monotonic_ns()
        with self.lock:
            if kind=='ready':self.ready=True
            elif kind=='configured':
                self.accepted_bitrate_bps=meta['bitrate_bps'];self.accepted_plan_revision=meta['configuration_revision']
            elif kind=='error':self.error=meta['message']
            elif kind=='preview_error':self.preview_error=meta['message']
            elif kind=='preview_state':self.preview_decoder=None if meta['message']=='off' else meta['message']
            elif kind=='preview':
                if self.preview_wanted:self.jpeg=payload;self.jpeg_pts=meta['pts_ns'];self.preview_count+=1
            elif kind=='encoded':
                pts=meta['pts_ns'];receipt=self.pending.pop(pts,None)
                self.observed_width,self.observed_height=meta['width'],meta['height']
                if (self.observed_width,self.observed_height)!=(self.settings['width'],self.settings['height']):
                    self.error='Encoded SPS dimensions differ from requested output';return
                self.verified_hardware=True;self.output_frames+=1;self.output_bytes+=len(payload);self.last_output=now
                self.events.append((now,len(payload)))
                if receipt:self.latencies.append((now_ns-receipt[2])/1e6)
                unit=EncodedAccessUnit(self.id,self.session,self.output_frames,receipt[0] if receipt else None,
                    receipt[1] if receipt else None,pts,now_ns,self.observed_width,self.observed_height,
                    meta['keyframe'],receipt[3] if receipt else None,payload)
                self.hub.publish(unit)

    def read_logs(self):
        try:
            for raw in self.process.stderr:
                line=raw.decode(errors='replace').strip()
                if line:self.logs.append(line[:400])
        except (ValueError,OSError):pass

    def state(self):
        now=time.monotonic()
        with self.lock:
            recent=[e for e in self.events if now-e[0]<2]
            duration=min(2,max(.1,now-self.started))
            fps=(len(recent)-1)/(recent[-1][0]-recent[0][0]) if len(recent)>1 and recent[-1][0]>recent[0][0] else 0.0
            lat=sorted(self.latencies)
            running=self.process is not None and self.process.poll() is None and not self.stop.is_set()
            status='error' if self.error else 'disabled' if not running else 'encoding' if self.verified_hardware else 'starting'
            return {'id':self.id,'name':self.source.spec.name,'state':status,'process_pid':self.process.pid if running else None,
                'session':self.session,'backend':self.native['factory'],'hardware_confirmed':self.verified_hardware,
                'requested':dict(self.settings),'requested_plan_revision':self.revision,
                'accepted_bitrate_bps':self.accepted_bitrate_bps,'accepted_plan_revision':self.accepted_plan_revision,
                'observed_width':self.observed_width,'observed_height':self.observed_height,
                'output_frames':self.output_frames,'output_bytes':self.output_bytes,'actual_bitrate_bps':sum(e[1] for e in recent)*8/duration,
                'actual_fps':fps if running and self.last_output and now-self.last_output<1 else 0,
                'submit_to_output_p50_ms':lat[len(lat)//2] if lat else None,
                'submit_to_output_p95_ms':lat[min(len(lat)-1,math.ceil(len(lat)*.95)-1)] if lat else None,
                'output_age_s':now-self.last_output if self.last_output else None,
                'input_frames':self.input_frames,'skipped_source_frames':self.skipped_source_frames,
                'pending_timestamp_records':len(self.pending),'preview_enabled':self.preview_wanted,
                'preview_decoder':self.preview_decoder,'preview_count':self.preview_count,
                'error':self.error,'preview_error':self.preview_error,'logs':list(self.logs),
                'scaler':'GStreamer videoscale (CPU)','input_adapter':'Immutable NV12 buffer → pipe → native appsrc; copies present'}

    def close(self):
        if self.stop.is_set() and self.process is None:return
        # Send QUIT before setting stop, then invalidate outputs before joining readers.
        self.command('QUIT');self.stop.set();self.hub.invalidate(self.id)
        if self.process:
            if self.threads:self.threads[0].join(timeout=.5)
            self.process.stdin.close()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
            for thread in self.threads:thread.join(timeout=2)
            for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
                if stream:stream.close()
        with self.control_lock:
            if self.control_fd is not None:os.close(self.control_fd);self.control_fd=None
        with self.lock:self.jpeg=None;self.preview_decoder=None;self.preview_wanted=False
        self.hub.invalidate(self.id)
