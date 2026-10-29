"""Local TCP/IP sender. Allocation remains in EncodingDecision; no re-encoding."""
import asyncio
from collections import deque
import ipaddress
import json
import os
import socket
import time

from video_wire import STREAM_IDS,pack


class SharedPacer:
    """One token bucket for all five flows; grant waiting chunks by C2 rank."""
    def __init__(self,rate):
        self.rate=rate;self.tokens=0.;self.last=time.monotonic();self.waiters=[];self.task=None
    async def start(self):self.task=asyncio.create_task(self.run())
    async def acquire(self,size,priority):
        future=asyncio.get_running_loop().create_future()
        item=(priority,time.monotonic(),size,future);self.waiters.append(item)
        try:await future
        finally:
            if item in self.waiters:self.waiters.remove(item)
    async def run(self):
        while True:
            now=time.monotonic();rate=max(0,self.rate())/8
            self.tokens=min(max(8192,rate*.05),self.tokens+(now-self.last)*rate);self.last=now
            if rate==0:self.tokens=0
            for item in sorted(self.waiters,key=lambda x:x[:2]):
                priority,at,size,future=item
                if future.done():continue
                if size>self.tokens:break
                self.tokens-=size;future.set_result(None)
            await asyncio.sleep(.001 if self.waiters else .02)
    async def close(self):
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        for *_,f in self.waiters:
            if not f.done():f.cancel()
        self.waiters.clear()


class CameraSender:
    MAX_FRAMES=8
    MAX_BYTES=4*1024*1024
    MAX_AGE_S=.5
    def __init__(self,owner,id,epoch):
        self.owner,self.id,self.epoch=owner,id,epoch
        self.subscription=owner.encoder.hub.subscribe(id,capacity=8)
        self.queue=deque();self.queue_bytes=0;self.waiting=True;self.last_sequence=None
        self.writer=None;self.task=None;self.ack_task=None;self.connected=False;self.stopping=False
        self.sent_frames=self.sent_bytes=self.dropped=self.connections=self.reconnects=0
        self.last_ack=self.last_sent=self.ack_seq=self.rtt_ms=None;self.receiver={};self.error=None
        self.events=deque(maxlen=600);self.inflight_bytes=0;self.first_attempt=True
    def priority(self):
        order=self.owner.order
        return order.index(self.id) if self.id in order else 5
    def reset_chain(self):
        self.dropped+=len(self.queue);self.queue.clear();self.queue_bytes=0;self.waiting=True
        self.owner.encoder.request_keyframe(self.id)
    def ingest(self):
        for unit in self.subscription.drain():
            if unit.encoder_session!=self.epoch:continue
            if len(unit.data)>self.MAX_BYTES:
                self.reset_chain();self.dropped+=1;continue
            gap=self.last_sequence is not None and unit.sequence!=self.last_sequence+1
            self.last_sequence=unit.sequence
            if gap or len(self.queue)>=self.MAX_FRAMES or self.queue_bytes+len(unit.data)>self.MAX_BYTES:self.reset_chain()
            if self.waiting and not unit.keyframe:self.dropped+=1;continue
            if unit.keyframe:self.waiting=False
            self.queue.append(unit);self.queue_bytes+=len(unit.data)
    async def acknowledgements(self,reader):
        while True:
            raw=await reader.readline()
            if not raw or len(raw)>8192:raise ConnectionError('C2 acknowledgement stream closed')
            row=json.loads(raw)
            if row.get('type')!='ack' or row.get('stream_id')!=self.id:raise ValueError('Invalid video acknowledgement')
            self.last_ack=time.monotonic();self.ack_seq=row['sequence'];self.receiver=row
            sent=row.get('echo_sent_ns')
            if isinstance(sent,str):self.rtt_ms=(time.monotonic_ns()-int(sent))/1e6
            if row.get('request_keyframe'):self.owner.encoder.request_keyframe(self.id)
    async def run(self):
        while not self.stopping:
            try:
                self.reset_chain()
                reader,self.writer=await asyncio.wait_for(asyncio.open_connection(self.owner.host,self.owner.port,limit=8192),1)
                self.writer.transport.set_write_buffer_limits(high=32768,low=8192)
                sock=self.writer.get_extra_info('socket');sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                self.connected=True;self.connections+=1;self.error=None;self.last_ack=time.monotonic()
                if not self.first_attempt:self.reconnects+=1
                self.first_attempt=False
                self.ack_task=asyncio.create_task(self.acknowledgements(reader))
                while not self.stopping:
                    if self.ack_task.done():self.ack_task.result();raise ConnectionError('C2 reader stopped')
                    if self.last_sent and time.monotonic()-self.last_ack>1.5:raise TimeoutError('C2 acknowledgements stalled')
                    if not self.queue:await asyncio.sleep(.003);continue
                    unit=self.queue.popleft();self.queue_bytes-=len(unit.data)
                    delay=self.owner.status.link.config.latency_ms/1000
                    await asyncio.sleep(max(0,unit.emitted_ns/1e9+delay-time.monotonic()))
                    age=time.monotonic()-unit.emitted_ns/1e9
                    if age>self.MAX_AGE_S:
                        self.dropped+=1;self.reset_chain();continue
                    meta={'stream_id':self.id,'session':unit.encoder_session,'sequence':unit.sequence,
                        'source_sequence':unit.source_sequence,'source_received_ns':str(unit.source_received_ns) if unit.source_received_ns is not None else None,
                        'pts_us':unit.pts_ns//1000,'width':unit.width,'height':unit.height,'keyframe':unit.keyframe,
                        'codec':'h264','format':'annexb','plan_revision':unit.requested_plan_revision,
                        'sent_ns':str(time.monotonic_ns()),'clock_scope':'loopback_same_host'}
                    record=pack(meta,unit.data);self.inflight_bytes=len(record)
                    chunk_size=min(8192,max(512,int(self.owner.capacity()/8*.01)))
                    for at in range(0,len(record),chunk_size):
                        chunk=record[at:at+chunk_size]
                        await self.owner.pacer.acquire(len(chunk),self.priority())
                        if time.monotonic()-unit.emitted_ns/1e9>self.MAX_AGE_S:raise TimeoutError('Frame exceeded transmission age deadline')
                        self.writer.write(chunk)
                        await asyncio.wait_for(self.writer.drain(),.4)
                        self.sent_bytes+=len(chunk);self.inflight_bytes-=len(chunk)
                        now=time.monotonic();self.owner.bytes.append((now,len(chunk)));self.events.append((now,len(chunk)))
                    self.sent_frames+=1;self.last_sent=time.monotonic()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.error=str(exc);self.owner.event(f'{self.id}: {exc}')
            finally:
                self.connected=False;self.inflight_bytes=0
                if self.ack_task:self.ack_task.cancel();await asyncio.gather(self.ack_task,return_exceptions=True);self.ack_task=None
                if self.writer:
                    self.writer.close()
                    try:await asyncio.wait_for(self.writer.wait_closed(),.5)
                    except (OSError,TimeoutError):pass
                    self.writer=None
            if not self.stopping:await asyncio.sleep(.3)
    def state(self):
        now=time.monotonic();recent=[e for e in self.events if now-e[0]<2]
        return {'id':self.id,'name':f'Camera {self.id[-2:]}','session':self.epoch,'connected':self.connected,
            'sent_frames':self.sent_frames,'sent_bytes':self.sent_bytes,'sent_bitrate_bps':sum(e[1] for e in recent)*4,
            'queue_frames':len(self.queue),'queue_bytes':self.queue_bytes,'inflight_bytes':self.inflight_bytes,
            'oldest_queue_age_ms':max(0,(now-self.queue[0].emitted_ns/1e9)*1000) if self.queue else 0,
            'dropped_frames':self.dropped+self.subscription.dropped,'waiting_for_keyframe':self.waiting,
            'connections':self.connections,'reconnects':self.reconnects,'ack_sequence':self.ack_seq,
            'ack_age_s':now-self.last_ack if self.last_ack else None,'ack_turnaround_ms':self.rtt_ms,
            'receiver':self.receiver,'error':self.error}
    async def close(self):
        self.stopping=True;self.subscription.close()
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.queue.clear();self.queue_bytes=0


class TransmissionRuntime:
    def __init__(self,encoder,decision,status):
        self.encoder,self.decision,self.status=encoder,decision,status
        self.host='127.0.0.1';self.port=8874;self.enabled=False;self.task=None
        self.order=list(STREAM_IDS);self.video_share=70;self.plan_checked_at=0
        self.jobs={};self.previous={};self.events=deque(maxlen=30);self.bytes=deque(maxlen=10000)
        self.pacer=SharedPacer(self.capacity);self.lock=asyncio.Lock();self.error=None
    def event(self,text):self.events.appendleft({'time':time.strftime('%H:%M:%S'),'message':text})
    def capacity(self):
        return int(self.status.link.config.bandwidth_bps*self.video_share/100) if self.enabled else 0
    def refresh_plan(self,force=False):
        now=time.monotonic()
        if force or now-self.plan_checked_at>.1:
            plan=self.decision.state();self.video_share=plan['configuration']['video_share_percent']
            self.order=plan.get('inputs',{}).get('ordered_stream_ids',list(STREAM_IDS))
            self.plan_checked_at=now
    async def start(self):await self.pacer.start();self.task=asyncio.create_task(self.run())
    async def configure(self,data):
        if not isinstance(data,dict) or not set(data)<= {'enabled','host','port'}:raise ValueError('Supply enabled, host and/or port')
        enabled=data.get('enabled',self.enabled);host=data.get('host',self.host);port=data.get('port',self.port)
        if type(enabled) is not bool or not isinstance(host,str) or not ipaddress.IPv4Address(host).is_loopback or type(port) is not int or not 1024<=port<=65535:raise ValueError('Use a loopback IPv4 address, port 1024–65535 and Boolean enabled')
        async with self.lock:
            if (host,port)!=(self.host,self.port) or not enabled:await self.stop_all()
            self.host,self.port,self.enabled=host,port,enabled
        await self.reconcile()
    async def stop_one(self,id):
        job=self.jobs.pop(id);await job.close();self.previous[id]=job.state()
    async def stop_all(self):
        for id in tuple(self.jobs):await self.stop_one(id)
    async def reconnect(self):
        async with self.lock:await self.stop_all()
        await self.reconcile();self.event('Explicit TCP reconnection requested')
    async def reconcile(self):
        self.refresh_plan()
        async with self.lock:
            active={id:w.session for id,w in self.encoder.jobs.items() if w.state()['state']=='encoding'} if self.enabled and self.capacity()>0 else {}
            for id in tuple(self.jobs):
                if active.get(id)!=self.jobs[id].epoch:await self.stop_one(id)
            for id,epoch in active.items():
                if id not in self.jobs:
                    job=CameraSender(self,id,epoch);self.jobs[id]=job;job.task=asyncio.create_task(job.run())
            for job in self.jobs.values():job.ingest()
    async def run(self):
        while True:
            try:await self.reconcile();self.error=None
            except Exception as exc:
                self.error=str(exc)
                async with self.lock:await self.stop_all()
            await asyncio.sleep(.01 if self.enabled else .1)
    def state(self):
        now=time.monotonic();rows=[]
        for id in STREAM_IDS:
            row=self.jobs[id].state() if id in self.jobs else dict(self.previous.get(id,{}),id=id,name=f'Camera {id[-2:]}',connected=False,queue_frames=0,queue_bytes=0,inflight_bytes=0,sent_bitrate_bps=0,oldest_queue_age_ms=0)
            row['active']=id in self.jobs;rows.append(row)
        return {'enabled':self.enabled,'process_pid':os.getpid(),'runtime_healthy':self.task is not None and not self.task.done(),
            'destination':{'host':self.host,'port':self.port},'connected_streams':sum(r['connected'] for r in rows),
            'wire_bitrate_bps':sum(n for t,n in self.bytes if now-t<2)*4 if self.enabled else 0,
            'shared_video_capacity_bps':self.capacity(),'simulated_one_way_delay_ms':self.status.link.config.latency_ms,
            'max_queue_frames_per_camera':CameraSender.MAX_FRAMES,'max_queue_bytes_per_camera':CameraSender.MAX_BYTES,
            'frame_age_deadline_ms':CameraSender.MAX_AGE_S*1000,'cameras':rows,'error':self.error,'events':list(self.events),
            'scope':'Real loopback TCP; shared application byte pacing/delay, not packet-loss emulation',
            'protocol':'URV1 / Annex B H.264 / one TCP connection per camera'}
    async def close(self):
        self.enabled=False
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        async with self.lock:await self.stop_all()
        await self.pacer.close()
