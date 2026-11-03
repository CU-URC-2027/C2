import hashlib
import json
import time
from types import SimpleNamespace
import pytest
from encoded_output import OutputHub
from replay import access_units,FixtureCatalog,ReplayWorker
from ros_video_common import validate_budget

AUD=b'\x00\x00\x01\x09\xf0'
KEY=AUD+b'\x00\x00\x01\x67\x42\x00\x1fabc\x00\x00\x01\x68abc\x00\x00\x01\x65picture'
DELTA=AUD+b'\x00\x00\x01\x41delta'


def catalog(tmp_path):
    data=KEY+DELTA;(tmp_path/'cam.h264').write_bytes(data)
    row=dict(stream_id='cam-01',profile_id='180p15',file='cam.h264',width=320,height=180,
        fps=15,frames=2,nominal_bitrate_bps=150000,sha256=hashlib.sha256(data).hexdigest())
    manifest=dict(schema_version=1,fixtures=[row])
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_fixture_framing_hash_profile_and_path_validation(tmp_path):
    assert access_units(KEY+DELTA)==(KEY,DELTA)
    with pytest.raises(ValueError):access_units(b'not Annex B')
    manifest=catalog(tmp_path);assert len(FixtureCatalog(tmp_path).fixtures)==1
    for change in ({'file':'../elsewhere.h264'},{'sha256':'bad'},{'width':3840},{'stream_id':'unknown'}):
        modified=dict(manifest,fixtures=[manifest['fixtures'][0]|change])
        (tmp_path/'manifest.json').write_text(json.dumps(modified))
        with pytest.raises(ValueError):FixtureCatalog(tmp_path)


def test_replay_loops_monotonic_pts_recovers_idr_and_reaps_without_hardware(tmp_path):
    catalog(tmp_path);c=FixtureCatalog(tmp_path);hub=OutputHub();sub=hub.subscribe('cam-01',16)
    source=SimpleNamespace(spec=SimpleNamespace(id='cam-01',name='Camera 01'),running=True)
    settings=dict(profile_id='180p15',width=320,height=180,fps=15,target_bitrate_bps=200000)
    w=ReplayWorker(source,settings,1,c.native,hub)
    try:
        w.start();time.sleep(.24);first=sub.drain()
        assert len(first)>=3 and all(b.pts_ns>a.pts_ns for a,b in zip(first,first[1:]))
        assert not w.state()['hardware_confirmed']
        w.command('KEYFRAME');time.sleep(.09);assert any(x.keyframe for x in sub.drain())
        with pytest.raises(RuntimeError):w.update(settings|{'target_bitrate_bps':100},2)
    finally:w.close()
    assert not w.thread.is_alive() and hub.capture('cam-01') is None


def test_ros_budget_accepts_outage_and_rejects_nonfinite_or_boolean_inputs():
    assert validate_budget(0,0)==(0,0.)
    for b,s in ((True,70),(1,float('nan')),(1,101),(-1,70)):
        with pytest.raises(ValueError):validate_budget(b,s)
