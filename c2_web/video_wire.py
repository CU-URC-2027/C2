"""Versioned H.264 framing, duplicated standalone in c2_web/video_wire.py.

TCP URV1: 12-byte length header + 66-byte fixed metadata + Annex B access unit.
Browser URB1: same length prefix, bounded JSON metadata + identical H.264 bytes.
No camera pixels, decoder or lab imports belong in this adapter.
"""
import json
import re
import struct

MAGIC=b'URV1'
BROWSER_MAGIC=b'URB1'
HEADER=struct.Struct('!4sII')
META=struct.Struct('!BBHH16sQQQQQI')
MAX_META=4096
MAX_PAYLOAD=16*1024*1024
STREAM_IDS=tuple(f'cam-{i:02}' for i in range(1,6))
START=re.compile(b'\x00\x00\x00?\x01')


def validate(m):
    if not isinstance(m,dict) or m.get('stream_id') not in STREAM_IDS:raise ValueError('Unknown stream')
    if not isinstance(m.get('session'),str) or re.fullmatch('[0-9a-f]{32}',m['session']) is None:raise ValueError('Invalid encoder epoch')
    for k,low,high in (('sequence',1,2**53-1),('pts_us',0,2**53-1),('width',16,3840),('height',16,2160)):
        if type(m.get(k)) is not int or not low<=m[k]<=high:raise ValueError('Invalid '+k)
    if type(m.get('keyframe')) is not bool or m.get('codec')!='h264' or m.get('format')!='annexb':raise ValueError('Expected H.264 Annex B')


def pack(meta,payload):
    validate(meta)
    if not 1<=len(payload)<=MAX_PAYLOAD:raise ValueError('Payload exceeds wire bounds')
    flags=int(meta['keyframe'])|(2 if meta.get('clock_scope')=='loopback_same_host' else 0)
    header=META.pack(STREAM_IDS.index(meta['stream_id'])+1,flags,meta['width'],meta['height'],bytes.fromhex(meta['session']),
        meta['sequence'],meta['pts_us'],meta.get('source_sequence') or 0,int(meta.get('source_received_ns') or 0),
        int(meta.get('sent_ns') or 0),meta.get('plan_revision') or 0)
    return HEADER.pack(MAGIC,len(header),len(payload))+header+payload


def pack_browser(meta,payload):
    header=json.dumps(meta,separators=(',',':'),allow_nan=False).encode()
    if not 1<=len(header)<=MAX_META or not 1<=len(payload)<=MAX_PAYLOAD:raise ValueError('Record exceeds browser bounds')
    return HEADER.pack(BROWSER_MAGIC,len(header),len(payload))+header+payload


async def read(reader):
    magic,m,p=HEADER.unpack(await reader.readexactly(HEADER.size))
    if magic!=MAGIC or m!=META.size or not 1<=p<=MAX_PAYLOAD:raise ValueError('Invalid URV1 record header')
    id,flags,w,h,epoch,seq,pts,source_seq,source_ns,sent_ns,rev=META.unpack(await reader.readexactly(m))
    if not 1<=id<=5 or flags&~3:raise ValueError('Invalid stream/flags')
    meta={'stream_id':STREAM_IDS[id-1],'session':epoch.hex(),'sequence':seq,'pts_us':pts,'width':w,'height':h,
        'keyframe':bool(flags&1),'codec':'h264','format':'annexb','source_sequence':source_seq or None,
        'source_received_ns':str(source_ns) if source_ns else None,'sent_ns':str(sent_ns) if sent_ns else None,
        'plan_revision':rev or None,'clock_scope':'loopback_same_host' if flags&2 else 'unmapped_remote'}
    validate(meta)
    return meta,await reader.readexactly(p)


def nal_info(payload):
    starts=list(START.finditer(payload));idr=sps=pps=False;codec=None
    for n,start in enumerate(starts):
        at=start.end();end=starts[n+1].start() if n+1<len(starts) else len(payload)
        if at>=end:continue
        kind=payload[at]&31
        if kind==5:idr=True
        if kind==7 and end-at>=4:
            sps=True;codec='avc1.'+payload[at+1:at+4].hex()
        if kind==8:pps=True
    return {'idr':idr,'sps':sps,'pps':pps,'codec_string':codec}
