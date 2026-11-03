# Connection recovery, saved rovers and browser PWM — experimental release

November 3, 2026. Both branches start from main `07b129d`; neither is hardware-validated.

| Component | Branch | Scope |
| --- | --- | --- |
| C2 browser/backend/mock | `fix/connection-recovery-discovery` | Disarm confirmation, discovery/profiles, diagnostics, 0–100% requested PWM |
| Uno R4 WiFi firmware | `experimental/arduino-connection-pwm` | Separate experimental sketch, physical 0–255 PWM range, discovery and timing |

The C2 branch intentionally retains main's Arduino files. For the matching experimental
sketch, switch a **separate checkout** to the Arduino branch. Do not copy the ROS vendor
adapters or historical `C2-team/` files between these branches. Main is not changed by
creating/pushing these branches. Read `docs/EXPERIMENTAL_ARDUINO.md` on the firmware branch.

## What changed

Unavailable gamepad samples no longer refresh valid-input freshness or repeatedly
send DISARM. Their sequence is consumed to reject replay; first loss disarms and
recovery stays disarmed. Browser controller identity, mapping/indices, error and focus
context are recorded separately from authority.

`RoverLink` treats repeated disable requests as one transition. It skips unnecessary
DISARM only after disabled state is confirmed and no later ARM/DRIVE is outstanding.
A pending shutdown records its first command sequence, session/epoch context, start
time and retries. Only valid same-session feedback at/after that sequence, with
disabled outputs (and STOP latched when requested), can confirm shutdown. Pre-request
disabled feedback cannot clear it. Retries are at most once per 150 ms and never move
the original 350 ms confirmation deadline. STOP escalation cannot downgrade to DISARM.
The 250 ms input/ARM/MCU-drive and 350 ms feedback guards are unchanged.

### November 3 timing follow-up

The original server could fault 156 ms into ARM because a pre-ARM PING was already
375 ms old. ARM now uses its own original 250 ms confirmation deadline; motion stays
inhibited until same-session feedback at/after ARM confirms enabled at the requested
epoch. Late confirmation cannot evade that deadline. Driving still requires both
reply and acknowledged-command ages below 350 ms. No send timestamp is rewritten.
PC pauses and the independent input/MCU watchdogs retain their original limits.

Browser state, tick records, file-log context and the pose model expose zero drive
and `enabled:false` while waiting, with `enable_requested:true`. The event/reason
says "Enable requested; waiting for rover confirmation" until confirmed. The existing
browser Enabling display uses that phase even when pre-ARM feedback ages.

Once a fault's STOP is confirmed, bounded PING traffic continues without clearing
the fault, resetting STOP or enabling. Diagnostics include `stop_confirmed`; command
age therefore measures ongoing communication rather than an intentionally idle STOP.
Reconnect/reset/enable remain deliberate, with no extra STOP press required.

The matching `recovery-v2` sketch uses compact guarded state replies and includes
detailed metadata/timings in at most one routine state per second while disabled
and after the receive queue drains. Detailed frames pause while armed. C2 retains the last
detail frame separately as `mcu_detail_state` with `mcu_detail_age_ms` since receipt;
never interpret those older counters as the current compact reply's measurements.
Identity/PWM/encoder/safety fields remain in every guarded state. Old firmware is
still accepted; detailed telemetry is optional and cannot refresh command authority.

Regressions reproduce all three 200/250/300 ms pre-ARM PING-age cases against the old
server and pass on this implementation. Checks also cover lost/late/wrong-epoch ARM
confirmation, inhibited displays/logs/model, retained detail sample age, fault-only
PING and a loopback fault/STOP/reconnect/reset/enable sequence. The firmware's native
stress model uses its actual scheduler/guard, 20 Hz commands, 25 ms receives plus a
35 ms delay every eleventh receive and 6 ms loop overhead. The old schedule sends
80 ms full replies; revised armed operation defers detailed replies and assumes
35 ms compact sends. Conservative maximum ACK ages are 356 ms old / 277 ms revised.
A sweep of assumed compact-send costs from 30–55 ms stays below 350 ms, with a
305 ms maximum. A separate idle-to-ARM case includes a 110 ms in-progress detail
send, 25 ms receive and 55 ms urgent reply. These are synthetic assumptions,
not measured board performance or proof that physical driving faults are resolved.

Final local checks: 76 backend tests; the shared verification also passed controller/
UI/JavaScript checks, 72 video-policy tests, 42 desktop, 21 Tk GUI, 16 ROS host,
10-second delayed-reply soak and native guard checks. Hardware/radio/Windows
acceptance is pending. No firmware upload or physical acceptance is implied.

Phases/readiness explain handshake, post-HELLO verification, Enable, pending disable,
STOP, degraded idle and faults. A returned MCU STOP offers Reset even if the browser's
local latch is clear; reset still needs fresh confirmed disabled feedback. Each new
connection archives the prior first fault instead of presenting it as a new fault;
Export snapshot includes up to eight archived sessions plus the current snapshot.
Diagnostics add pending-disarm identity/age/retries, command lag, two-second TX/state
RX rates, browser input context and last valid-input sequence. Arm preview is blocked
while a chassis transport is connected.

## Requested PWM is controlled from the browser

Drive's **Wheel PWM cap** selects 0–100% when the connected firmware supports the
full 8-bit range. Startup is 25%; a new connection retains at most 25%. Increasing
the cap while enabled disarms and requires deliberate re-enable at neutral. Zero
produces zero wheel PWM. Lowering the cap does not enable anything.

The MCU advertises `max_pwm` in actual guarded state feedback. Missing capability
means legacy 64-count/approximately 25% firmware: C2 limits the slider and validates
outgoing/returned mixed wheel commands against that ceiling. The physical host
ceiling is 255; the ROS/onboard adapter remains pinned to 25%. Selected percentages
map approximately to 0, 64, 128 and 255 counts for 0%, 25%, 50% and 100%. Full PWM
is duty cycle, not measured wheel speed or torque. Mixing/quantization cannot exceed
the selected per-wheel cap, including the odd 255-count full-range boundary.

The experimental MCU enforces the 8-bit envelope, session/epoch/sequence ownership
and watchdog independently. It does not store the browser's selected lower cap;
the trusted C2 backend enforces that requested cap before transmission. This is not
authentication against an arbitrary replacement controller on an untrusted network.

## Connect without typing the rover address each time

The browser talks to local Python on port 8870. Python sends guarded UDP to the
Arduino on its control port (default 4210), through the shared LAN/router. The
Arduino replies to Python's source address/ephemeral port. Software mock mode stays
on loopback and uses no router/Arduino. Network association, discovery, session
ownership and Enable are separate operations.

1. Join the PC and Arduino to the configured Wi-Fi. Discovery cannot supply Wi-Fi
   credentials or join networks. A router DHCP reservation can stabilize the address.
2. In Connections, **Find rovers** sends two `C2DISC1,<16 hex nonce>` probes over
   1.5 seconds to the selected address/port. Defaults are LAN broadcast and 4210.
   Choose a local interface IPv4 in advanced settings if VPN/multiple NICs interfere.
3. Select the returned identity/address/build, then **Connect selected rover**.
   No first responder is automatically selected/claimed. A busy candidate is blocked.
   The normal handshake independently verifies the selected identity before Enable.
4. **Save connected rover** stores a named local profile after valid feedback. Select
   it and **Connect saved rover** next time. It reconnects disarmed and preserves STOP;
   it never resets, enables or reconnects automatically after a motion fault.

Profiles are local atomic JSON settings in ignored `data/rover_profiles.json` (override
with `C2_PROFILE_PATH` for an isolated test). They store name, endpoint and optional
device ID; no Wi-Fi credentials. Old firmware can use manual UDP and address-only
profiles, but cannot be auto-discovered or provide identity assurance. MAC-derived
identity/boot/build metadata aid diagnosis; they are not cryptographic authentication.

The discovery listener is a short-lived backend UDP socket; HTTP stays loopback-only.
Replies must match the nonce, compatible C2V1/watchdog, local source and queried port.
Scans are bounded to 256 replies/16 candidates. They run off the event loop (including
Uvicorn/uvloop), never touch the control lease/watchdog, and are refused during local
Enable/disable transitions. Armed experimental firmware suppresses discovery replies
to prioritize control. Discovery is not guaranteed across routed subnets, guest/client
isolation, VPNs or firewall policies; manual unicast remains available.

## Validation and hardware gate

Run the root `uv run --frozen python scripts/verify.py`. Added checks cover the supplied
missing-gamepad/slow-transition failure mechanism, repeated page disarm, old/reordered
feedback, fixed deadlines, STOP escalation, identity mismatch, busy-owner protection,
profiles/restart, production uvloop compatibility, zero/full/mixed PWM and legacy/ROS
ceilings. Discovery tests send only loopback probes. The optional uvloop-specific
case is skipped on platforms where uvloop is unavailable.

Local Mac browser testing discovered an independent mock, selected/verified it, saved
a profile, reconnected disarmed with retained STOP, and selected the 100% cap. A 600 ms
mouse hold produced actual returned mock PWM 255; release/centering/disarm returned
zero. These are host/mock results, not physical motor or radio validation.

Before adopting the pair on hardware, record exact C2/firmware revisions, core/library
and Wi-Fi co-processor versions. Verify startup/25% and 0% behavior, then deliberately
chosen higher caps; test missing/recovered gamepad, repeated page changes, packet loss,
delayed/reordered ACKs, STOP/reset, ownership, reconnect and discovery under load.
Measure actual output cessation against the 250 ms watchdog goal: synchronous WiFiS3
calls can defer loop-based enforcement. Inspect new read/send/status/loop timings,
not just lifetime maxima. A successful compile or mock soak is not that acceptance.
No firmware upload, physical devices, LAN test, powered motion or DDS was exercised
by this implementation. Keep the two draft branches separate until reviewed/validated.
