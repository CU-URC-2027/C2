"""Opt-in ROS video configuration/health adapter. No chassis authority."""
import time
from .priorities import VideoPriorities
from ros_video_common import validate_budget,qos,new_node,spin,close


class ROSVideoPriorities(VideoPriorities):
    def __init__(self,namespace='/urc_video_lab',available_bps=20_000_000,video_share_percent=70):
        super().__init__(enabled=True)
        self.namespace=namespace;self.node=None;self.owns_context=False
        self.available_bps,self.video_share_percent=validate_budget(available_bps,video_share_percent)
        self.remote_health=None;self.remote_plan=None;self.health_received=None
        self.rover_session=None;self.retired_rovers=set();self.health_sequence=-1;self.plan_sequence=-1
    def start(self):
        from urc_video_interfaces.msg import FeedPriorities,VideoLinkBudget,VideoHealth,EncodingPlan
        self.types=(FeedPriorities,VideoLinkBudget)
        self.node,self.owns_context=new_node('c2_video_adapter',self.namespace)
        self.priority_pub=self.node.create_publisher(FeedPriorities,'priorities',qos(True))
        self.budget_pub=self.node.create_publisher(VideoLinkBudget,'link_budget',qos())
        self.health_sub=self.node.create_subscription(VideoHealth,'health',self.receive_health,qos())
        self.plan_sub=self.node.create_subscription(EncodingPlan,'encoding_plan',self.receive_plan,qos())
    def configure_budget(self,available_bps,video_share_percent):
        self.available_bps,self.video_share_percent=validate_budget(available_bps,video_share_percent)
        self.last_sent=None
    def destination(self,host,port,enabled):
        if type(enabled) is not bool:raise ValueError('enabled must be Boolean')
        if (host,port)!=self.target:raise ValueError('ROS video topics are fixed by the runner namespace')
        self.enabled=enabled;self.last_sent=None
    def receive_health(self,m):
        if m.schema_version!=1 or m.priority_source_session!=self.session or m.priority_sequence not in self.sent:return
        if m.source_session in self.retired_rovers:return
        if m.source_session!=self.rover_session:
            if self.rover_session:
                if len(self.retired_rovers)>=32:
                    self.error='Too many rover restarts; restart the video adapter';return
                self.retired_rovers.add(self.rover_session)
            self.rover_session=m.source_session;self.health_sequence=self.plan_sequence=-1
        if m.sequence<=self.health_sequence:return
        self.health_sequence=m.sequence
        self.last_ack=self.clock();self.ack_sequence=m.priority_sequence;self.ack_revision=m.priority_revision
        self.rtt_ms=(self.last_ack-self.sent[m.priority_sequence][0])*1000
        self.remote_health={k:getattr(m,k) for k in m.get_fields_and_field_types()}
        self.health_received=self.last_ack
    def receive_plan(self,m):
        if m.schema_version!=1 or m.source_session!=self.rover_session or m.sequence<=self.plan_sequence:return
        self.plan_sequence=m.sequence
        self.remote_plan=dict(state=m.state,revision=m.plan_revision,video_budget_bps=m.video_budget_bps,
            execution_mode=m.execution_mode,hardware_validated=m.hardware_validated,
            cameras=[dict(id=c.stream_id,selected=c.selected,width=c.width,height=c.height,fps=c.fps,
                target_bitrate_bps=c.target_bitrate_bps,reason=c.reason) for c in m.cameras])
    def tick(self):
        if self.node is None:return
        spin(self.node)
        now=self.clock()
        if self.enabled and (self.last_sent is None or now-self.last_sent>=.5):
            self.sequence+=1
            p=self.types[0]()
            for key,value in self.message().items():setattr(p,key,value)
            self.priority_pub.publish(p)
            self.budget_pub.publish(self.types[1](schema_version=1,source_session=self.session,
                sequence=self.sequence,available_bps=self.available_bps,video_share_percent=self.video_share_percent))
            self.sent[self.sequence]=(now,self.revision)
            self.sent={k:v for k,v in self.sent.items() if k>self.sequence-128}
            self.last_sent=now
    def state(self):
        return dict(super().state(),transport='ros2_tcp',namespace=self.namespace,
            link_budget=dict(available_bps=self.available_bps,video_share_percent=self.video_share_percent,
                source='Explicit comms/test input; not a measured network estimator'),
            remote_health=self.remote_health,remote_plan=self.remote_plan)
    def close(self):
        if self.node:close(self.node,self.owns_context);self.node=None
