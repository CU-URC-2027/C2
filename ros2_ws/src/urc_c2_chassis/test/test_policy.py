import math
import unittest
from urc_c2_chassis.policy import Supervisor, EncoderRates, Intent, CLAIM, INPUT, ENABLE, STOP, RESET


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.gate = Supervisor()
        self.seq = 0

    def packet(self, op, now, **changes):
        self.seq += 1
        p = Intent(session='a'*32, oc_boot=self.gate.boot, sequence=self.seq,
                   challenge=self.gate.challenge(now), epoch=self.gate.epoch, operation=op)
        for key, value in changes.items():
            setattr(p, key, value)
        return p

    def receive(self, op, now, **changes):
        return self.gate.receive(self.packet(op, now, **changes), now, True, False, False)

    def test_claim_neutral_enable_deadman_and_cap(self):
        self.assertFalse(self.receive(ENABLE, 1))
        self.assertTrue(self.receive(CLAIM, 1.1))
        self.assertFalse(self.gate.control.armed)
        self.assertFalse(self.receive(ENABLE, 1.2, throttle=.4))
        self.assertTrue(self.receive(ENABLE, 1.3))
        self.receive(INPUT, 1.4, throttle=1.0, steering=1.0, deadman=True)
        out = self.gate.tick(1.4)
        self.assertEqual(out['left'], .25)
        self.assertEqual(out['right'], 0)
        self.receive(INPUT, 1.5, throttle=1.0, deadman=False)
        self.assertEqual(self.gate.tick(1.5)['left'], 0)

    def test_timeout_invalidates_old_enable_and_input(self):
        self.receive(CLAIM, 1)
        self.receive(ENABLE, 1.1)
        old_epoch = self.gate.epoch
        self.gate.tick(1.36)
        self.assertFalse(self.gate.control.armed)
        self.assertFalse(self.receive(ENABLE, 1.4, epoch=old_epoch))
        self.assertTrue(self.receive(INPUT, 1.5))
        self.assertFalse(self.gate.control.armed)

    def test_delay_duplicates_wrong_boot_and_invalid_numbers(self):
        self.receive(CLAIM, 1)
        old = self.packet(ENABLE, 1.1)
        self.assertFalse(self.gate.receive(old, 1.36, True, False, False))
        for changes in ({'throttle': math.nan}, {'steering': 2.0}, {'oc_boot': 'wrong'}, {'session': 'b'*32}):
            self.assertFalse(self.receive(INPUT, 1.4, **changes))
        p = self.packet(INPUT, 1.5)
        self.assertTrue(self.gate.receive(p, 1.5, True, False, False))
        self.assertFalse(self.gate.receive(p, 1.6, True, False, False))

    def test_stop_reset_and_owner_replacement(self):
        self.receive(CLAIM, 1)
        self.receive(ENABLE, 1.1)
        self.assertFalse(self.receive(CLAIM, 1.2, session='b'*32))
        self.receive(STOP, 1.3)
        self.assertFalse(self.receive(ENABLE, 1.4))
        self.receive(RESET, 1.5)
        self.assertFalse(self.gate.control.armed)
        self.assertFalse(self.gate.control.stopped)
        self.assertFalse(self.receive(CLAIM, 1.6, session='b'*32))
        self.assertTrue(self.receive(CLAIM, 2.6, session='b'*32))

    def test_mcu_feedback_required_for_enable(self):
        self.receive(CLAIM, 1)
        for ready, enabled, stopped in ((False, False, False), (True, True, False), (True, False, True)):
            self.assertFalse(self.gate.receive(self.packet(ENABLE, 1.1), 1.1, ready, enabled, stopped))
        self.assertFalse(self.gate.control.armed)

    def test_counts_rates_null_rollover_reset_and_gap(self):
        rates = EncoderRates()
        rates.update([10, None, 0xfffffffe, None], 1)
        self.assertFalse(any(rates.valid))
        rates.update([20, None, 2, None], 1.1)
        self.assertEqual(rates.valid, [True, False, True, False])
        self.assertAlmostEqual(rates.rates[0], 100)
        self.assertAlmostEqual(rates.rates[2], 40)
        rates.update([0, None, 3, None], 1.2)
        self.assertFalse(rates.valid[0])
        rates.update([1, None, 4, None], 2)
        self.assertFalse(any(rates.valid))


if __name__ == '__main__':
    unittest.main()
