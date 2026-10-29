import time
import rclpy
from rclpy.node import Node
from urc_c2_interfaces.msg import DriveIntent, ChassisState
from .policy import Intent
from .bridge import ChassisBridge
from .ros_io import qos


class BridgeNode(Node):
    def __init__(self, namespace=None, force_mock=False):
        super().__init__('chassis_bridge', namespace=namespace)
        self.declare_parameter('mock', True)
        self.declare_parameter('rover_host', '')
        self.declare_parameter('rover_port', 4210)
        self.bridge = ChassisBridge(True if force_mock else self.get_parameter('mock').value,
                                     self.get_parameter('rover_host').value,
                                     self.get_parameter('rover_port').value)
        self.publisher = self.create_publisher(ChassisState, 'chassis/state', qos())
        self.subscription = self.create_subscription(DriveIntent, 'c2/drive_intent', self.on_intent, qos())
        self.timer = self.create_timer(.05, self.update)
        self.get_logger().info('LOCAL MOCK — no motors' if self.bridge.mock_mode else 'REAL CHASSIS endpoint selected; starts disabled')

    def on_intent(self, msg):
        p = Intent(**{name: getattr(msg, name) for name in Intent.__dataclass_fields__})
        self.bridge.receive(p, time.monotonic())

    def update(self):
        msg = ChassisState()
        for name, value in self.bridge.tick(time.monotonic()).items():
            setattr(msg, name, value)
        self.publisher.publish(msg)

    def destroy_node(self):
        self.bridge.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = BridgeNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
