"""Real hidden Tk widgets; fake ROS transport. No hardware or ROS installation."""
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from urc_c2_chassis.dashboard import Dashboard
from urc_c2_chassis.policy import CLAIM, INPUT, ENABLE, DISARM, STOP, RESET


class State(SimpleNamespace):
    def get_fields_and_field_types(self):
        return vars(self)


class FakeNode:
    session = 'a'*32

    def __init__(self):
        self.available = True
        self.sent = []
        self.state = State(owner_session='', oc_boot='boot1', mock=True,
                           supervisor_enabled=False, mcu_ready=True, mcu_enabled=False,
                           stop_latched=False, mcu_stopped=False, applied_throttle_pwm=0,
                           applied_steering_pwm=0, mcu_age_s=.01, reason='disabled',
                           encoder_counts=[12, 0, 34, 0], encoder_valid=[True, False, True, False],
                           encoder_count_rate=[10., 0., 20., 0.],
                           encoder_rate_valid=[True, False, True, False])

    def fresh(self):
        return self.available

    def send(self, op, *args):
        if not self.fresh():
            return False
        self.sent.append((op, *args))
        return True


class DashboardTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}; run with xvfb-run on headless Ubuntu')
        self.root.withdraw()
        self.node = FakeNode()
        self.app = Dashboard(self.root, self.node, lambda: None)
        self.root.after_cancel(self.app.after_id)

    def tearDown(self):
        if hasattr(self, 'app'):
            self.app.close()

    def step(self):
        self.app.loop()
        self.root.after_cancel(self.app.after_id)

    def own(self):
        self.node.state.owner_session = self.node.session

    def test_all_control_buttons_and_explicit_reset(self):
        self.app.buttons['claim'].invoke()
        self.assertEqual(self.node.sent[-1], (CLAIM,))
        self.own()
        self.app.buttons['enable'].invoke()
        self.assertEqual(self.node.sent[-1], (ENABLE, 0., 0., False))
        self.assertTrue(self.app.permit)
        self.app.buttons['disarm'].invoke()
        self.assertEqual(self.node.sent[-1], (DISARM,))
        self.assertFalse(self.app.permit)
        self.app.buttons['stop'].invoke()
        self.assertEqual(self.node.sent[-1], (STOP,))
        self.step()
        self.assertEqual(self.node.sent[-1], (STOP,))
        self.app.buttons['reset'].invoke()
        self.assertEqual(self.node.sent[-1], (RESET,))
        self.assertFalse(self.app.permit)

    def test_raw_vector_moves_disarmed_and_space_release_zero_hold(self):
        self.own()
        self.app.throttle.set(.6)
        self.app.steering.set(-.4)
        self.step()
        x1, y1, x2, y2 = self.app.vector.coords('input_arrow')
        self.assertLess(x2, x1)
        self.assertLess(y2, y1)
        self.assertIn('+0.60', self.app.input_text.cget('text'))
        self.assertEqual(self.node.sent[-1], (INPUT, .6, -.4, False))
        self.app.buttons['enable'].invoke()
        self.assertFalse(self.app.permit)  # nonneutral refused
        self.app.throttle.set(0)
        self.app.steering.set(0)
        self.step()
        self.app.buttons['enable'].invoke()
        self.app.space_down()
        self.app.throttle.set(.6)
        self.step()
        self.assertEqual(self.node.sent[-1], (INPUT, .6, 0., True))
        self.app.space_up()
        self.step()
        self.assertEqual(self.node.sent[-1], (INPUT, .6, 0., False))

    def test_feedback_loss_and_oc_restart_require_reset(self):
        self.own()
        self.app.buttons['enable'].invoke()
        self.node.available = False
        previous = len(self.node.sent)
        self.step()
        self.assertEqual(len(self.node.sent), previous)
        self.assertTrue(self.app.fault)
        self.assertFalse(self.app.permit)
        self.assertIn('stale', self.app.encoder_text.cget('text'))
        self.node.available = True
        self.step()
        self.assertEqual(self.node.sent[-1], (STOP,))
        self.app.buttons['enable'].invoke()
        self.assertFalse(self.app.permit)
        self.app.buttons['reset'].invoke()
        self.assertFalse(self.app.fault)
        self.node.state.oc_boot = 'boot2'
        self.step()
        self.assertTrue(self.app.fault)
        self.assertEqual(self.node.sent[-1], (STOP,))

    def test_encoder_missing_and_capture_export(self):
        self.assertIn('N/A', self.app.encoder_text.cget('text'))
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.app.buttons['save'].invoke()
                files = list(Path('captures').glob('*.jsonl'))
                self.assertEqual(len(files), 1)
                row = json.loads(files[0].read_text().splitlines()[0])
                self.assertEqual(row['state']['encoder_valid'], [True, False, True, False])
                self.assertIn('receipt_utc', row)
            finally:
                os.chdir(cwd)

    def test_xbox_disarmed_samples_disconnect_and_source_change(self):
        self.own()
        with patch('urc_c2_chassis.vendor.xbox.Xbox') as factory:
            pad = factory.return_value
            pad.read.return_value = (.75, -.5, False)
            self.app.source.set('Xbox')
            self.app.change_source()
            self.step()
            self.assertEqual(self.app.sample, (.75, -.5, False))
            self.assertAlmostEqual(self.app.throttle.get(), .75)
            self.assertEqual(self.node.sent[-1], (INPUT, .75, -.5, False))
            pad.read.side_effect = RuntimeError('Controller disconnected')
            self.app.permit = True
            self.step()
            self.assertFalse(self.app.permit)
            self.assertEqual(self.node.sent[-1], (DISARM,))
            self.app.source.set('Sliders')
            self.app.change_source()
            pad.close.assert_called_once()
            self.assertEqual(self.app.throttle.get(), 0)

    def test_reset_refused_while_mcu_enabled_and_close_sends_stop(self):
        self.own()
        self.node.state.mcu_enabled = True
        before = len(self.node.sent)
        self.app.buttons['reset'].invoke()
        self.assertEqual(len(self.node.sent), before)
        self.app.close()
        self.assertEqual(self.node.sent[-1], (STOP,))
        self.assertTrue(self.app.closed)


if __name__ == '__main__':
    unittest.main()
