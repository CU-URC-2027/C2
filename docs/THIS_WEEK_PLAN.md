# This week's chassis prototype

The morning motor test uses the existing Windows app in `c2_prototype/`.
Ubuntu and ROS are a separate integration track, not prerequisites for that test.
The ROS distribution name is **Jazzy**; the target OS is **Ubuntu 24.04**.

## 1. Preserve and prove the direct bench path

```
Xbox or sliders → existing C2 app → router/Wi-Fi → Uno R4 WiFi → motor drivers
                              ← acknowledgment / available encoder counts ←
```

The unchanged app and firmware are also saved in
`releases/c2-bench-v0.4.zip`, from commit `6ae96d1`. Use the top-level
`c2_prototype/`, not the older duplicate under `C2-team/c2_prototype/`.

1. Follow [the existing wiring/router instructions](../c2_prototype/NEXT_WEEK_SETUP.md).
   Confirm the **guarded companion firmware** is installed on Matthew's R4.
   His original unmodified sketch does not acknowledge the new protocol, so
   this app intentionally refuses to enable it. Launching C2 never uploads firmware.
2. Support the rover with wheels off the ground. Identify the physical motor-power
   disconnect, check supply/current limits and wiring with Matthew, and start with
   the existing 25% wheel-command limit. Keep the direct app as the only controller.
3. Launch `python c2_prototype/app.py` from the repository root. Verify raw Xbox
   values and the input vector move while disarmed. Connect using the R4's actual
   router-assigned IPv4 address and UDP port 4210; require returned disabled state.
4. Center sticks, release the drive hold, then enable. Hold LB and request a small
   forward movement. Check wheel direction before testing steering and reverse.
5. **Release-to-zero:** while the stick remains deflected, release LB. Verify the
   returned applied command becomes zero and observe what the wheels actually do.
   Zero PWM may coast; it is not proof of mechanical braking.
6. Test Disarm, STOP, Reset STOP, controller removal, loss of focus, C2 process
   termination, and Wi-Fi interruption individually. Reset must not cause motion.
   Reconnection must require deliberate enable. Measure actual stopping response;
   the nominal 250 ms MCU timeout is not a guaranteed physical stop time.

Record firmware revision, wiring, controller mapping, IP, returned state, and
pass/fail for each test. Stop the powered test if a stop/release test fails.
The existing [operator guide](../c2_prototype/operator_guide.txt) covers all panels.

## 2. Characterize encoders before claiming speed or odometry

Liam's proposed demonstration is Arduino → OC → C2 feedback. First establish what
the actual hardware measures:

- With motor drive disabled, record each reported starting count. Rotate one wheel
  by 1, 5 and 10 complete output-wheel revolutions; record ending count and repeat.
  Note the wheel, direction, gear stage and whether the encoder is on the motor shaft.
- Compute count difference / output-wheel revolutions. Compare repeated trials.
  Repeat in reverse: current single-channel counts are unsigned and cannot establish
  direction on their own. Do not infer direction from the joystick during coasting.
- Check stationary counts, low-command powered counts, resets, and dropped feedback.
  Missing feedback must show **N/A**, never a fabricated zero-speed reading.
- Current default firmware uses FL D0, RL D9, FR D11 and RR D13. With the R4 core
  previously checked, D9/D13 have no supported interrupt mapping; those channels
  are reported unavailable. Agree on a verified pin change before promising four
  working encoder channels. Do not change wiring immediately before the basic drive test.

The new ROS panel shows raw counts and unsigned pulses/second. Rate uses OC receipt
intervals, so Wi-Fi jitter affects it. Add MCU capture timestamps and calibrated
counts-per-revolution before PI speed control or measured wheel odometry.

## 3. Add ROS only after the local mock passes

```
C2 Ubuntu: Xbox/sliders → c2_operator (Tk dashboard + input checks)
                                      ↓ typed DriveIntent over ROS 2
OC Ubuntu:                 chassis_bridge (supervisor + MCU adapter)
                                      ↓ guarded UDP through router
                                  Uno R4 → motor drivers
                                      ↑ state / counts
C2 dashboard ← typed ChassisState ← OC bridge
```

The implementation lives in [ros2_ws](../ros2_ws/README.md), separate from the
morning app. For this week, two processes contain the four logical responsibilities;
splitting dashboard/operator and supervisor/bridge into separate nodes can follow.
The dashboard has no motor socket. One process owns the physical Xbox controller.
No virtual Xbox device is needed: sliders publish the same operator-intent messages.

1. After the motor test, install Ubuntu when ready using [the WSL guide](UBUNTU_SETUP.md).
2. Build the ROS workspace and run its forced-mock smoke test on one Ubuntu machine.
3. Run both ROS processes with the mock endpoint; check claim, enable, raw vector,
   hold/release, STOP, input timeout, and saved feedback. Sliders work without USB setup.
4. On the private router, test C2 and OC on separate computers using a matching ROS
   domain and namespace. Confirm discovery and returned state before motor connection.
   WSL's network setup can complicate discovery; do not assume same Wi-Fi proves ROS connectivity.
5. Close/disconnect the direct Windows app. Start the OC bridge in explicit real mode
   with the R4 address. Repeat the same raised-wheel acceptance tests, including killing
   C2 separately from killing the OC process. Only one bridge may own the Arduino.

The new messages are a **provisional team contract**. Send the `.msg` files to Liam
through the normal review process before integrating his implementation. This version
uses normalized throttle/steering, not a misleading metres-per-second `Twist` command.
Agree on wheel geometry, sign conventions and calibration before a velocity interface.

If ROS or WSL networking is not ready, demonstrate the verified direct drive path and
the separate ROS mock. Do not present mock encoder data as physical feedback.

## 4. Thursday review and next work

Suggested ten-minute review: two minutes architecture, four minutes drive and stop
demonstration, two minutes encoder observations, two minutes limitations/next steps.
Bring logs plus the frozen fallback, not only a live network demonstration.

Later milestones: encoder capture timing and calibrated odometry; closed-loop wheel
control; MoveIt/arm bridge with Nucleo-F446RE joint limits and homing; GPS fix validity
and measured odometry comparison; video timestamps and latency; mission recording.
The existing arm previews, GPS experiments and camera panels remain in the bench app.
They are not represented as implemented ROS nodes this week. RC requires a real receiver
interface and input arbitration; it is not a replacement transport for video/GPS.
