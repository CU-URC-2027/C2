# C2 feedback on the physical-prototype interface draft

Prepared for discussion with Liam, 27 October 2026. These are proposed agreements,
not claims that all interfaces are implemented or hardware-tested. Reviewed all four
pages of `C:\Users\Cutle\Downloads\URC_interface.pdf`. No colored highlights or PDF
highlight annotations were visible in this export; the interface headings and field
lists below are the review targets. The original PDF has not been edited.

## Suggested opening message

I agree with C2 sending operator intent, OC owning command validation and chassis
conversion, and Arduino owning the final motor outputs and local timeout. My main
change for this week's prototype is to explicitly separate open-loop PWM driving
from the later encoder-based speed-control interface. We currently have two paired
drive outputs, not four independently controlled motors. We should still display
four encoder channels with validity flags, and never treat missing measurements
as zero speed. Below are my proposed ownership and field definitions.

## Page 1: motion request fields and units

- Joint ownership of the message definition: C2 implements publication; OC implements
  validation and consumption. Put one versioned ROS interface package in the shared
  contract so the two implementations cannot silently diverge.
- Long-term agreement: `forward_mps` is positive forward in the rover body frame;
  `turn_radps` is positive left/counterclockwise viewed from above. Label the frame
  `base_link`. Standard ROS body axes are x forward, y left, z up. The present bench
  steering convention is positive right; an explicit conversion is required.
- This week's contract uses normalized throttle/steering with bounded PWM outputs.
  Do not rename a joystick fraction or PWM value to m/s or rad/s. Choose this mode
  explicitly and report it as `OPEN_LOOP_PWM`. Later `WHEEL_SPEED` mode requires
  calibrated encoders and a speed controller, not just a message-field change.
- Agree on maximum forward/reverse speed, yaw rate, acceleration and wheel speed
  before using physical velocity commands. Hardware testing must determine these;
  25% PWM is not a measured speed limit.

## Page 1: command ID and enable state

- C2 owns a new session ID on process start and a monotonically increasing command
  sequence for each new input sample. Duplicates or lower sequences do not refresh
  motion permission. OC owns accepted ownership and its restart/enable generation.
- Rename outbound `enabled` to `enable_requested`, or use explicit ENABLE/DISARM/
  STOP/RESET operations. The GUI cannot declare that the Arduino is actually enabled.
- Include a hold-to-drive/deadman indication. Enable requires neutral sticks and a
  released hold. Releasing the hold requests zero; STOP/disarm withdraws permission.
- Report OC authorization and MCU-confirmed enable separately. On loss of feedback,
  show MCU state as stale/unknown rather than treating the last state as current.
- Reset STOP must leave the system disabled. A timeout, restart or new connection
  must require deliberate re-enable; renewed telemetry alone cannot restore motion.
- Keep one active input owner. Xbox versus GUI controls must not compete; later RC
  and autonomy need an explicitly agreed priority and takeover policy.
- Session/sequence fields do not prove freshness after network buffering. Keep the
  existing ROS prototype's receiver-issued short-lived challenge and enable epoch,
  or agree on another bounded-age mechanism. A receipt timer alone cannot detect an
  old packet arriving for the first time. These fields are not authentication.

## Pages 1-2: telemetry ownership and what C2 needs

| Data | Owner/source | C2 interpretation |
| --- | --- | --- |
| Operator body request | C2 | What the operator asked for |
| Wheel/side targets | OC | What OC calculated after its limits |
| Applied target/PWM | Arduino | What its controller applied after local limits |
| Encoder counts, sample time, validity | Arduino | Sensor evidence, not proof of signed speed |
| Calibrated measured speed | Arduino speed controller, once implemented | rad/s at output wheel with documented direction validity |
| OC acceptance, source ownership and OC faults | OC | Why an operator request was accepted or refused |
| MCU enable/controller state and MCU faults | Arduino, forwarded by OC | Last confirmed local controller state |
| Link ages and timeouts | Receiver of each link | Freshness of that specific link/sample |
| Display, run annotation and requested telemetry set | C2, agreed with OC | Operator-facing presentation |

Keep requested, limited/applied and measured values distinct. Return target-limited
flags and reasons. Use named wheel fields or a fixed documented FL, RL, FR, RR order.
Four physical wheel measurements are useful even though the left pair shares one
command and the right pair shares one command.

Minimum prototype telemetry: protocol version, OC and MCU boot/session identity,
last accepted C2 command ID, last MCU-applied command ID, controller mode, OC enable,
MCU enable with validity, STOP latch, applied throttle/steering or left/right PWM,
four raw counts with validity, link ages, and structured faults.

Do not label an OC receipt acknowledgment `last_applied_command_id`. Preserve the
mapping from the C2 request to the OC-to-MCU sequence; only report MCU application
after MCU confirmation. Applied means the software updated its output state, not
that a wheel reached its target or even moved. Target attainment requires measurements.

Suggested faults contain `source`, `code`, `severity`, `latched`, command identity,
and time. Examples: `C2_INPUT_TIMEOUT`, `MCU_LINK_STALE`, `ENABLE_NOT_CONFIRMED`, and
`ENCODER_UNAVAILABLE`. C2 should show the reason enable was refused and retain the
first-fault evidence even if STOP traffic subsequently changes the MCU reason.

## Page 2: freshness rules and ROS transport

Proposed initial bench values, subject to measured loop/network timing:

| Path | Normal cadence | Initial expiry policy |
| --- | --- | --- |
| C2 to OC input | 20 Hz / 50 ms | Disable on 250 ms without a valid fresh input |
| OC to MCU drive | 20 Hz / 50 ms | MCU disables after nominal 250 ms without valid drive renewal |
| MCU feedback | Approximately 10 Hz periodic, plus command responses | Bridge faults on 350 ms without fresh accepted feedback/acknowledgment |
| OC to C2 state | 20 Hz / 50 ms | C2 inhibits input on 350 ms without fresh OC state |

These mirror the initial implementation; the stale-link events from the bench mean
we need timing logs before signing them off. Do not increase thresholds just to hide
a blocking task. Software watchdog timing is not a guaranteed mechanical stopping time,
and multiple watchdog stages can add delay.

Only newer valid commands from the current owner/session renew motion. Status polling,
duplicate packets, malformed packets and unrelated GPS/video data must not renew it.
OC must stop forwarding motion once C2 input expires, even if its MCU connection works.

Specify two ages at C2: time since fresh OC feedback, and the MCU/sensor age reported by
OC. Refreshing an OC message must not make an old encoder sample look new. Include MCU
sample counter, boot ID and capture timestamp. Raw clocks on different computers must
not be subtracted without synchronization; initially use local monotonic receipt timers
and clearly label capture times by clock domain. Elapsed age since OC receipt must also
be considered when displaying downstream data; unsynchronized transit delay remains
unknown rather than being presented as zero.

Agree on topics, namespace, ROS domain, units and QoS together. Existing experimental
topics are `c2/drive_intent` and `chassis/state`, normally under `/rover1`. Current
prototype QoS is best effort, volatile, depth 1, lifespan 250 ms. This is provisional:
test discovery and loss on the actual router. Latest input should not be replayed from
a backlog. Enable/reset need explicit confirmation and bounded retry behavior; a
successful publish is not acknowledgment. Reliable transport alone does not make an
old enable request safe. Application timeouts remain mandatory.

## Pages 2-3: OC to Arduino targets, limits and ordering

- The present wiring has two independent PWM commands: left and right. OC can expose
  four named targets, but FL=RL and FR=RR under the current actuator arrangement.
  Four independent wheel controllers require changed wiring/control architecture.
- Keep named FL/RL/FR/RR order and define positive wheel motion as driving the rover
  forward, accounting for opposite motor mounting/polarity in the hardware mapping.
- OC owns body-to-wheel conversion and wheel geometry. Arduino owns output limiting,
  driver enable, local timeout and, later, the speed controller. Matthew owns the
  physical pin map and encoder calibration in coordination with OC.
- Proposed limits policy: OC scales valid requests to agreed operational limits,
  preserving left/right ratio where appropriate, and reports limiting. Arduino rejects
  malformed/out-of-contract commands and enforces its own final output limit. Invalid
  packets do not keep its watchdog alive. Stop/timeout disable must not wait for a
  normal acceleration ramp. Define coast/brake behavior separately and measure it.
- `applied_target` means the target after local limits/ramping, not the untouched
  request. Report actual PWM separately from a speed setpoint when speed mode exists.

## Pages 3-4: encoder validity, acknowledgments and watchdogs

Encoder readings currently do not gate open-loop drive. Counts can be unavailable
without preventing a bounded bench command; this should be a visible warning. That
is different from missing MCU acknowledgments, which must still inhibit motion.
For future closed-loop speed mode, invalid required speed feedback should stop the
affected drive system; never silently fall back to open-loop PWM.

Single-channel pulses do not independently establish rotation direction. Calibration
must establish counts per output-wheel revolution and timing, with explicit direction
validity. If speed is only unsigned, say so rather than calculating signed target error.
Show N/A for invalid data; do not plot a false zero or calculate error from it.

The watchdog must be checked continuously in the main loop or an appropriate control
task; 250 ms is the silence threshold, not how often the code checks for packets.
Keep the PDF's rule: timeout clears targets/disables drivers, reports COMMAND_TIMEOUT,
and recovery stays disabled until a new authorized enable. Arduino reset starts disabled.
The current MCU watchdog is cooperative; blocking peripheral calls can delay it.

## Acceptance tests and decisions for tonight

Agree tonight on: prototype mode (open-loop PWM first), ownership, sign/units, paired
outputs, message schema, enable/STOP semantics, freshness policy, fault reporting,
and what is deferred. Physical speed limits and calibration remain measured inputs.

Stage 1: stable disabled telemetry; enable at neutral; hold/release; forward/reverse;
left/right; STOP/reset; disconnect controller; kill C2; kill OC; interrupt Wi-Fi;
restart MCU; verify no automatic re-enable and save timing/state logs. Measure motor
signals and physical response separately. Retain the physical power cutoff.

Stage 2: confirm the actual pin map, measure counts for known wheel rotations, validate
sampling/rates and missing-channel reporting. Resolve the A2 conflict between our old
sonar assignment and Matthew's new front-left encoder wiring before powered tests.

Stage 3: implement calibrated speed control and time-aligned target-versus-measured
speed error. A joystick/PWM value cannot be subtracted from rad/s to produce a valid
tracking error. Command integration remains a model, not measured odometry.

Current status: direct C2/Arduino software and mock tests exist; real motor motion has
not been established. A separate ROS workspace has host-side tests but has not been
built/run under Ubuntu/Jazzy on this laptop. Four-wheel closed-loop speed control,
signed speed measurements and the complete C2-OC-hardware route are not validated.

References:
- Source draft: `C:\Users\Cutle\Downloads\URC_interface.pdf`, pages 1-4.
- ROS units/frames: https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst
- Jazzy QoS: https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst
- Existing implementation: `c2_prototype/firmware/mini_rover_c2/`, `c2_prototype/rover_link.py`.
- Experimental ROS schema: `ros2_ws/src/urc_c2_interfaces/msg/`.
