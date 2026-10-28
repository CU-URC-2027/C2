"""Actual ROS serialization/topic round-trip. Run ONLY after colcon on Jazzy.

An isolated namespace and forced loopback mock prevent this from driving hardware.
"""
import secrets
import time
import rclpy
from rclpy.executors import SingleThreadedExecutor
from .bridge_node import BridgeNode
from .ros_io import OperatorNode
from .policy import CLAIM, INPUT, ENABLE, STOP, RESET


def main(args=None):
    rclpy.init(args=args)
    ns = '/c2_smoke_'+secrets.token_hex(4)
    bridge = BridgeNode(namespace=ns, force_mock=True)
    operator = OperatorNode(namespace=ns)
    executor = SingleThreadedExecutor()
    executor.add_node(bridge)
    executor.add_node(operator)

    def wait(predicate, send=None, limit=3):
        end = time.monotonic()+limit
        last_send = 0
        while time.monotonic() < end:
            executor.spin_once(timeout_sec=.01)
            if send and time.monotonic()-last_send >= .05:
                send()
                last_send = time.monotonic()
            if predicate():
                return
        raise AssertionError('ROS smoke condition timed out')

    try:
        wait(lambda: operator.fresh() and operator.state.mcu_ready)
        assert not operator.state.mcu_enabled
        wait(lambda: operator.state.owner_session == operator.session, lambda: operator.send(CLAIM))
        operator.send(ENABLE)
        wait(lambda: operator.state.mcu_enabled, lambda: operator.send(INPUT))
        wait(lambda: operator.state.applied_throttle_pwm > 0, lambda: operator.send(INPUT, .5, 0, True))
        wait(lambda: operator.state.applied_throttle_pwm == 0, lambda: operator.send(INPUT, .5, 0, False))
        operator.send(STOP)
        wait(lambda: operator.state.mcu_stopped and not operator.state.mcu_enabled)
        operator.send(RESET)
        wait(lambda: not operator.state.mcu_stopped and not operator.state.stop_latched)
        assert not operator.state.mcu_enabled
        operator.send(ENABLE)
        wait(lambda: operator.state.mcu_enabled, lambda: operator.send(INPUT))
        wait(lambda: operator.state.applied_throttle_pwm > 0, lambda: operator.send(INPUT, .5, 0, True))
        wait(lambda: not operator.state.supervisor_enabled and not operator.state.mcu_enabled)
        assert not any(operator.state.encoder_valid)  # Mock has no physical encoder data.
        print('PASS: ROS claim, enable, drive, release, STOP/reset, input expiry and invalid mock encoders')
    finally:
        operator.send(STOP)
        executor.remove_node(operator)
        executor.remove_node(bridge)
        operator.destroy_node()
        bridge.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
