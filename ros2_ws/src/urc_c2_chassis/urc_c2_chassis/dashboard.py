"""Chassis-only ROS dashboard. Tk owns input and publication, never motor UDP."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from .policy import CLAIM, INPUT, ENABLE, DISARM, STOP, RESET


class Dashboard:
    def __init__(self, root, node, spin):
        self.root, self.node, self.spin = root, node, spin
        self.xbox = None
        self.space = False
        self.permit = False
        self.pending_stop = DISARM
        self.fault = False
        self.had_feedback = False
        self.last_boot = ''
        self.closed = False
        self.after_id = None
        self.records = deque(maxlen=6000)
        self.sample = (0.0, 0.0, False)
        self.buttons = {}
        root.title('URC C2 | ROS chassis prototype — onboard bridge required')
        root.geometry('1060x740')
        root.minsize(850, 650)
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='URC / ROS CHASSIS STATION', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        self.banner = ttk.Label(outer, text='WAITING FOR ONBOARD STATE • no direct Arduino connection')
        self.banner.pack(anchor='w', pady=8)
        row = ttk.Frame(outer)
        row.pack(fill='x')
        self.source = tk.StringVar(value='Sliders')
        self.menu = ttk.Combobox(row, textvariable=self.source, values=('Sliders', 'Xbox'), state='readonly', width=10)
        self.menu.pack(side='left')
        self.menu.bind('<<ComboboxSelected>>', self.change_source)
        for key, label, callback in (
            ('claim', 'Claim control', lambda: self.command(CLAIM)),
            ('enable', 'Enable', lambda: self.command(ENABLE)),
            ('disarm', 'Disarm', self.disarm),
            ('reset', 'Reset STOP', lambda: self.command(RESET)),
            ('stop', 'STOP / Esc', self.stop),
            ('save', 'Save run', self.save)):
            button = ttk.Button(row, text=label, command=callback)
            button.pack(side='left', padx=4)
            self.buttons[key] = button
        self.hint = ttk.Label(outer, text='Start the onboard mock bridge first. Claim → neutral/release hold → Enable → hold LB or Space.', wraplength=980)
        self.hint.pack(anchor='w', pady=10)
        self.throttle, self.steering = tk.DoubleVar(), tk.DoubleVar()
        self.sliders = []
        for label, variable in (('Throttle: reverse / forward', self.throttle), ('Steering: left / right', self.steering)):
            ttk.Label(outer, text=label).pack(anchor='w')
            slider = ttk.Scale(outer, from_=-1, to=1, variable=variable)
            slider.pack(fill='x', pady=(0, 6))
            self.sliders.append(slider)
        self.input_text = ttk.Label(outer, text='Input not sampled')
        self.input_text.pack(anchor='w')
        self.vector = tk.Canvas(outer, height=150, bg='#172e3f', highlightthickness=0)
        self.vector.pack(fill='x', pady=8)
        self.state_text = ttk.Label(outer, text='MCU state unknown', wraplength=980)
        self.state_text.pack(anchor='w', pady=5)
        self.encoder_text = ttk.Label(outer, text='Encoders unavailable', font=('Consolas', 12), justify='left')
        self.encoder_text.pack(anchor='w', pady=5)
        ttk.Label(outer, text='Encoder rate = unsigned pulses/s, not wheel speed. No arm, GPS or camera ROS nodes in this build.\nUse the preserved bench app for those existing panels.', wraplength=980).pack(anchor='w', pady=8)
        root.bind('<Escape>', lambda event: self.stop())
        root.bind('<FocusOut>', lambda event: root.after_idle(self.check_focus))
        root.bind_class('RosDriveKeys', '<KeyPress-space>', self.space_down)
        root.bind_class('RosDriveKeys', '<KeyRelease-space>', self.space_up)
        def keys(widget):
            widget.bindtags(('RosDriveKeys',)+widget.bindtags())
            for child in widget.winfo_children():
                keys(child)
        keys(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.loop()

    def owned(self):
        return self.node.fresh() and self.node.state.owner_session == self.node.session

    def space_down(self, event=None):
        self.space = True
        return 'break'

    def space_up(self, event=None):
        self.space = False
        return 'break'

    def check_focus(self):
        if not self.closed and not str(self.root.tk.call('focus')):
            self.disarm()

    def change_source(self, event=None):
        self.disarm()
        if self.xbox:
            self.xbox.close()
            self.xbox = None
        for slider in self.sliders:
            slider.config(state='disabled' if self.source.get() == 'Xbox' else 'normal')
        self.throttle.set(0)
        self.steering.set(0)
        if self.source.get() == 'Xbox':
            try:
                from .vendor.xbox import Xbox
                self.xbox = Xbox()
            except Exception as exc:
                self.hint.config(text=f'Xbox unavailable: {exc}. Select Sliders to test without it.')

    def command(self, operation):
        t, s, held = self.sample
        if operation == CLAIM:
            self.permit = False
            self.pending_stop = DISARM
            sent = self.node.send(CLAIM)
        elif not self.owned():
            self.hint.config(text='Need fresh onboard feedback and Claim control first.')
            return
        elif operation == ENABLE:
            if self.fault:
                self.hint.config(text='Feedback interruption: Reset STOP, then enable deliberately.')
                return
            if abs(t) >= .08 or abs(s) >= .08 or held:
                self.hint.config(text='Center sticks and release LB/Space before enabling.')
                return
            self.pending_stop = None
            self.permit = True
            sent = self.node.send(ENABLE, t, s, held)
        elif operation == RESET:
            if self.node.state.supervisor_enabled or self.node.state.mcu_enabled or not self.node.state.mcu_ready:
                self.hint.config(text='Reset needs confirmed disabled MCU feedback.')
                return
            self.fault = False
            self.permit = False
            self.pending_stop = DISARM
            sent = self.node.send(RESET)
        else:
            return
        self.hint.config(text='Request published; check returned state for confirmation.' if sent else 'No fresh onboard feedback; request not sent.')

    def disarm(self):
        self.permit = self.space = False
        if self.pending_stop != STOP:
            self.pending_stop = DISARM
        if self.owned():
            self.node.send(DISARM)

    def stop(self):
        self.permit = self.space = False
        self.pending_stop = STOP
        if self.owned():
            self.node.send(STOP)

    def read_input(self):
        if self.source.get() == 'Xbox':
            if not self.xbox:
                raise RuntimeError('Xbox unavailable; select Sliders, then Xbox to retry')
            t, s, held = self.xbox.read()
            self.throttle.set(t)
            self.steering.set(s)
            return t, s, held
        return self.throttle.get(), self.steering.get(), self.space

    def loop(self):
        if self.closed:
            return
        self.spin()
        try:
            self.sample = self.read_input()
            input_ok = True
        except Exception as exc:
            self.sample, input_ok = (0.0, 0.0, False), False
            self.disarm()
            self.hint.config(text=str(exc))
        t, s, held = self.sample
        self.input_text.config(text=f'{self.source.get()} input T {t:+.2f} / S {s:+.2f} • hold {held} • yellow vector is input, not measured velocity')
        self.vector.delete('all')
        cx, cy = max(100, self.vector.winfo_width()/2), 75
        self.vector.create_oval(cx-60, cy-60, cx+60, cy+60, outline='#6edac6')
        self.vector.create_line(cx, cy, cx+s*60, cy-t*60, fill='#ffc861', width=4, arrow='last', tags='input_arrow')
        if not self.node.fresh():
            if self.had_feedback:
                self.fault = True
                self.stop()
            self.banner.config(text='ONBOARD FEEDBACK STALE / UNKNOWN • movement disabled locally')
            self.state_text.config(text='MCU state unknown; no input heartbeats sent')
            self.encoder_text.config(text='FL / RL / FR / RR: unavailable (stale)')
        else:
            state = self.node.state
            if self.last_boot and self.last_boot != state.oc_boot:
                self.fault = True
                self.stop()
            self.last_boot, self.had_feedback = state.oc_boot, True
            self.banner.config(text=('LOCAL MOCK • no motors' if state.mock else 'REAL CHASSIS VIA ONBOARD BRIDGE') +
                               (' • this C2 owns input' if self.owned() else ' • control not claimed by this C2'))
            if self.owned():
                if self.pending_stop == STOP:
                    self.node.send(STOP)
                elif self.pending_stop == DISARM and (state.supervisor_enabled or state.mcu_enabled):
                    self.node.send(DISARM)
                elif input_ok:
                    self.node.send(INPUT, t, s, held and self.permit)
            applied = f'T {state.applied_throttle_pwm} / S {state.applied_steering_pwm}' if state.mcu_ready else 'UNKNOWN'
            self.state_text.config(text=f'OC enabled: {state.supervisor_enabled} | MCU ready: {state.mcu_ready} / enabled: {state.mcu_enabled}\n'
                                  f'STOP: {state.stop_latched or state.mcu_stopped} | applied PWM {applied} | MCU age {state.mcu_age_s:.3f}s\n{state.reason}')
            lines = ['Wheel    Count      Unsigned pulses/s']
            for i, name in enumerate(('FL', 'RL', 'FR', 'RR')):
                count = str(state.encoder_counts[i]) if state.encoder_valid[i] else 'N/A'
                rate = f'{state.encoder_count_rate[i]:.1f}' if state.encoder_rate_valid[i] else 'N/A'
                lines.append(f'{name:5s} {count:>8s}      {rate:>8s}')
            self.encoder_text.config(text='\n'.join(lines))
            self.records.append(dict(receipt_utc=datetime.now(timezone.utc).isoformat(),
                                     receipt_monotonic_s=time.monotonic(), source=self.source.get(),
                                     throttle=t, steering=s, hold=held,
                                     state={name: self.json_value(getattr(state, name)) for name in state.get_fields_and_field_types()}))
        self.after_id = self.root.after(50, self.loop)

    @staticmethod
    def json_value(value):
        if isinstance(value, (str, bool, float, int)):
            return value
        return list(value)

    def save(self):
        if not self.records:
            self.hint.config(text='No received state to save yet.')
            return
        try:
            directory = Path.cwd()/'captures'
            directory.mkdir(exist_ok=True)
            path = directory/f'ros-chassis-{time.time_ns()}.jsonl'
            path.write_text(''.join(json.dumps(row, allow_nan=False)+'\n' for row in self.records), encoding='utf-8')
            self.hint.config(text=f'Saved {len(self.records)} recent records to {path}')
        except (OSError, ValueError) as exc:
            self.hint.config(text=f'Could not save: {exc}')

    def close(self):
        if self.closed:
            return
        self.stop()
        self.closed = True
        if self.after_id:
            self.root.after_cancel(self.after_id)
        if self.xbox:
            self.xbox.close()
        self.root.destroy()


def main(args=None):
    import rclpy
    from .ros_io import OperatorNode
    rclpy.init(args=args)
    node = OperatorNode()
    root = tk.Tk()
    app = Dashboard(root, node, lambda: rclpy.spin_once(node, timeout_sec=0))
    try:
        root.mainloop()
    finally:
        app.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
