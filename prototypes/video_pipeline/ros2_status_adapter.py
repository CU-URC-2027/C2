"""Optional ROS 2 adapter; not imported by the Mac lab.

Build/source ros2/urc_video_interfaces in a ROS 2 workspace first, then run this
file with that environment's Python. The standard-library StatusManager is reused
unchanged. This reference adapter has not been executed against ROS 2 on this Mac.
"""
from status_manager import BandwidthInput, FeedPriorities, StatusManager


def main():
    import rclpy
    from rclpy.node import Node
    from urc_video_interfaces.msg import BandwidthInput as BandwidthMessage
    from urc_video_interfaces.msg import FeedPriorities as PriorityMessage
    from urc_video_interfaces.msg import StatusInputs

    class StatusNode(Node):
        def __init__(self):
            super().__init__("video_status_manager")
            self.declare_parameter("stream_ids", [f"cam-{i:02}" for i in range(1, 6)])
            self.declare_parameter("stale_after_s", 3.0)
            self.core = StatusManager(self.get_parameter("stream_ids").value,
                                      stale_after_s=self.get_parameter("stale_after_s").value)
            # Depth 1 with default reliability/durability is a starting adapter
            # profile, not a validated radio QoS decision. Publishers must match.
            self.output = self.create_publisher(StatusInputs, "/video/status_inputs", 1)
            self.priority_subscription = self.create_subscription(PriorityMessage,
                "/c2/video/priorities", self.receive_priority, 1)
            self.bandwidth_subscription = self.create_subscription(BandwidthMessage,
                "/video/bandwidth_input", self.receive_bandwidth, 1)
            self.timer = self.create_timer(.2, self.publish)  # Also reports stale transitions.

        def receive_priority(self, message):
            try:
                self.core.receive_priorities(FeedPriorities(message.source_session,
                    message.sequence, message.revision, tuple(message.ordered_stream_ids),
                    message.enabled_count, message.schema_version))
                self.publish()
            except (ValueError, TypeError) as exc:
                self.get_logger().warning(f"Rejected priorities: {exc}")

        def receive_bandwidth(self, message):
            try:
                self.core.receive_bandwidth(BandwidthInput(message.source_session,
                    message.sequence, message.available_bps, message.schema_version))
                self.publish()
            except (ValueError, TypeError) as exc:
                self.get_logger().warning(f"Rejected bandwidth: {exc}")

        def publish(self):
            snapshot = self.core.snapshot()
            output = StatusInputs()
            for field, value in snapshot.items():
                if value is None:
                    value = -1.0 if field.endswith("_age_s") else "" if field.endswith("_session") else 0
                setattr(output, field, value)
            self.output.publish(output)

    rclpy.init()
    node = StatusNode()
    try:
        rclpy.spin(node)  # Single-threaded executor owns the core, like the Mac event loop.
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
