"""Bounded local H.264 access-unit handoff for transport adapters.

No networking. Slow subscribers wait for the next IDR after overflow/session
changes, rather than receiving an undecodable partial prediction chain.
"""
from collections import deque
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class EncodedAccessUnit:
    stream_id: str
    encoder_session: str
    sequence: int
    source_sequence: int | None
    source_received_ns: int | None
    pts_ns: int
    emitted_ns: int
    width: int
    height: int
    keyframe: bool
    requested_plan_revision: int | None
    data: bytes
    codec: str = 'h264'
    stream_format: str = 'annexb'


class Subscription:
    def __init__(self, stream_id, capacity=8):
        self.stream_id,self.capacity=stream_id,capacity
        self.queue=deque();self.session=None;self.waiting_for_keyframe=True
        self.dropped=0;self.closed=False;self.lock=threading.Lock()

    def push(self, frame):
        with self.lock:
            if self.closed:return
            if frame.encoder_session!=self.session:
                self.queue.clear();self.session=frame.encoder_session;self.waiting_for_keyframe=True
            if len(self.queue)>=self.capacity:
                self.dropped+=len(self.queue);self.queue.clear();self.waiting_for_keyframe=True
            if self.waiting_for_keyframe and not frame.keyframe:
                self.dropped+=1;return
            self.waiting_for_keyframe=False;self.queue.append(frame)

    def drain(self):
        with self.lock:
            result=list(self.queue);self.queue.clear();return result

    def reset(self):
        with self.lock:self.queue.clear();self.waiting_for_keyframe=True;self.session=None

    def close(self):
        with self.lock:self.closed=True;self.queue.clear()


class OutputHub:
    MAX_GOP_BYTES=8*1024*1024
    MAX_GOP_FRAMES=64
    def __init__(self):
        self.lock=threading.Lock();self.gops={};self.gop_bytes={};self.latest={};self.subscribers=[]
        self.on_keyframe_request=None

    def subscribe(self, stream_id, capacity=8):
        if type(capacity) is not int or not 1<=capacity<=64:raise ValueError('Use a subscription capacity from 1 to 64')
        sub=Subscription(stream_id,capacity)
        with self.lock:self.subscribers.append(sub)
        if self.on_keyframe_request:self.on_keyframe_request(stream_id)
        return sub

    def publish(self, frame):
        with self.lock:
            id=frame.stream_id
            previous=self.latest.get(id)
            if frame.keyframe or previous is None or frame.encoder_session!=previous.encoder_session:
                self.gops[id]=[];self.gop_bytes[id]=0
            self.latest[id]=frame
            gop=self.gops[id]
            if frame.keyframe or gop:
                if self.gop_bytes[id]+len(frame.data)<=self.MAX_GOP_BYTES and len(gop)<self.MAX_GOP_FRAMES:
                    gop.append(frame);self.gop_bytes[id]+=len(frame.data)
                else:gop.clear();self.gop_bytes[id]=0
            self.subscribers=[s for s in self.subscribers if not s.closed]
            for sub in self.subscribers:
                if sub.stream_id==id:sub.push(frame)

    def invalidate(self, stream_id):
        with self.lock:
            self.gops.pop(stream_id,None);self.gop_bytes.pop(stream_id,None);self.latest.pop(stream_id,None)
            for sub in self.subscribers:
                if sub.stream_id==stream_id:sub.reset()

    def capture(self, stream_id):
        with self.lock:
            gop=self.gops.get(stream_id,[])
            if not gop or not gop[0].keyframe:return None
            return tuple(gop)

    def state(self):
        with self.lock:
            return {'scope':'Bounded local access-unit handoff; TCP state is in the Transmission module',
                    'cached_gop_bytes':dict(self.gop_bytes),'subscribers':sum(not s.closed for s in self.subscribers),
                    'max_gop_bytes_per_camera':self.MAX_GOP_BYTES,'max_gop_frames_per_camera':self.MAX_GOP_FRAMES}
