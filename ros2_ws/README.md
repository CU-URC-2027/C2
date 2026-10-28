# ROS 2 chassis prototype — Ubuntu 24.04 / Jazzy

This separate workspace adds a C2 operator/dashboard and an onboard chassis bridge.
The original `../c2_prototype/` remains the morning motor-test app.
**Host-side tests pass; actual colcon/ROS execution is pending an Ubuntu installation.**

## Build and verify

First follow [Ubuntu setup](../docs/UBUNTU_SETUP.md). In Ubuntu, using system Python:

```bash
source /opt/ros/jazzy/setup.bash
cd ~/projects/C2/ros2_ws
colcon build --symlink-install
source install/setup.bash
python3 -m unittest discover -s src/urc_c2_chassis/test -v
ros2 run urc_c2_chassis smoke_test
```

The smoke test forces a loopback-only mock regardless of the `mock` parameter and
uses an isolated namespace. It exercises actual ROS message serialization and topics,
enable, drive, release, STOP/reset, and input expiry. It must print PASS before moving
to a real endpoint. The Python suite uses hidden Tk windows; a display/WSLg is needed
for GUI tests. Headless Ubuntu can use `xvfb-run` after installing `xvfb`. Skipped GUI
tests are not a GUI pass. No tests contact physical motors.

## Run a simulated chassis

In **each** Ubuntu terminal:

```bash
source /opt/ros/jazzy/setup.bash
cd ~/projects/C2/ros2_ws
source install/setup.bash
export ROS_DOMAIN_ID=27
```

Domain 27 is an example for the team to agree on, not a security boundary.

Terminal 1 (OC role, defaults to a local mock):

```bash
ros2 run urc_c2_chassis chassis_bridge --ros-args -r __ns:=/rover1
```

Terminal 2 (C2 role):

```bash
ros2 run urc_c2_chassis c2_operator --ros-args -r __ns:=/rover1
```

1. Wait for **LOCAL MOCK** and MCU-ready feedback. Click **Claim control**.
2. Use Sliders initially. Raw T/S and the yellow input arrow should move while
   disarmed. This arrow is an input display, not measured rover displacement.
3. Set both sliders to zero and release Space. Click **Enable** and wait for both
   OC and MCU enabled feedback. Move a slider while holding **Space**. Release
   Space to request zero movement even if the slider is still deflected.
4. For Xbox, choose Xbox, center the left stick and release LB before enabling.
   Use the left stick for throttle/steering and **LB** for hold-to-drive. Selecting
   another source disarms. Controller samples are shown before enabling.
5. **Disarm** disables; **STOP/Esc** latches STOP; **Reset STOP** only clears the
   latch while disabled. Enable remains a separate action. Loss of window focus
   disarms. Lost OC feedback or an OC restart requires Reset STOP and deliberate enable.
6. **Save run** exports recent input/feedback rows to `captures/ros-chassis-*.jsonl`
   under the directory from which you started the app. Records include receipt UTC,
   monotonic time, counts, validity and applied command. The buffer holds 6000 samples
   (about five minutes at 20 Hz); save between trials. It is not a full mission recorder.

Only the existing pygame adapter owns the Xbox device. Do not simultaneously run
`joy/game_controller_node`, the Windows bench app, and this operator against it.
ROS joy is a possible later adapter, not a prerequisite for Python → ROS input.

## Real R4 endpoint, only after bench acceptance

Install the existing guarded companion firmware using its
[firmware guide](../c2_prototype/firmware/README.md). Close the direct C2 connection
and stop the mock bridge before starting the real bridge. Raise wheels and arrange
the physical power disconnect as described in [this week's plan](../docs/THIS_WEEK_PLAN.md).

On the OC machine, after sourcing the workspace:

```bash
read -r -p 'R4 IPv4 address from the router: ' ROVER_IP
ros2 run urc_c2_chassis chassis_bridge --ros-args -r __ns:=/rover1 -p mock:=false -p rover_host:="$ROVER_IP" -p rover_port:=4210
```

Run the operator on C2 with the same ROS domain and namespace. Both machines need
the same interface package. Only OC talks UDP to the Arduino. A router routes traffic;
it does not translate ROS into Arduino commands. Before enabling, verify the dashboard
says REAL CHASSIS, has fresh returned state, and shows the MCU disabled.

If the MCU link faults, stop the bridge, verify the rover is stopped, and restart the
bridge to establish a new connection. Reclaim and reset/enable deliberately; there is
no automatic reconnect/rearm loop. GUI close requests STOP, but receiver timeouts remain
necessary if a close packet is lost. A ROS or UDP STOP is not a hardware emergency stop.

## Interface contract

| Topic (relative to namespace) | Type | Meaning |
| --- | --- | --- |
| `c2/drive_intent` | `urc_c2_interfaces/DriveIntent` | Claim, input, enable, disarm, STOP or reset; normalized throttle/steering and deadman |
| `chassis/state` | `urc_c2_interfaces/ChassisState` | OC authority, returned MCU state/age, applied PWM, counts and validity |

Input is normalized [-1,1], forward throttle positive and right steering positive,
matching the existing bench convention. OC applies the 25% wheel cap and the existing
left/right mixing. These are not calibrated body velocities. A later velocity adapter
must explicitly convert to ROS forward/left-positive yaw convention and use wheel geometry.

The OC rotates short-lived challenges. Commands echo the OC boot, current challenge,
owner session, sequence and enable epoch. The 250 ms challenge acceptance limit bounds
delay without subtracting clocks on different machines. Input expiry is also 250 ms
at OC; the MCU has its independent nominal 250 ms timeout. These layers can accumulate
latency: do not interpret either number as total physical stopping time.

QoS is best effort, volatile, latest-sample depth 1, 250 ms lifespan. Non-motion
requests such as Enable may be dropped; the UI says request published and requires
returned state for confirmation. Retry an enable only while neutral and disabled.
STOP is repeated while the operator remains stopped and owns fresh feedback.
Loss of messages must stop movement rather than replay old enable state.

Ownership/challenges prevent accidental replay, **not hostile access**. Run on the
team's private test network. ROS authentication/authorization is future work.

Counts are FL/RL/FR/RR. Always use `encoder_valid` and `encoder_rate_valid`; an invalid
numeric slot contains zero only because the message field requires a number. Mock
encoders are invalid. Rates are unsigned pulses/s calculated from OC receipt intervals,
not motor RPM or calibrated odometry. State receipt time is not MCU capture time.

## Implementation boundaries

`c2_operator` combines Tk dashboard and operator logic in one process so a stalled GUI
stops publication. `chassis_bridge` combines the tested supervisor policy and the MCU
adapter in one OC process. This is the minimal chassis integration; Liam's eventual
separate supervisor, dashboard, arm, GPS and camera nodes remain a roadmap.

`vendor/` pins four small adapters from `c2_prototype/` at commit `6ae96d1`: core,
Xbox, RoverLink and MockRover. Only MockRover's import was changed to be package-relative.
This avoids changing the bench app during migration. Review and consolidate adapters
after both paths pass hardware acceptance; do not silently diverge the firmware protocol.

Maintainer email placeholders must be replaced by the team before release. The package
license metadata does not grant an open-source license; the repository had no selected
license to inherit. No license choice was made on the team's behalf.
