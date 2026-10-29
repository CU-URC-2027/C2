from dataclasses import replace
import pytest
from encoded_output import EncodedAccessUnit, OutputHub


def au(sequence=1, key=True, session='first', data=b'picture'):
    return EncodedAccessUnit('cam-01',session,sequence,sequence,1000,sequence*100,2000,640,360,key,1,data)


def test_gop_capture_starts_at_keyframe_and_resets_on_new_session_or_stop():
    hub=OutputHub()
    hub.publish(au(key=False))
    assert hub.capture('cam-01') is None
    hub.publish(au(2));hub.publish(au(3,False))
    assert [f.sequence for f in hub.capture('cam-01')]==[2,3]
    hub.publish(au(4,False,'second'))
    assert hub.capture('cam-01') is None
    hub.publish(au(5,True,'second'))
    hub.invalidate('cam-01')
    assert hub.capture('cam-01') is None and not hub.state()['cached_gop_bytes']


def test_gop_cache_is_bounded_and_waits_for_next_idr_after_limit():
    hub=OutputHub();hub.MAX_GOP_BYTES=12
    hub.publish(au(data=b'12345678'));hub.publish(au(2,False,data=b'12345678'))
    assert hub.capture('cam-01') is None
    hub.publish(au(3,False,data=b'a'))
    assert hub.capture('cam-01') is None
    hub.publish(au(4,True,data=b'b'))
    assert len(hub.capture('cam-01'))==1
    hub.MAX_GOP_FRAMES=2
    hub.publish(au(5,False,data=b'c'));hub.publish(au(6,False,data=b'd'))
    assert hub.capture('cam-01') is None


def test_slow_consumer_resynchronizes_without_blocking_output_or_other_consumers():
    hub=OutputHub();requested=[];hub.on_keyframe_request=requested.append
    slow=hub.subscribe('cam-01',2);fast=hub.subscribe('cam-01',2)
    assert requested==['cam-01','cam-01']
    for n in range(1,5):
        hub.publish(au(n,key=n==1));assert len(fast.drain())==1
    assert not slow.drain() and slow.waiting_for_keyframe and slow.dropped==4
    hub.publish(au(5));assert slow.drain()[0].keyframe
    hub.publish(au(6,False,'new'));assert not fast.drain()
    hub.publish(au(7,True,'new'));hub.invalidate('cam-01');assert not slow.drain()
    slow.close();fast.close();assert hub.state()['subscribers']==0
    with pytest.raises(ValueError):hub.subscribe('cam-01',65)
