import asyncio
import json
import struct
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from c2_web.api import create_app
from c2_web.video_receiver import VideoReceiver, Channel, Viewer
from c2_web.video_wire import pack,read,HEADER,MAX_PAYLOAD,nal_info

KEY=b'\x00\x00\x00\x01\x67\x64\x00\x28abc\x00\x00\x01\x68abc\x00\x00\x01\x65picture'
DELTA=b'\x00\x00\x01\x41delta'
def meta(sequence=1,key=True,id='cam-01',session='a'*32):
    return {'stream_id':id,'session':session,'sequence':sequence,'pts_us':sequence*33333,'width':640,'height':360,'keyframe':key,'codec':'h264','format':'annexb'}


@pytest.mark.asyncio
async def test_wire_reads_fragmented_records_and_rejects_oversized_or_invalid_metadata():
    reader=asyncio.StreamReader();packet=pack(meta(),KEY)
    for at in range(0,len(packet),3):reader.feed_data(packet[at:at+3])
    m,p=await read(reader);assert m['sequence']==1 and p==KEY
    assert nal_info(p)=={'idr':True,'sps':True,'pps':True,'codec_string':'avc1.640028'}
    for bad in (HEADER.pack(b'BAD!',5,5),HEADER.pack(b'URV1',5,MAX_PAYLOAD+1)):
        reader=asyncio.StreamReader();reader.feed_data(bad)
        with pytest.raises(ValueError):await read(reader)
    with pytest.raises(ValueError):
        reader=asyncio.StreamReader();reader.feed_data(pack(dict(meta(),width=True),KEY));await read(reader)


@pytest.mark.asyncio
async def test_real_tcp_receiver_epochs_keyframe_subscription_and_reconnection():
    receiver=VideoReceiver();await receiver.start()
    try:
        r,w=await asyncio.open_connection('127.0.0.1',receiver.port)
        w.write(pack(meta(),KEY));await w.drain();ack=json.loads(await r.readline())
        assert ack['receiver_pid']>0 and receiver.channels['cam-01'].connected
        first=ack['connection_epoch'];viewer=receiver.subscribe('cam-01')
        w.write(pack(meta(2,False),DELTA));await w.drain();ack=json.loads(await r.readline())
        assert ack['request_keyframe'] and viewer.pop() is None
        w.write(pack(meta(3),KEY));await w.drain();await r.readline()
        m,p=viewer.pop();assert m['connection_epoch']==first and p==KEY
        w.close();await w.wait_closed();await asyncio.sleep(.03)
        assert not receiver.channels['cam-01'].connected and not viewer.queue
        r2,w2=await asyncio.open_connection('127.0.0.1',receiver.port)
        w2.write(pack(meta(4),KEY));await w2.drain();ack=json.loads(await r2.readline())
        assert ack['connection_epoch']!=first
        assert viewer.pop()[0]['keyframe']
        await receiver.restart();assert not receiver.channels['cam-01'].connected and not viewer.queue
        assert await r2.read()==b''
        w2.close();await w2.wait_closed()
        receiver.unsubscribe(viewer)
    finally:await receiver.stop()
    assert not receiver.connections and not receiver.tasks


def test_slow_viewer_discards_prediction_chain_and_does_not_block_other_viewers():
    c=Channel('cam-01');slow=Viewer(c);fast=Viewer(c)
    for i in range(1,9):
        m=meta(i,key=i==1);slow.push(m,KEY if i==1 else DELTA);fast.push(m,KEY if i==1 else DELTA)
        assert fast.pop() is not None
    assert slow.waiting and not slow.queue and c.request_keyframe
    slow.push(meta(9),KEY);assert slow.pop()[0]['keyframe']
    with pytest.raises(ValueError):slow.update_report({'type':'render','render_fps':float('inf')})


def test_video_websocket_is_separate_from_operator_authority_and_origin_guarded():
    app=create_app()
    with TestClient(app) as client:
        assert client.get('/api/live-video/state').json()['listening']
        with client.websocket_connect('/ws/video/cam-01') as ws:
            assert ws.receive_json()['type']=='status'
            assert app.state.station.owner is None and not app.state.station.control.armed
            ws.send_json({'type':'render','rendered_frames':1,'render_fps':30})
        assert not app.state.video_receiver.channels['cam-01'].viewers
        assert client.post('/api/live-video/restart',headers={'Origin':'https://bad.example'}).status_code==403
        assert client.post('/api/live-video/restart').json()['restart_count']==1


def test_viewer_byte_bound_also_applies_to_a_single_oversized_keyframe():
    channel=Channel('cam-01');viewer=Viewer(channel);viewer.MAX_BYTES=10
    viewer.push(meta(),KEY)
    assert viewer.bytes==0 and not viewer.queue and viewer.waiting and channel.request_keyframe
