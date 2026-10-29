import time
import unittest
from urc_c2_chassis.bridge import ChassisBridge
from urc_c2_chassis.policy import Intent, CLAIM, INPUT, ENABLE, STOP, RESET


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ChassisBridge()
        self.seq = 0
        self.pump(.15)

    def tearDown(self):
        self.bridge.close()

    def send(self, op, t=0, s=0, held=False):
        now = time.monotonic()
        self.seq += 1
        gate = self.bridge.gate
        p = Intent(session='a'*32, oc_boot=gate.boot, sequence=self.seq,
                   challenge=gate.challenge(now), epoch=gate.epoch, operation=op,
                   throttle=t, steering=s, deadman=held)
        return self.bridge.receive(p, now)

    def pump(self, duration, drive=None):
        until = time.monotonic()+duration
        while time.monotonic() < until:
            if drive:
                self.send(INPUT, *drive)
            self.state = self.bridge.tick()
            time.sleep(.015)

    def start_drive(self):
        self.assertTrue(self.send(CLAIM))
        self.assertTrue(self.send(ENABLE))
        self.pump(.16, (.5, 0, True))
        self.assertTrue(self.state['mcu_enabled'])
        self.assertGreater(self.state['applied_throttle_pwm'], 0)

    def test_full_path_drive_release_stop_reset(self):
        self.start_drive()
        self.pump(.12, (.5, 0, False))
        self.assertEqual(self.state['applied_throttle_pwm'], 0)
        self.assertTrue(self.send(STOP))
        self.pump(.12)
        self.assertFalse(self.state['mcu_enabled'])
        self.assertTrue(self.state['mcu_stopped'])
        self.assertTrue(self.send(RESET))
        self.pump(.12)
        self.assertFalse(self.state['mcu_enabled'])
        self.assertFalse(self.state['mcu_stopped'])
        self.assertFalse(any(self.state['encoder_valid']))

    def test_c2_failure_stops_even_when_oc_keeps_running(self):
        self.start_drive()
        self.pump(.4)
        self.assertFalse(self.state['supervisor_enabled'])
        self.assertFalse(self.state['mcu_enabled'])
        self.pump(.12, (.5, 0, True))
        self.assertFalse(self.state['mcu_enabled'])

    def test_oc_freeze_uses_independent_mcu_timeout(self):
        self.start_drive()
        time.sleep(.32)
        self.assertFalse(self.bridge.mock.enabled)
        self.pump(.1)
        self.assertFalse(self.state['mcu_enabled'])

    def test_mcu_return_loss_does_not_auto_recover(self):
        self.start_drive()
        self.bridge.mock.silent = True
        self.pump(.55, (.5, 0, True))
        self.assertFalse(self.state['mcu_ready'])
        self.assertFalse(self.state['supervisor_enabled'])
        self.bridge.mock.silent = False
        self.pump(.15, (.5, 0, True))
        self.assertFalse(self.state['mcu_enabled'])


if __name__ == '__main__':
    unittest.main()
