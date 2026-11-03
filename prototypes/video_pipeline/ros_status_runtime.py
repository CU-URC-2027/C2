"""Rover ROS metadata adapter around the unchanged StatusManager/decision cores."""
import asyncio
from collections import deque
import os
import time
import uuid
from types import SimpleNamespace
from simulated_link import LinkConfig
from status_manager import StatusManager,FeedPriorities,BandwidthInput
from ros_video_common import validate_budget,qos,new_node,spin,close


class ROSStatusRuntime:
    allocation_external=True
    def __init__(self,stream_ids,namespace='/urc_video_lab'):
        self.manager=StatusManager(stream_ids);self.namespace=namespace
        self.session=uuid.uuid4().hex;self.node=None;self.task=None;self.events=deque(maxlen=40)
        self.link=SimpleNamespace(config=LinkConfig(0,0));self.share=70.;self.messages=0;self.error=None
    def attach(self,decision,encoder,transmission):
        self.decision,self.encoder,self.transmission=decision,encoder,transmission
    def event(self,text):self.events.appendleft(dict(time=time.strftime('%H:%M:%S'),message=text))
    async def start(self):
        from urc_video_interfaces.msg import FeedPriorities,VideoLinkBudget,StatusInputs,EncodingPlan,CameraEncodingPlan,VideoHealth
        self.types=StatusInputs,EncodingPlan,CameraEncodingPlan,VideoHealth
        self.node,self.owns_context=new_node('video_rover',self.namespace)
        self.priority_sub=self.node.create_subscription(FeedPriorities,'priorities',self.priority,qos(True))
        self.budget_sub=self.node.create_subscription(VideoLinkBudget,'link_budget',self.budget,qos())
        self.status_pub=self.node.create_publisher(StatusInputs,'status_inputs',qos())
        self.plan_pub=self.node.create_publisher(EncodingPlan,'encoding_plan',qos())
        self.health_pub=self.node.create_publisher(VideoHealth,'health',qos())
        self.task=asyncio.create_task(self.run())
    def priority(self,m):
        try:
            self.manager.receive_priorities(FeedPriorities(m.source_session,m.sequence,m.revision,
                tuple(m.ordered_stream_ids),m.enabled_count,m.schema_version));self.messages+=1
        except (TypeError,ValueError) as exc:self.error=str(exc)
    def budget(self,m):
        try:
            bps,share=validate_budget(m.available_bps,m.video_share_percent)
            accepted=self.manager.receive_bandwidth(BandwidthInput(m.source_session,m.sequence,bps,m.schema_version))
            if accepted:
                self.share=share
                if share!=self.decision.core.config.video_share_percent:self.decision.configure(share)
                self.error=None
        except (TypeError,ValueError) as exc:self.error=str(exc)
    def configure_link(self,config):raise ValueError('Link budget is owned by the actual C2 ROS publisher')
    async def run(self):
        last_publish=0
        while True:
            spin(self.node)
            snapshot=self.manager.snapshot()
            self.link.config=LinkConfig(0 if snapshot['bandwidth_stale'] else (snapshot['available_bandwidth_bps'] or 0),0)
            if time.monotonic()-last_publish>=.2:
                self.publish(snapshot);last_publish=time.monotonic()
            await asyncio.sleep(.02)
    def publish(self,s):
        Status,Plan,Camera,Health=self.types
        out=Status()
        for key,value in s.items():
            if value is None:value=-1. if key.endswith('_age_s') else '' if key.endswith('_session') else 0
            setattr(out,key,value)
        self.status_pub.publish(out)
        plan=self.decision.state()
        out=Plan(schema_version=1,source_session=self.session,sequence=plan['evaluation_sequence'],
            plan_revision=plan['plan_revision'],state=plan['state'],
            video_budget_bps=plan['budget']['encoder_budget_bps'],planned_bitrate_bps=plan['budget']['planned_bitrate_bps'],
            priorities_stale=s['priorities_stale'],bandwidth_stale=s['bandwidth_stale'],hardware_validated=False,
            execution_mode=self.encoder.execution_mode)
        out.cameras=[Camera(stream_id=c['id'],operator_enabled=c['operator_enabled'],selected=c['selected'],
            profile_id=c['profile_id'] or '',width=c['width'] or 0,height=c['height'] or 0,fps=c['fps'] or 0,
            target_bitrate_bps=c['target_bitrate_bps'],reason=c['reason']) for c in plan['cameras']]
        self.plan_pub.publish(out)
        sent=sum(j.sent_frames for j in self.transmission.jobs.values())
        self.health_pub.publish(Health(schema_version=1,source_session=self.session,sequence=plan['evaluation_sequence'],
            priority_source_session=s['priority_session'] or '',priority_sequence=s['priority_sequence'] or 0,
            priority_revision=s['priority_revision'] or 0,priorities_fresh=not s['priorities_stale'],
            budget_fresh=not s['bandwidth_stale'],transmission_enabled=self.transmission.enabled,
            connected_streams=sum(j.connected for j in self.transmission.jobs.values()),sent_frames=sent,
            execution_mode=self.encoder.execution_mode,pipeline_state=plan['state'],runtime_message=self.error or ''))
    def state(self):
        s=self.manager.snapshot();connected=s['priorities_received'] and not s['priorities_stale']
        stats=dict(sent_packets=self.messages,queued_packets=0,dropped_packets=0)
        return dict(c2=dict(external=True,connected=connected,publisher_pid=None,publisher_address=None,
            ingress_address=None,backend_age_s=s['priority_age_s'],ui_url='http://127.0.0.1:8870/#cameras',
            ordered_stream_ids=s['ordered_stream_ids'],enabled_count=s['enabled_count'],revision=s['priority_revision'],
            sequence=s['priority_sequence'],session=s['priority_session'],ack_revision=s['priority_revision'],
            ack_sequence=s['priority_sequence'],ack_age_s=s['priority_age_s'],rtt_ms=None),
            process=dict(pid=os.getpid(),service='urc-video-pipeline-prototype',priority_input='ROS 2 typed metadata'),
            link=dict(transport='ros2_tcp',link_up=connected,bandwidth_bps=self.link.config.bandwidth_bps,
                latency_ms=0,c2_to_rover=stats,rover_to_c2=dict(stats,sent_packets=self.decision.core.evaluation_sequence)),
            status_manager=s,events=list(self.events),invalid_packets=self.manager.rejected)
    async def close(self):
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        if self.node:close(self.node,self.owns_context);self.node=None
