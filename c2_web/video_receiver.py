"""Passive local TCP video receiver and bounded binary-WebSocket fanout.

Owns no motor authority, camera generation, decoder or encoder. The HTTP app
remains loopback-only. Port 0 is useful for isolated tests; dev uses 8874.
"""
import asyncio
from collections import deque
import json
import math
import os
import time
import uuid

from .video_wire import STREAM_IDS,read,pack,nal_info


class Viewer:
    MAX_BYTES=4*1024*1024
    def __init__(self,channel):
        self.channel=channel;self.queue=deque();self.bytes=0;self.waiting=True
        self.dropped=0;self.report={};self.reported_at=None;self.closed=False
    def clear(self):self.queue.clear();self.bytes=0;self.waiting=True
    def push(self,meta,payload):
        if self.closed:return
        if len(payload)>self.MAX_BYTES:
            self.dropped+=1;self.clear();self.channel.request_keyframe=True;return
        if len(self.queue)>=6 or self.bytes+len(payload)>self.MAX_BYTES:
            self.dropped+=len(self.queue);self.clear();self.channel.request_keyframe=True
        if self.waiting and not meta['keyframe']:self.dropped+=1;return
        self.waiting=False;self.queue.append((meta,payload));self.bytes+=len(payload)
    def pop(self):
        if not self.queue:return None
        item=self.queue.popleft();self.bytes-=len(item[1]);return item
    def update_report(self,row):
        if not isinstance(row,dict) or row.get('type')!='render':raise ValueError('Expected render report')
        clean={}
        for k in ('rendered_frames','decoded_frames','last_sequence','render_fps','decode_fps','decoder_queue','client_dropped','arrival_to_render_ms'):
            v=row.get(k,0)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=2**53-1:raise ValueError('Invalid render telemetry')
            clean[k]=v
        self.report=clean;self.reported_at=time.monotonic()


class Channel:
    def __init__(self,id):
        self.id=id;self.writer=None;self.epoch=None;self.session=None;self.connected=False;self.codec=None
        self.last_received=None;self.sequence=0;self.frames=self.bytes=0;self.connections=0
        self.width=self.height=None;self.viewers=set();self.request_keyframe=False
        self.events=deque(maxlen=180);self.error=None;self.last_source_age_ms=None;self.last_keyframe_request=0
    def clear(self):
        self.connected=False;self.writer=None;self.last_received=None;self.codec=None
        for viewer in self.viewers:viewer.clear()
    def state(self):
        now=time.monotonic();recent=[e for e in self.events if now-e[0]<2]
        fps=(len(recent)-1)/(recent[-1][0]-recent[0][0]) if len(recent)>1 else 0
        reports=[v.report for v in self.viewers if v.reported_at and now-v.reported_at<2]
        fresh=self.connected and self.last_received is not None and now-self.last_received<1
        return {'id':self.id,'name':f'Camera {self.id[-2:]}','connected':self.connected,'fresh':fresh,
            'session':self.session,'connection_epoch':self.epoch,'sequence':self.sequence,'received_frames':self.frames,
            'received_bytes':self.bytes,'connections':self.connections,'width':self.width,'height':self.height,'codec_string':self.codec,
            'receive_fps':fps if fresh else 0,'received_bitrate_bps':sum(n for t,n in recent)*4 if fresh else 0,
            'last_receive_age_ms':(now-self.last_received)*1000 if self.last_received else None,
            'loopback_source_to_receive_ms':self.last_source_age_ms if fresh else None,
            'viewers':len(self.viewers),'reporting_viewers':len(reports),
            'render_fps':max((r['render_fps'] for r in reports),default=0),
            'rendered_frames':max((r['rendered_frames'] for r in reports),default=0),
            'viewer_dropped_frames':sum(v.dropped for v in self.viewers),'error':self.error}


class VideoReceiver:
    def __init__(self,port=0):
        self.port=port;self.server=None;self.channels={id:Channel(id) for id in STREAM_IDS}
        self.tasks=set();self.connections=set();self.error=None;self.invalid_records=0;self.restart_count=0;self.lock=asyncio.Lock()
    async def start(self):
        self.server=await asyncio.start_server(self.accept,'127.0.0.1',self.port,limit=8192)
        self.port=self.server.sockets[0].getsockname()[1]
    async def accept(self,reader,writer):
        task=asyncio.current_task();self.tasks.add(task);self.connections.add(writer);channel=None;token=uuid.uuid4().hex
        try:
            if len(self.connections)>10:raise ValueError('Too many video connections')
            peer=writer.get_extra_info('peername')
            if not peer or peer[0]!='127.0.0.1':raise ValueError('Only loopback senders are supported')
            while True:
                meta,payload=await asyncio.wait_for(read(reader),2)
                info=nal_info(payload)
                if meta['keyframe']!=info['idr']:raise ValueError('Incorrect IDR flag')
                if channel is None:
                    if not (info['idr'] and info['sps'] and info['pps']):raise ValueError('New TCP stream requires IDR/SPS/PPS')
                    channel=self.channels[meta['stream_id']]
                    if channel.writer and channel.writer is not writer:channel.writer.close()
                    channel.clear();channel.writer=writer;channel.epoch=token;channel.session=meta['session']
                    channel.sequence=0;channel.connected=True;channel.connections+=1;channel.error=None
                if channel.epoch!=token:break
                if meta['stream_id']!=channel.id or meta['session']!=channel.session or meta['sequence']<=channel.sequence:raise ValueError('Video identity or sequence changed within TCP epoch')
                if meta['sequence']!=channel.sequence+1 and not info['idr']:
                    channel.request_keyframe=True
                    for viewer in channel.viewers:viewer.clear()
                if info['codec_string']:channel.codec=info['codec_string']
                if not channel.codec:raise ValueError('Missing decoder configuration')
                now=time.monotonic();channel.last_received=now;channel.sequence=meta['sequence']
                channel.frames+=1;channel.bytes+=len(payload);channel.width=meta['width'];channel.height=meta['height']
                channel.events.append((now,len(payload)))
                source_ns=meta.get('source_received_ns')
                channel.last_source_age_ms=(time.monotonic_ns()-int(source_ns))/1e6 if meta.get('clock_scope')=='loopback_same_host' and isinstance(source_ns,str) else None
                delivered=dict(meta,connection_epoch=token,codec_string=channel.codec,received_wall_ms=time.time()*1000)
                for viewer in tuple(channel.viewers):viewer.push(delivered,payload)
                if info['idr']:channel.request_keyframe=False
                request_keyframe=channel.request_keyframe and now-channel.last_keyframe_request>=.25
                if request_keyframe:channel.request_keyframe=False;channel.last_keyframe_request=now
                state=channel.state()
                ack={'type':'ack','stream_id':channel.id,'sequence':meta['sequence'],'receiver_pid':os.getpid(),
                    'echo_sent_ns':meta.get('sent_ns'),'request_keyframe':request_keyframe,
                    'receive_fps':state['receive_fps'],'render_fps':state['render_fps'],'rendered_frames':state['rendered_frames'],
                    'received_frames':channel.frames,'viewers':len(channel.viewers),'connection_epoch':token}
                writer.write(json.dumps(ack,separators=(',',':')).encode()+b'\n');await asyncio.wait_for(writer.drain(),.5)
        except asyncio.CancelledError:raise
        except (ValueError,TypeError,KeyError,OSError,TimeoutError,asyncio.IncompleteReadError,ConnectionError) as exc:
            if not isinstance(exc,asyncio.IncompleteReadError):self.invalid_records+=isinstance(exc,ValueError)
            if channel and channel.epoch==token:channel.error=str(exc)[:200]
        finally:
            if channel and channel.epoch==token:channel.clear()
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),.5)
            except (OSError,TimeoutError):pass
            self.connections.discard(writer);self.tasks.discard(task)
    def subscribe(self,id):
        channel=self.channels[id]
        if len(channel.viewers)>=8:raise ValueError('Camera viewer limit reached')
        viewer=Viewer(channel);channel.viewers.add(viewer);channel.request_keyframe=True;return viewer
    def unsubscribe(self,viewer):
        viewer.closed=True;viewer.clear();viewer.channel.viewers.discard(viewer)
    async def stop(self):
        if self.server:self.server.close();await self.server.wait_closed();self.server=None
        for writer in tuple(self.connections):writer.close()
        for task in tuple(self.tasks):task.cancel()
        await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
        for channel in self.channels.values():channel.clear()
    async def restart(self):
        async with self.lock:
            await self.stop();await self.start();self.restart_count+=1
    def state(self):
        return {'process_pid':os.getpid(),'listening':self.server is not None,'host':'127.0.0.1','port':self.port,
            'protocol':'URV1 / H.264 Annex B','restart_count':self.restart_count,'invalid_records':self.invalid_records,
            'cameras':[c.state() for c in self.channels.values()],'error':self.error,
            'scope':'Local TCP receive and binary-WebSocket relay; no server video decoding or encoding'}
