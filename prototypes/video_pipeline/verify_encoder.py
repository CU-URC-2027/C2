"""Explicit local hardware acceptance probe. Requires real C2 publishing all five.

Toggles synthetic generators/encoding, adjusts only local bench link/video share,
restores those settings and leaves generators/encoding OFF even on failure.
Never edits C2 priorities, operates physical hardware, or transmits video.
"""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from PIL import Image

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8872'


def request(path, data=None):
    r=Request(URL+path,data=json.dumps(data).encode() if data is not None else None,
              headers={'Content-Type':'application/json'})
    with urlopen(r,timeout=20) as response:return json.load(response)


def wait(predicate, timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        s=request('/api/state')
        if predicate(s):return s
        time.sleep(.15)
    raise AssertionError('Timed out waiting for expected hardware state')


def encoder(s):return s['architecture']['encoder']
def workers(s):return {r['id']:r for r in encoder(s)['cameras'] if r['state']=='encoding'}
def ready(s,n=5):return len(workers(s))==n and all(r['output_frames']>=10 for r in workers(s).values())
def pids(s):return {id:r['process_pid'] for id,r in workers(s).items()}


def main():
    initial=request('/api/state');a=initial['architecture'];report={'checked_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'scope':'Mac synthetic local output; not Sigma or network validation'}
    assert a['status_manager']['enabled_count']==5, 'Enable all five priorities in the separate real C2 UI before this explicit test'
    link=a['link'];share=a['encoding_decision']['configuration']['video_share_percent']
    recorded_pids=set()
    try:
        request('/api/link',{'bandwidth_bps':10_000_000,'latency_ms':40})
        request('/api/encoding-decision/config',{'video_share_percent':70})
        request('/api/sources',{'running':True});request('/api/encoder/enabled',{'enabled':True})
        baseline=wait(ready);recorded_pids.update(pids(baseline).values())
        report['five_concurrent_baseline']=encoder(baseline)
        # Bitrate-only change must preserve every hardware process/session.
        request('/api/encoding-decision/config',{'video_share_percent':69})
        changed=wait(lambda s:ready(s) and all(r['accepted_plan_revision']==s['architecture']['encoding_decision']['plan_revision'] for r in workers(s).values()))
        assert pids(changed)==pids(baseline),'Bitrate-only update restarted a hardware session'
        assert any(workers(changed)[id]['accepted_bitrate_bps']!=row['accepted_bitrate_bps'] for id,row in workers(baseline).items())
        report['live_rate_change']={'same_pids':pids(changed),'before':{id:r['accepted_bitrate_bps'] for id,r in workers(baseline).items()},'after':{id:r['accepted_bitrate_bps'] for id,r in workers(changed).items()}}
        # Preview images are decoded actual H.264, not source JPEG shortcuts.
        request('/api/encoder/previews/acceptance',{'visible':True})
        previewed=wait(lambda s:ready(s) and all(r['preview_count']>0 for r in workers(s).values()))
        images={};probes={}
        for id,row in workers(previewed).items():
            data=urlopen(URL+f'/api/encoder/preview/{id}.jpg').read();im=Image.open(BytesIO(data));assert im.size==(480,270)
            images[id]=hashlib.sha256(data).hexdigest();(ROOT/f'artifacts/encoded-{id}.jpg').write_bytes(data)
            data=urlopen(URL+f'/api/encoder/capture/{id}').read();path=ROOT/f'artifacts/encoded-{id}.h264';path.write_bytes(data)
            result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name,width,height,has_b_frames','-of','json',str(path)],capture_output=True,text=True,check=True)
            stream=json.loads(result.stdout)['streams'][0]
            assert (stream['codec_name'],stream['width'],stream['height'],stream['has_b_frames'])==('h264',row['requested']['width'],row['requested']['height'],0)
            subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,capture_output=True)
            probes[id]=stream
        assert len(set(images.values()))==5
        report['independent_captures']=probes;report['distinct_decoded_preview_sha256']=images
        request('/api/encoder/previews/acceptance',{'visible':False})
        # Remaining browser leases must be collapsed by the operator for idle proof.
        hidden=wait(lambda s:not encoder(s)['previews_enabled'] and all(not r['preview_enabled'] and not r['preview_decoder'] for r in workers(s).values()))
        before={id:r['preview_count'] for id,r in workers(hidden).items()};time.sleep(.5)
        quiet=request('/api/state');assert not any(r['preview_decoder'] for r in workers(quiet).values())
        # Counts remain stable after the worker has processed the hide request.
        assert all(r['preview_count']==before[id] for id,r in workers(quiet).items())
        report['preview_decoders_stopped']=True
        # Twenty-second steady workload: real FPS, delay, frame continuity, bounded state.
        samples=[]
        for i in range(20):
            time.sleep(1);s=request('/api/state');assert ready(s)
            rows=workers(s)
            assert all(not r['error'] and r['pending_timestamp_records']<=128 and r['output_age_s']<1 for r in rows.values())
            samples.append({id:{k:r[k] for k in ('actual_fps','actual_bitrate_bps','submit_to_output_p95_ms','pending_timestamp_records','skipped_source_frames')} for id,r in rows.items()})
            if i in (4,14):print(f'Steady hardware workload: {i+1}/20 seconds',flush=True)
        assert all(min(sample[id]['actual_fps'] for sample in samples)>=row['requested']['fps']*.9 for id,row in rows.items())
        report['steady_20_seconds']=samples
        # Low bandwidth: only primary, tiny profile, a fresh epoch on format change.
        request('/api/link',{'bandwidth_bps':400_000,'latency_ms':40})
        low=wait(lambda s:ready(s,1) and workers(s)['cam-01']['requested']['profile_id']=='180p15')
        recorded_pids.update(pids(low).values())
        assert workers(low)['cam-01']['session']!=workers(changed)['cam-01']['session']
        report['low_bandwidth']=encoder(low)
        # Outage invalidates all cached output, never replays an old GOP.
        request('/api/link',{'bandwidth_bps':0,'latency_ms':40})
        outage=wait(lambda s:encoder(s)['active_sessions']==0)
        assert not encoder(outage)['output']['cached_gop_bytes']
        for id in pids(baseline):
            try:urlopen(URL+f'/api/encoder/capture/{id}');raise AssertionError('Stale output survived outage')
            except HTTPError as exc:assert exc.code==409
        report['outage_clears_output']=True
        request('/api/link',{'bandwidth_bps':10_000_000,'latency_ms':40})
        restored=wait(ready,20);recorded_pids.update(pids(restored).values())
        assert all(workers(restored)[id]['session']!=workers(baseline)[id]['session'] for id in workers(baseline))
        report['recovery']=encoder(restored)
        # Disabling camera generation while encoder intent is ON must not race/restart.
        recorded_pids.update(r['process_pid'] for r in restored['sources'] if r['process_pid'])
        request('/api/sources',{'running':False})
        stopped=wait(lambda s:encoder(s)['active_sessions']==0 and not any(r['running'] for r in s['sources']))
        time.sleep(.4);assert encoder(request('/api/state'))['active_sessions']==0
        report['source_disable_stops_all']=True
        report['passed']=True
    finally:
        request('/api/encoder/previews/acceptance',{'visible':False})
        request('/api/encoder/enabled',{'enabled':False});request('/api/sources',{'running':False})
        request('/api/link',{'bandwidth_bps':link['bandwidth_bps'],'latency_ms':link['latency_ms']})
        request('/api/encoding-decision/config',{'video_share_percent':share})
        report['final']=encoder(request('/api/state'));report['recorded_native_and_source_pids']=sorted(recorded_pids)
        (ROOT/'artifacts/encoder-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: hardware sessions, live rate change, decoded previews/captures, steady workload, low-bandwidth/outage/recovery and shutdown. Sources and encoder left OFF.')


if __name__=='__main__':main()
