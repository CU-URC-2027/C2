"""Decision consumer and resource owner. No allocation policy or transmission."""
import asyncio
from collections import deque
import os
import time

from encoded_output import OutputHub
from encoder_native import prepare
from encoder_worker import EncoderWorker
from encoding_decision import PROFILES, SigmaLimits


class EncoderRuntime:
    def __init__(self, bank, decision, worker_factory=EncoderWorker, native_prepare=prepare):
        self.bank,self.decision=bank,decision
        self.worker_factory,self.native_prepare=worker_factory,native_prepare
        self.enabled=False;self.native=None;self.task=None
        self.jobs={};self.last_jobs={};self.failed={};self.restarts={};self.events=deque(maxlen=30)
        self.hub=OutputHub();self.hub.on_keyframe_request=self.request_keyframe
        self.preview_leases={};self.lock=asyncio.Lock();self.error=None
        self.session_started=self.session_stopped=0
        self.sources_blocked=False

    def event(self, text):self.events.appendleft({'time':time.strftime('%H:%M:%S'),'message':text})

    async def start(self):self.task=asyncio.create_task(self.run())

    async def set_enabled(self, enabled):
        if type(enabled) is not bool:raise ValueError('enabled must be true or false')
        async with self.lock:
            if enabled and not self.enabled:
                try:self.native=await asyncio.to_thread(self.native_prepare)
                except Exception as exc:
                    self.error=str(exc);raise ValueError(str(exc)) from exc
                self.failed.clear();self.error=None;self.enabled=True;self.event('Hardware encoding enabled explicitly')
            elif not enabled:
                self.enabled=False
                await self.stop_all('Encoding disabled')
                self.error=None;self.failed.clear()
        await self.reconcile()

    def request_keyframe(self, id):
        worker=self.jobs.get(id)
        if worker:worker.command('KEYFRAME')

    def preview(self, client, visible):
        if not isinstance(client,str) or not 1<=len(client)<=64:raise ValueError('Invalid preview client')
        if type(visible) is not bool:raise ValueError('visible must be true or false')
        if visible:self.preview_leases[client]=time.monotonic()+5
        else:self.preview_leases.pop(client,None)

    @property
    def previews_enabled(self):
        now=time.monotonic()
        self.preview_leases={id:t for id,t in self.preview_leases.items() if t>now}
        return self.enabled and bool(self.preview_leases)

    def validate(self, plan):
        if not plan.get('runtime_healthy') or plan.get('evaluation_age_s',10)>1:return {}
        inputs=plan.get('inputs',{})
        if inputs.get('bandwidth_stale') or not inputs.get('priorities_received'):return {}
        allowed=set(inputs['ordered_stream_ids'][:inputs['enabled_count']])
        desired={}
        for row in plan['cameras']:
            if not row['selected']:continue
            id=row['id']
            if id not in allowed or id not in self.bank.sources or id in desired:raise ValueError('Invalid selected camera identity')
            source=self.bank.sources[id];s=source.spec
            profile=next((p for p in PROFILES if p.id==row['profile_id']),None)
            values=[row.get(k) for k in ('width','height','fps','target_bitrate_bps')]
            if any(type(v) is not int or v<=0 for v in values):raise ValueError('Invalid encoder settings')
            if profile is None or (row['width'],row['height'],row['fps'])!=(profile.width,profile.height,profile.fps):raise ValueError('Unknown encoding profile')
            if row['width']>s.width or row['height']>s.height or row['fps']>s.fps:raise ValueError('Output exceeds native source capability')
            if not profile.minimum_bps<=row['target_bitrate_bps']<=profile.maximum_bps:raise ValueError('Bitrate outside profile range')
            if source.running:
                desired[id]={k:row[k] for k in ('width','height','fps','target_bitrate_bps','profile_id')}
        limits=SigmaLimits()
        if len(desired)>limits.max_streams or sum(s['width']*s['height']*s['fps'] for s in desired.values())>limits.max_pixels_per_second:raise ValueError('Plan exceeds provisional Sigma workload')
        if sum(s['target_bitrate_bps'] for s in desired.values())>plan['budget']['encoder_budget_bps']:raise ValueError('Plan exceeds video budget')
        return desired

    async def stop_one(self, id, reason):
        worker=self.jobs.pop(id)
        await asyncio.to_thread(worker.close)
        self.last_jobs[id]=dict(worker.state(),stop_reason=reason)
        self.session_stopped+=1;self.event(f'{id}: {reason}')

    async def stop_all(self, reason):
        for id in tuple(self.jobs):await self.stop_one(id,reason)

    async def reconcile(self):
        async with self.lock:
            if not self.enabled or self.sources_blocked:return
            plan=self.decision.state()
            try:desired=self.validate(plan)
            except (ValueError,KeyError,TypeError) as exc:
                self.error=str(exc);await self.stop_all('Invalid/stale plan');return
            self.error=None
            revision=plan['plan_revision'];preview=self.previews_enabled
            for id in tuple(self.jobs):
                worker=self.jobs[id];requested=desired.get(id)
                if not requested:
                    await self.stop_one(id,'Not selected or source unavailable');continue
                old=worker.settings
                if tuple(old[k] for k in ('width','height','fps'))!=tuple(requested[k] for k in ('width','height','fps')):
                    await self.stop_one(id,'Resolution/fps reconfiguration');self.restarts[id]=self.restarts.get(id,0)+1
                    continue
                state=worker.state()
                if state['state']=='starting' and time.monotonic()-worker.started>5:
                    worker.error='No encoded frames within startup deadline'
                    state=worker.state()
                if state['state']=='error' or (state['output_age_s'] is not None and state['output_age_s']>2):
                    self.failed[id]=(tuple(requested.items()),revision)
                    await self.stop_one(id,'Worker failed or stopped producing frames');continue
                try:worker.update(requested,revision);worker.preview(preview)
                except RuntimeError as exc:
                    self.failed[id]=(tuple(requested.items()),revision);worker.error=str(exc)
                    await self.stop_one(id,'Native control failed')
            for id,settings in desired.items():
                if self.decision.state()['plan_revision']!=revision:return
                if id in self.jobs:continue
                key=(tuple(settings.items()),revision)
                if self.failed.get(id)==key:continue
                source=self.bank.sources[id]
                worker=self.worker_factory(source,settings,revision,self.native,self.hub)
                starting=asyncio.create_task(asyncio.to_thread(worker.start))
                try:
                    # Reaping must include a spawn already dispatched to a thread.
                    # Cancellation cannot leave that native process ownerless.
                    await asyncio.shield(starting)
                    self.jobs[id]=worker;self.session_started+=1;worker.preview(preview)
                    self.event(f'{id}: native hardware session started')
                except asyncio.CancelledError:
                    try:await starting
                    finally:await asyncio.to_thread(worker.close)
                    raise
                except Exception as exc:
                    worker.error=str(exc);await asyncio.to_thread(worker.close)
                    self.last_jobs[id]=worker.state();self.failed[id]=key
                    self.event(f'{id}: failed: {exc}')

    async def run(self):
        while True:
            try:await self.reconcile()
            except Exception as exc:
                self.error=str(exc)
                async with self.lock:await self.stop_all('Encoder manager error')
            await asyncio.sleep(.2)

    def state(self):
        rows=[]
        plan=self.decision.state()
        planned={r['id']:r for r in plan['cameras']}
        for id,source in self.bank.sources.items():
            row=self.jobs[id].state() if id in self.jobs else dict(self.last_jobs.get(id,{}))
            if id not in self.jobs:row.update(state='error' if id in self.failed else 'disabled',process_pid=None,actual_fps=0,actual_bitrate_bps=0,preview_enabled=False)
            row.update(id=id,name=getattr(getattr(source,'spec',None),'name',f'Camera {id[-2:]}'),
                       desired=planned.get(id),reconfiguration_count=self.restarts.get(id,0))
            rows.append(row)
        return {'enabled':self.enabled,'process_pid':os.getpid(),
            'runtime_healthy':self.task is not None and not self.task.done(),
            'backend':self.native['factory'] if self.native else 'not probed',
            'gstreamer_version':self.native['probe']['gstreamer_version'] if self.native else None,
            'active_sessions':len(self.jobs),'session_started':self.session_started,'session_stopped':self.session_stopped,
            'previews_enabled':self.previews_enabled,'error':self.error,'cameras':rows,
            'output':self.hub.state(),'events':list(self.events),'mode':'hardware_encoder_local_output',
            'transmission_connected':False}

    def jpeg(self, id):
        worker=self.jobs.get(id)
        if not worker or not self.previews_enabled:return None
        with worker.lock:return (worker.jpeg,worker.jpeg_pts) if worker.jpeg else None

    async def sources_stopping(self):
        async with self.lock:
            self.sources_blocked=True
            await self.stop_all('Camera generation disabled')

    async def sources_started(self):
        async with self.lock:self.sources_blocked=False
        await self.reconcile()

    async def close(self):
        self.enabled=False;self.preview_leases.clear()
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        async with self.lock:await self.stop_all('Lab shutdown')
