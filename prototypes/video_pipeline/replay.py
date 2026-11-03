"""Explicit pre-encoded test adapter. No capture, decoder, encoder or subprocess."""
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
from types import SimpleNamespace

from encoded_output import EncodedAccessUnit
from sources import SPECS
from encoding_decision import PROFILES
from video_wire import nal_info


def access_units(data):
    starts=[m.start() for m in re.finditer(b'\x00\x00\x00?\x01',data)]
    aud=[]
    for start in starts:
        end=start+3 if data[start:start+3]==b'\x00\x00\x01' else start+4
        if end>=len(data):raise ValueError('Truncated Annex B NAL')
        if data[end]&31==9:aud.append(start)
    if not aud or aud[0]!=0:raise ValueError('Fixture must begin with an AUD')
    return tuple(data[a:b] for a,b in zip(aud,aud[1:]+[len(data)]))


class FixtureCatalog:
    def __init__(self,directory):
        root=Path(directory).resolve()
        manifest=root/'manifest.json'
        if manifest.stat().st_size>65536:raise ValueError('Fixture manifest too large')
        rows=json.loads(manifest.read_text())
        if rows.get('schema_version')!=1 or not 1<=len(rows.get('fixtures',[]))<=35:
            raise ValueError('Invalid fixture manifest')
        self.fixtures={};total=0
        for row in rows['fixtures']:
            spec=next((s for s in SPECS if s.id==row.get('stream_id')),None)
            profile=next((p for p in PROFILES if p.id==row.get('profile_id')),None)
            if (not spec or not profile or profile.width>spec.width or profile.height>spec.height
                or (row.get('width'),row.get('height'),row.get('fps'))!=(profile.width,profile.height,profile.fps)
                or type(row.get('nominal_bitrate_bps')) is not int
                or not 1<=row['nominal_bitrate_bps']<=profile.minimum_bps
                or type(row.get('frames')) is not int or not 1<=row['frames']<=profile.fps*5):
                raise ValueError('Fixture does not match a supported camera/profile')
            path=(root/row['file']).resolve()
            if path.parent!=root or path.stat().st_size>16*1024*1024:
                raise ValueError('Fixture path/size rejected')
            data=path.read_bytes();total+=len(data)
            if total>64*1024*1024:raise ValueError('Fixture catalog exceeds 64 MiB')
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Fixture hash mismatch')
            frames=access_units(data)
            if len(frames)!=row['frames'] or not nal_info(frames[0])['idr']:
                raise ValueError('Fixture framing/keyframe mismatch')
            for frame in frames:
                info=nal_info(frame)
                if info['idr'] and not (info['sps'] and info['pps']):
                    raise ValueError('Fixture IDR requires SPS/PPS')
            key=(row['stream_id'],row['profile_id'])
            if key in self.fixtures:raise ValueError('Duplicate fixture')
            self.fixtures[key]=(dict(row),frames)
        self.native={'factory':'preencoded_fixture_replay','probe':{'gstreamer_version':None},'catalog':self}


class ReplayBank:
    def __init__(self,catalog):
        self.catalog=catalog;self.leases={};self.preview_busy=False
        self.sources={s.id:SimpleNamespace(spec=s,running=False,jpeg=None,clients=0,
            latest=lambda:(0,None,None)) for s in SPECS}
    @property
    def previews_enabled(self):return False
    async def start(self):pass
    async def set_sources(self,enabled):
        if type(enabled) is not bool:raise ValueError('running must be Boolean')
        for source in self.sources.values():source.running=enabled
    def state(self):
        return {'service':'urc-video-pipeline-prototype','mode':'preencoded_test',
            'sources':[dict(id=s.id,name=s.name,width=s.width,height=s.height,fps_target=s.fps,
                fps_actual=0,pixel_format='pre-encoded H.264',frame_bytes=0,raw_mb_s=0,
                color=s.color,hue=s.hue,sequence=0,running=self.sources[s.id].running,
                process_pid=None,age_ms=0 if self.sources[s.id].running else None,error=None,
                preview_sequence=0,preview_count=0,preview_age_ms=None,raw_consumers=0,
                consumer_skips=0,stream_path='') for s in SPECS],
            'previews_enabled':False,'preview_busy':False,'preview_width':480,'preview_fps_target':0}
    async def close(self):await self.set_sources(False);self.leases.clear()


class ReplayWorker:
    def __init__(self,source,settings,revision,native,hub):
        self.source=source;self.id=source.spec.id;self.settings=dict(settings);self.revision=revision
        self.catalog=native['catalog'];self.hub=hub;self.session=uuid.uuid4().hex
        self.started=time.monotonic();self.lock=threading.Lock();self.stop=threading.Event()
        self.force_idr=threading.Event();self.thread=None;self.error=None;self.jpeg=None;self.jpeg_pts=None
        self.output_frames=self.output_bytes=0;self.last_output=None;self.events=deque(maxlen=120)
    def start(self):
        self.fixture,self.frames=self.catalog.fixtures[(self.id,self.settings['profile_id'])]
        if (self.fixture['width'],self.fixture['height'],self.fixture['fps'])!=tuple(self.settings[k] for k in ('width','height','fps')):
            raise ValueError('Fixture dimensions/fps do not match the plan')
        if self.fixture['nominal_bitrate_bps']>self.settings['target_bitrate_bps']:
            raise ValueError('Fixture bitrate exceeds requested target')
        self.thread=threading.Thread(target=self.run,name='fixture-'+self.id,daemon=True);self.thread.start()
    def run(self):
        cursor=0;due=time.monotonic()
        try:
            while not self.stop.is_set() and self.source.running:
                if self.force_idr.is_set():cursor=0;self.force_idr.clear()
                data=self.frames[cursor];cursor=(cursor+1)%len(self.frames)
                now=time.monotonic();now_ns=time.monotonic_ns()
                with self.lock:
                    self.output_frames+=1;seq=self.output_frames;self.output_bytes+=len(data)
                    self.last_output=now;self.events.append((now,len(data)));revision=self.revision
                self.hub.publish(EncodedAccessUnit(self.id,self.session,seq,seq,None,
                    (seq-1)*1_000_000_000//self.fixture['fps'],now_ns,
                    self.fixture['width'],self.fixture['height'],nal_info(data)['idr'],revision,data))
                due=max(due+1/self.fixture['fps'],now)
                self.stop.wait(max(0,due-time.monotonic()))
        except Exception as exc:self.error=str(exc)
    def update(self,settings,revision):
        if settings['target_bitrate_bps']<self.fixture['nominal_bitrate_bps']:
            raise RuntimeError('Fixture cannot satisfy a lower target')
        with self.lock:self.settings=dict(settings);self.revision=revision
    def preview(self,visible):pass
    def command(self,command):
        if command=='KEYFRAME':self.force_idr.set()
    def state(self):
        now=time.monotonic()
        with self.lock:
            recent=[(t,n) for t,n in self.events if now-t<2]
            duration=min(2,max(.1,now-self.started))
            running=self.thread is not None and self.thread.is_alive() and not self.stop.is_set()
            return dict(id=self.id,name=self.source.spec.name,state='error' if self.error else 'encoding' if running and self.output_frames else 'starting',
                process_pid=None,session=self.session,backend='preencoded_fixture_replay',hardware_confirmed=False,
                requested=dict(self.settings),requested_plan_revision=self.revision,
                accepted_bitrate_bps=getattr(self,'fixture',{}).get('nominal_bitrate_bps'),
                accepted_plan_revision=self.revision,observed_width=self.settings['width'],observed_height=self.settings['height'],
                output_frames=self.output_frames,output_bytes=self.output_bytes,actual_bitrate_bps=sum(n for _,n in recent)*8/duration,
                actual_fps=(len(recent)-1)/(recent[-1][0]-recent[0][0]) if len(recent)>1 else 0,
                output_age_s=now-self.last_output if self.last_output else None,preview_count=0,
                preview_enabled=False,error=self.error,skipped_source_frames=0,
                input_adapter='Pre-encoded fixture; no raw camera or hardware encoding',scaler='none')
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=1)
        if self.thread and self.thread.is_alive():raise RuntimeError('Replay thread did not stop')
        self.hub.invalidate(self.id)
