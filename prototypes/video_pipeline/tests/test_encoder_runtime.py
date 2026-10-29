import asyncio
from copy import deepcopy
import time
from types import SimpleNamespace
import pytest
from encoder_runtime import EncoderRuntime
from encoding_decision import PROFILES
from sources import SPECS


class FakeWorker:
    serial=0
    def __init__(self,source,settings,revision,native,hub):
        FakeWorker.serial+=1;self.pid=FakeWorker.serial
        self.settings=dict(settings);self.started=time.monotonic();self.error=None;self.closed=False;self.preview_wanted=False
    def start(self):pass
    def update(self,settings,revision):self.settings=dict(settings)
    def preview(self,visible):self.preview_wanted=visible
    def close(self):self.closed=True
    def state(self):return {'state':'error' if self.error else 'encoding','output_age_s':.01,'error':self.error}
    def command(self,line):return True


def fixture():
    sources={s.id:SimpleNamespace(spec=s,running=True) for s in SPECS}
    p=PROFILES[2]
    rows=[dict(id=s.id,selected=i<2,profile_id=p.id,width=p.width,height=p.height,fps=p.fps,target_bitrate_bps=p.target_bps) for i,s in enumerate(SPECS)]
    plan={'runtime_healthy':True,'evaluation_age_s':.01,'plan_revision':1,
        'inputs':{'bandwidth_stale':False,'priorities_received':True,'ordered_stream_ids':list(sources),'enabled_count':5},
        'cameras':rows,'budget':{'encoder_budget_bps':20_000_000}}
    bank=SimpleNamespace(sources=sources);decision=SimpleNamespace(state=lambda:deepcopy(plan))
    runtime=EncoderRuntime(bank,decision,worker_factory=FakeWorker,native_prepare=lambda:{'factory':'fake','probe':{'gstreamer_version':'test'}})
    return runtime,plan


def test_rate_changes_preserve_sessions_format_changes_restart_only_one_and_omissions_stop():
    async def run():
        runtime,plan=fixture()
        try:
            await runtime.reconcile();assert not runtime.jobs
            await runtime.set_enabled(True)
            first=dict(runtime.jobs);assert len(first)==2
            plan['cameras'][0]['target_bitrate_bps']=500_000;plan['plan_revision']+=1
            await runtime.reconcile();assert runtime.jobs==first
            p=PROFILES[3];plan['cameras'][0].update(profile_id=p.id,width=p.width,height=p.height,fps=p.fps,target_bitrate_bps=p.target_bps);plan['plan_revision']+=1
            await runtime.reconcile()
            assert runtime.jobs['cam-01'] is not first['cam-01'] and first['cam-01'].closed
            assert runtime.jobs['cam-02'] is first['cam-02']
            plan['cameras'][1]['selected']=False;await runtime.reconcile()
            assert set(runtime.jobs)=={'cam-01'} and first['cam-02'].closed
            await runtime.sources_stopping();assert not runtime.jobs
            await runtime.reconcile();assert not runtime.jobs
            await runtime.sources_started();assert len(runtime.jobs)==1
            await runtime.set_enabled(False);assert not runtime.jobs
        finally:await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('field,value',[('runtime_healthy',False),('evaluation_age_s',2)])
def test_stale_or_stopped_planner_stops_encoder(field,value):
    async def run():
        runtime,plan=fixture()
        try:
            await runtime.set_enabled(True);old=list(runtime.jobs.values());plan[field]=value
            await runtime.reconcile();assert not runtime.jobs and all(w.closed for w in old)
        finally:await runtime.close()
    asyncio.run(run())


def test_outage_source_stop_invalid_budget_and_failed_worker_never_keep_stale_output():
    async def run():
        runtime,plan=fixture()
        try:
            await runtime.set_enabled(True)
            runtime.jobs['cam-01'].error='hardware failure';await runtime.reconcile()
            assert 'cam-01' not in runtime.jobs
            await runtime.reconcile();assert 'cam-01' not in runtime.jobs
            plan['plan_revision']+=1;await runtime.reconcile();assert 'cam-01' in runtime.jobs
            plan['budget']['encoder_budget_bps']=1;await runtime.reconcile()
            assert not runtime.jobs and runtime.error
            plan['budget']['encoder_budget_bps']=20_000_000;await runtime.reconcile();assert runtime.jobs and not runtime.error
            plan['inputs']['bandwidth_stale']=True;await runtime.reconcile();assert not runtime.jobs
            plan['inputs']['bandwidth_stale']=False
            for s in runtime.bank.sources.values():s.running=False
            await runtime.reconcile();assert not runtime.jobs
        finally:await runtime.close()
    asyncio.run(run())


def test_rejects_native_dimension_bitrate_and_aggregate_workload_overruns():
    runtime,plan=fixture()
    for settings in ({'width':5000},{'fps':60},{'target_bitrate_bps':True},{'target_bitrate_bps':99_000_000}):
        bad=deepcopy(plan);bad['cameras'][0].update(settings)
        with pytest.raises(ValueError):runtime.validate(bad)
    for row in plan['cameras']:
        p=PROFILES[5];row.update(selected=True,profile_id=p.id,width=p.width,height=p.height,fps=p.fps,target_bitrate_bps=p.target_bps)
    with pytest.raises(ValueError,match='Sigma'):runtime.validate(plan)


def test_native_probe_failure_keeps_encoder_off_and_no_source_side_effects():
    async def run():
        runtime,plan=fixture()
        def fail():raise RuntimeError('No hardware encoder available')
        runtime.native_prepare=fail
        with pytest.raises(ValueError,match='No hardware'):await runtime.set_enabled(True)
        assert not runtime.enabled and not runtime.jobs
        assert all(s.running for s in runtime.bank.sources.values())
        for bad in (1,'true',None):
            with pytest.raises(ValueError):await runtime.set_enabled(bad)
        runtime.preview('test',True);runtime.preview_leases['test']=0
        assert not runtime.previews_enabled
    asyncio.run(run())


def test_cancelling_during_native_spawn_waits_for_creation_and_reaps_it():
    import threading
    async def run():
        runtime,plan=fixture();began=threading.Event();finish=threading.Event();instances=[]
        class SlowWorker(FakeWorker):
            def __init__(self,*args):super().__init__(*args);instances.append(self)
            def start(self):began.set();finish.wait(2)
        runtime.worker_factory=SlowWorker;runtime.native={'factory':'fake'};runtime.enabled=True
        task=asyncio.create_task(runtime.reconcile())
        await asyncio.to_thread(began.wait,1)
        task.cancel();finish.set()
        result=await asyncio.gather(task,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
        assert instances[0].closed and not runtime.jobs
        await runtime.close()
    asyncio.run(run())
