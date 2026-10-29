"""Explicit local end-to-end acceptance run with an already-playing C2 browser.

Uses actual TCP receiver and browser render reports. Tests local shaped bandwidth,
outage/recovery and both receiver- and sender-initiated reconnects. Leaves source,
encoder and sender workloads OFF; never changes C2 priorities or motion state.
"""
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
LAB='http://127.0.0.1:8872';C2='http://127.0.0.1:8870'

def req(base,path,data=None):
    request=Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=30) as response:return json.load(response)

def snapshot():
    return {'lab':req(LAB,'/api/state'),'receiver':req(C2,'/api/live-video/state')}

def wait(predicate,timeout=20):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        s=snapshot()
        if predicate(s):return s
        time.sleep(.2)
    raise AssertionError('Expected TCP/browser condition was not reached')

def playing(s,n=5):
    rows=s['receiver']['cameras']
    active=[r for r in rows if r['connected'] and r['fresh']]
    return len(active)==n and all(r['reporting_viewers']>0 and r['render_fps']>4 and r['rendered_frames']>5 for r in active)


def main():
    initial=snapshot();config=initial['lab']['architecture']['link']
    report={'checked_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'scope':'Synthetic loopback TCP and actual browser render reports; not radio or two-host validation'}
    primary=initial['lab']['architecture']['status_manager']['ordered_stream_ids'][0]
    camera=lambda s:next(r for r in s['receiver']['cameras'] if r['id']==primary)
    assert initial['lab']['architecture']['status_manager']['enabled_count']==5,'Enable all five in the actual C2 priority UI'
    try:
        req(LAB,'/api/link',{'bandwidth_bps':10_000_000,'latency_ms':40})
        req(LAB,'/api/sources',{'running':True});req(LAB,'/api/encoder/enabled',{'enabled':True});req(LAB,'/api/transmission/config',{'enabled':True})
        baseline=wait(playing);report['five_playing']=baseline
        before={r['id']:r['rendered_frames'] for r in baseline['receiver']['cameras']}
        samples=[]
        for i in range(10):
            time.sleep(1);s=snapshot();assert playing(s)
            tx=s['lab']['architecture']['transmission']
            assert tx['wire_bitrate_bps']<=tx['shared_video_capacity_bps']*1.12
            assert all(r['queue_frames']<=8 and r['queue_bytes']<=4*1024*1024 for r in tx['cameras'])
            samples.append({'sender':tx,'receiver':s['receiver']})
        assert all(r['rendered_frames']>before[r['id']] for r in samples[-1]['receiver']['cameras'])
        report['ten_second_steady']=samples;print('PASS: five actual browser decoders, increasing render counters and shared TCP payload budget',flush=True)
        req(LAB,'/api/link',{'bandwidth_bps':1_000_000,'latency_ms':40})
        low=wait(lambda s:playing(s,1) and camera(s)['fresh'] and camera(s)['width']==640)
        time.sleep(3);low=snapshot();tx=low['lab']['architecture']['transmission']
        assert tx['wire_bitrate_bps']<=700000*1.12
        report['one_megabit_primary_only']=low
        req(LAB,'/api/link',{'bandwidth_bps':400_000,'latency_ms':40})
        emergency=wait(lambda s:playing(s,1) and camera(s)['fresh'] and camera(s)['width']==320)
        report['emergency_180p15']=emergency
        req(LAB,'/api/link',{'bandwidth_bps':0,'latency_ms':40})
        outage=wait(lambda s:not any(r['connected'] for r in s['receiver']['cameras']))
        time.sleep(1.5);outage=snapshot();assert all(r['render_fps']==0 for r in outage['receiver']['cameras'])
        assert outage['lab']['architecture']['transmission']['connected_streams']==0
        report['outage']=outage;print('PASS: 1 Mb/s, 400 kb/s and zero-bandwidth stale/stop behavior',flush=True)
        req(LAB,'/api/link',{'bandwidth_bps':10_000_000,'latency_ms':40})
        recovered=wait(playing,25);report['bandwidth_recovery']=recovered
        epochs={r['id']:r['connection_epoch'] for r in recovered['receiver']['cameras']}
        counts={r['id']:r['rendered_frames'] for r in recovered['receiver']['cameras']}
        req(C2,'/api/live-video/restart',{})
        restarted=wait(lambda s:playing(s) and all(r['connection_epoch']!=epochs[r['id']] and r['rendered_frames']>counts[r['id']] for r in s['receiver']['cameras']))
        report['receiver_restart_recovery']=restarted
        epochs={r['id']:r['connection_epoch'] for r in restarted['receiver']['cameras']}
        req(LAB,'/api/transmission/reconnect',{})
        reconnected=wait(lambda s:playing(s) and all(r['connection_epoch']!=epochs[r['id']] for r in s['receiver']['cameras']))
        report['sender_reconnect_recovery']=reconnected
        assert all(r['backend'] in ('vtenc_h264_hw','qsvh264enc') and r['hardware_confirmed'] for r in reconnected['lab']['architecture']['encoder']['cameras'])
        report['passed']=True;print('PASS: all five return after bandwidth recovery, receiver restart and sender reconnect',flush=True)
    finally:
        req(LAB,'/api/transmission/config',{'enabled':False});req(LAB,'/api/encoder/enabled',{'enabled':False});req(LAB,'/api/sources',{'running':False})
        req(LAB,'/api/link',{'bandwidth_bps':config['bandwidth_bps'],'latency_ms':config['latency_ms']})
        report['final']=snapshot();(ROOT/'artifacts/transmission-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Sources, encoding and transmission left OFF.')

if __name__=='__main__':main()
