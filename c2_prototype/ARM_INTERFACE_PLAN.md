# Arm interface plan — Nucleo-F446RE / DRV8825 / MG995

Known hardware from Kyler: Nucleo-F446RE, DRV8825 drivers, NEMA 17 steppers and
possible MG995 servos for other joints/gripper. Joint-to-motor assignments, gear
ratios, limits, homing and feedback are not yet specified. The GUI shows these
parts but retains example joint names and preview-only output. No arm bytes are
currently sent. Do not interpret the normalized 20% preview as a calibrated speed.

## Responsibilities and proposed connection

```text
Next arm bench milestone:
C2 Python → USB serial → Nucleo firmware → STEP/DIR drivers + servo PWM

Onboard-compute milestone:
Xbox → C2 input/intent node → Wi-Fi/router → onboard arm supervisor
      → USB serial arm bridge → Nucleo → drivers/motors
Nucleo state/limits/faults → onboard computer → C2
```

Start by configuring a versioned serial exchange on the Nucleo's ST-LINK virtual
COM port. The F446RE's default board routing supports target USART2 through ST-LINK;
check the actual solder-bridge configuration against ST's manual. This avoids
inventing a Wi-Fi interface on a board that is not itself a wireless rover link.
[ST UM1724, USART communication](https://www.st.com/resource/en/user_manual/dm00105823.pdf).

C2 requests a joint jog or goal. The onboard supervisor decides ownership, valid
mode and permitted limits. The Nucleo generates the actual pulse timing using
hardware timers, enforces acceleration and joint limits, reads limit switches and
faults, and expires commands locally. Python/ROS/Wi-Fi must not time individual
step edges. When onboard compute is introduced it becomes the sole serial owner;
do not leave C2 and another script competing for the same MCU.

## Motor handling

| Hardware | MCU responsibility | Needed from arm team |
|---|---|---|
| DRV8825 + stepper | STEP/DIR, enable, acceleration, homing and fault input | Exact carrier, phase-current rating, step angle, microstep configuration, gearing, joint travel and pin allocation |
| MG995 servo | Local bounded PWM pulse generation and rate-limited targets | Exact servo variant, supply/current needs, safe pulse/angle range, mechanical endpoints and whether any external feedback exists |
| Limit switches/encoders | Debounce, active-level validation, fault detection, state reporting | Locations, wiring, normally-open/closed behavior, counts and joint zero definition |

DRV8825 uses STEP/DIR and supports microstepping. Its carrier current limit must
be set from the actual sense resistors and motor phase-current rating. NEMA 17 is
a mechanical frame size, not sufficient electrical configuration. Give the servo
its own appropriately rated supply with common signal ground; do not power it
from a Nucleo GPIO. [TI DRV8825 datasheet](https://www.ti.com/lit/ds/symlink/drv8825.pdf).

Do not equate commanded step count with measured angle: a stepper can miss steps.
A normal servo command also does not return actual joint position to C2. Telemetry
must label each value as measured, estimated from steps, or merely commanded.

## Draft protocol contract to agree before writing motion firmware

This is a proposal, not a protocol claimed to exist on Kyler's board. Start with
115200 8N1 USB serial; bounded frames with explicit version, length and CRC, and
resynchronization after corruption. Use a fresh session and a board-generated boot
identity, increasing command sequence, and a state epoch that changes on timeout,
stop and reset. The receiver must reject stale/duplicate commands before motion.

| Message | Contents / behavior |
|---|---|
| HELLO / CAPABILITIES | Protocol/build version, boot/session identity, joint IDs, supported modes and configured limits; no motion |
| ENABLE request + ACK | Explicit disabled → enabled transition; zero command required; homing policy and faults checked locally |
| JOINT_JOG | Joint ID, requested rad/s (or gripper unit), sequence and short lease; initially one joint at a time |
| JOINT_GOAL | Calibrated joint target plus velocity/acceleration limits; later milestone after jogging/homing |
| STOP / DISABLE | Cancel current requests and queued goals; return explicit stop state |
| RESET | Clear a recoverable latched stop while remaining disabled; never resume old goals |
| STATE | Accepted sequence, enabled/mode, per-joint position and validity/source, limit switches, faults, homed flags and MCU uptime |

Proposed continuous jog update is 20 Hz with an initial 250 ms receive watchdog,
to be tested with the mechanics. Keep lease expiry on the MCU's monotonic clock;
a diagnostic heartbeat must not preserve the last moving command. Reject invalid
joint IDs, nonfinite values, unknown units and commands outside configured bounds.
Rate limits belong on the MCU too. CRC protects against transmission corruption;
it does not authenticate a remote operator.

Arm STOP cannot blindly mean "remove all torque": a gravity-loaded joint may fall.
Agree a per-joint stop/hold/brake policy with the mechanical team. Separate a normal
controlled stop from the physical emergency-power system. The GUI needs feedback
about which stop state was actually reached, not just that a button was pressed.

## First arm acceptance test

1. Agree one joint ID, safe travel, direction, ratio/current settings and MCU pins.
2. With drivers disabled, exchange HELLO/state and verify malformed/unknown joint
   messages are rejected and reconnect never enables motion.
3. Support the mechanism, test the limit inputs manually, then jog one unloaded
   joint at a low configured rate. Check direction, release-to-stop and travel limits.
4. Unplug the serial cable while jogging; confirm local stop behavior and no restart
   after reconnect. Check driver fault and lost-homing state handling.
5. Add MG995 output only after servo supply and mechanical endpoints are verified.
6. Replace the desktop serial owner with the onboard ROS bridge; keep the same MCU
   enforcement. Add MoveIt trajectories only after a calibrated robot model and
   joint-state/controller interfaces exist.

## ROS 2 stage

Ubuntu 24.04 / ROS 2 Jazzy is the planned software platform, not a motor protocol.
An Xbox can feed Python directly or a ROS joystick node. Both should produce the
same operator intent through one authority gate. The onboard arm bridge translates
validated intents to the Nucleo protocol. Use sensor_msgs/JointState only with clear
position-validity semantics; do not publish invented measurements. A later
FollowJointTrajectory controller can serve MoveIt after limits, homing and timing
are established. The existing [ROS plan](ROS2_INTERFACE_PLAN.md) covers the wider
C2/rover topics, video, GPS and command ownership.
