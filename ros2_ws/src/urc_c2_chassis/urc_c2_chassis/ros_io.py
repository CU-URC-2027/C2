"""ROS adapter. No DDS imports in the policy/bridge tests."""
from dataclasses import asdict
import secrets
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rclpy.duration import Duration
from urc_c2_interfaces.msg import DriveIntent, ChassisState
from .policy import Intent


def qos():
    return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                      reliability=ReliabilityPolicy.BEST_EFFORT,
                      durability=DurabilityPolicy.VOLATILE,
                      lifespan=Duration(seconds=.25))


class OperatorNode(Node):
    """Tk loop calls spin_once and publishes; a blocked GUI never repeats motion."""
    def __init__(self, namespace=None):
        super().__init__('c2_operator', namespace=namespace)
        self.session = secrets.token_hex(16)
        self.seq = 0
        self.state = None
        self.received = -float('inf')
        self._seen_boot = ''
        self._seen_sequence = 0
        self.publisher = self.create_publisher(DriveIntent, 'c2/drive_intent', qos())
        self.subscription = self.create_subscription(ChassisState, 'chassis/state', self.on_state, qos())

    def on_state(self, message):
        if message.version != 1 or not message.oc_boot or not message.challenge:
            return
        if message.oc_boot == self._seen_boot and message.state_sequence <= self._seen_sequence:
            return
        self._seen_boot, self._seen_sequence = message.oc_boot, message.state_sequence
        self.state, self.received = message, time.monotonic()

    def fresh(self):
        return self.state is not None and time.monotonic()-self.received < .35

    def send(self, operation, throttle=0.0, steering=0.0, deadman=False):
        if not self.fresh():
            return False
        self.seq += 1
        p = Intent(session=self.session, oc_boot=self.state.oc_boot,
                   challenge=self.state.challenge, sequence=self.seq, epoch=self.state.epoch,
                   operation=operation, throttle=float(throttle), steering=float(steering), deadman=bool(deadman))
        msg = DriveIntent()
        for name, value in asdict(p).items():
            setattr(msg, name, value)
        self.publisher.publish(msg)
        return True
