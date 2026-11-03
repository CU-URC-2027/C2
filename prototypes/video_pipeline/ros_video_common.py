"""Shared ROS video adapter policy. Heavy media never enters ROS callbacks."""
import math


def validate_budget(available_bps,share):
    if type(available_bps) is not int or not 0<=available_bps<=1_000_000_000:
        raise ValueError('Use integer bandwidth from 0 to 1,000,000,000 bps')
    if type(share) not in (int,float) or not math.isfinite(share) or not 0<=share<=100:
        raise ValueError('Use video share from 0 to 100 percent')
    return available_bps,float(share)


def qos(retained=False):
    from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
    from rclpy.duration import Duration
    return QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL if retained else DurabilityPolicy.VOLATILE,
        lifespan=Duration(seconds=3 if retained else 1))


def new_node(name,namespace):
    import rclpy
    from rclpy.node import Node
    owns=not rclpy.ok()
    if owns:rclpy.init(args=[])
    return Node(name,namespace=namespace),owns


def spin(node):
    import rclpy
    # The owning asyncio/control loop pumps a bounded number of metadata callbacks.
    for _ in range(4):rclpy.spin_once(node,timeout_sec=0)


def close(node,owns):
    import rclpy
    node.destroy_node()
    if owns and rclpy.ok():rclpy.shutdown()
