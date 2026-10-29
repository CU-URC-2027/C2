import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
import pytest
from transmission import SharedPacer,TransmissionRuntime,CameraSender


def test_shared_pacer_prioritizes_waiters_and_enforces_one_combined_rate():
    async def run():
        rate=[0];pacer=SharedPacer(lambda:rate[0]);await pacer.start();order=[]
        async def consume(name,priority):
            for _ in range(2):await pacer.acquire(2048,priority)
            order.append(name)
        try:
            low=asyncio.create_task(consume('secondary',4));primary=asyncio.create_task(consume('primary',0))
            await asyncio.sleep(.03);assert not low.done() and not primary.done()
            start=time.monotonic();rate[0]=131072 # 16 KiB/s, 8 KiB total => ~0.5 s
            await asyncio.gather(low,primary)
            assert time.monotonic()-start>=.4 and order==['primary','secondary']
        finally:await pacer.close()
        assert not pacer.waiters
    asyncio.run(run())


def test_sender_defaults_off_validates_local_boundary_and_uses_video_allowance_once():
    class Decision:
        def state(self):return {'configuration':{'video_share_percent':70}}
    async def run():
        encoder=SimpleNamespace(jobs={});status=SimpleNamespace(link=SimpleNamespace(config=SimpleNamespace(bandwidth_bps=10_000_000,latency_ms=40)))
        runtime=TransmissionRuntime(encoder,Decision(),status);await runtime.start()
        try:
            assert not runtime.enabled and runtime.capacity()==0
            for bad in ({'enabled':1},{'host':'192.168.0.2'},{'port':True},{'unexpected':3}):
                with pytest.raises(ValueError):await runtime.configure(bad)
            await runtime.configure({'enabled':True});assert runtime.capacity()==7_000_000
            status.link.config.bandwidth_bps=0;await runtime.reconcile();assert not runtime.jobs
        finally:await runtime.close()
    asyncio.run(run())


def test_receiver_and_sender_import_one_canonical_wire_contract():
    import importlib.util
    import urc_video_protocol
    import video_wire
    repo=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('receiver_wire_shim',repo/'c2_web/video_wire.py')
    receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)
    assert receiver.pack is video_wire.pack is urc_video_protocol.pack
    assert receiver.read is video_wire.read is urc_video_protocol.read


def test_oversized_access_unit_is_dropped_instead_of_exceeding_sender_queue_bound():
    from encoded_output import OutputHub, EncodedAccessUnit
    from transmission import CameraSender
    async def run():
        hub=OutputHub();encoder=SimpleNamespace(hub=hub,request_keyframe=lambda id:None)
        owner=SimpleNamespace(encoder=encoder);job=CameraSender(owner,'cam-01','a'*32);job.MAX_BYTES=10
        unit=EncodedAccessUnit('cam-01','a'*32,1,1,0,0,time.monotonic_ns(),640,360,True,1,b'X'*11)
        hub.publish(unit);job.ingest();assert job.queue_bytes==0 and job.waiting
        await job.close()
    asyncio.run(run())
