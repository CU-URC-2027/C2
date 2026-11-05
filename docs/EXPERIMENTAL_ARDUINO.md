# Experimental Uno R4 WiFi connection/PWM firmware

November 3, 2026. Branch `experimental/arduino-connection-pwm`, from main `07b129d`.
The user selected `c2_prototype/firmware/mini_rover_c2` as the firmware source.
Matching C2 UI/backend changes are on separate branch `fix/connection-recovery-discovery`.
Neither branch has physical hardware acceptance. No upload was performed.

## Scope

- Keep C2V1 identity/session/epoch/sequence guards, the 250 ms drive watchdog, explicit
  ARM and STOP/reset semantics. Discovery is parsed separately; it cannot change
  the owner, session, epoch, lastOwner/lastDrive or enabled/stopped state.
- `C2_MAX_PWM=255` is the physical 8-bit mixed-wheel bound. There is no firmware
  25%/50% operating cap: the matching browser/backend selects 0–100%, starts at 25%,
  and disarms on an increase. State feedback advertises `max_pwm:255`, letting C2
  distinguish this sketch from older 64-count firmware. Duty cycle is not speed.
- Actual ARM/DISARM/STOP/reset transitions still apply outputs immediately and receive
  urgent compact confirmation. Redundant DISARM/STOP packets share bounded receive
  batches without an urgent reply per duplicate. Routine replies follow a separate
  100 ms schedule; receive work admits at most eight packets or 120 ms per batch.
- Telemetry adds device ID (cached MAC), boot diagnostic ID, build identifier, Wi-Fi
  co-processor firmware and last completed UDP read/send/Wi-Fi status/loop timing,
  max send/loop timing, TX failures and discovery-query count. The existing `udp_ms`
  covers the handler; timing fields can describe the previous completed operation.
  `max_loop_gap_ms` is a lifetime maximum, not every loop's duration. Identity is
  diagnostic/selection metadata, not cryptographic authentication.

### November 3 timing follow-up: recovery-v2

Routine/urgent replies now use compact C2V1-compatible guarded state JSON (381 bytes
in the native worst-width fixture). Device/boot identity, PWM capability, encoders
and every safety/ACK field remain in each frame. Detailed build/Wi-Fi metadata and
counters replace one routine reply at most once per second while disabled and only
after the RX queue drains. Detailed frames pause throughout armed operation; they
never add a second datagram. Every urgent transition receives a compact reply.
The matching C2 server keeps separately aged detail frames in diagnostics.

`C2Telemetry.h` supplies the portable scheduler and bounded formatter used by the
actual sketch. Receive batches stop at the packet/time admission limit, with
watchdog/GPIO checks around individual synchronous modem calls. An already-started
call can exceed the admission budget; this is not a hard real-time bound. Oversize
datagrams use one flush instead of an unbounded byte-by-byte drain. No loop sends a
second state immediately after an urgent state, even when its modem call ran long.

Timings now include the full receive batch separately from the handler, batch count,
budget-hit count, last payload bytes and beginPacket/write/endPacket durations.
Existing send/loop maxima remain lifetime maxima. Timing values describe previously
completed work; detail-frame receipt age is also distinct from capture/measurement
age. All three send stages contribute to TX failure reporting. No timeout increased.

Native stress checks use the real scheduler and guard with 20 Hz input, 25 ms receives
plus 35 ms every eleventh receive, 6 ms loop overhead, 80 ms detailed sends and assumed
35 ms compact sends. The revised scheduler defers detailed frames while armed.
Conservative ACK-age maxima are 356 ms old / 277 ms revised. Sweeping compact-send
costs from 30–55 ms gives a 305 ms maximum. An idle-to-ARM case also includes an
in-progress 110 ms full send, 25 ms receive and 55 ms urgent reply. These costs are
synthetic; the compact-send improvement must be measured on hardware.
The test also checks count/time budgets, timer rollover, output-buffer truncation and
maximum-width compact framing. The independent 250 ms drive timeout still applies.

Arduino Renesas Uno core 1.6.0 compiled recovery-v2 at **100,492 bytes flash / 12,544
bytes static RAM**, using the library versions below. This is compilation evidence,
not a firmware upload or a physical timing/motor test. Full shared host verification
passed (22 checks including compilation); the final revised scheduler/native stress
and full sketch compile also pass. Physical acceptance remains pending.

## Read-only discovery contract

The control UDP port (normally 4210) also accepts exactly
`C2DISC1,<16 lowercase hexadecimal nonce>\n`. It replies with bounded JSON containing
`type:c2_discovery`, `v:1`, the nonce, `device_id`, `boot_id`, `build`,
`control_protocol:C2V1`, `control_port`, `watchdog_ms:250`, `max_pwm:255`, and Boolean
`busy`, `enabled`, `stopped`. The reply's IP/port are the actual source endpoint.

Queries do not call C2Guard::accept and do not feed any watchdog/owner lease. Replies
are limited to one per 500 ms and suppressed while armed to prioritize motion
traffic. A disabled endpoint can report busy while another owner's traffic is fresh.
The C2 backend sends only two probes and requires explicit identity selection plus
the normal guarded handshake before Enable. Both devices must already share a LAN;
this is not Wi-Fi credential provisioning or automatic ARM/STOP recovery.

## Build and validation

Keep Wi-Fi credentials in ignored `wifi_credentials.local.h` according to the
existing firmware guide. Never commit credentials, compiled binaries, captures or
private test logs. Use a separate checkout of this branch; the C2 feature branch
intentionally contains main's older sketch.

Compile (never uploads):

```sh
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi c2_prototype/firmware/mini_rover_c2
```

The local compile used Arduino Renesas Uno core **1.6.0**, Adafruit GFX **1.13.0**,
BusIO **1.17.4**, SH110X **2.1.15**, NeoPixel **1.15.5**, MPU6050 **2.2.9**, Unified Sensor
**1.1.15** and its dependencies. Build output: **99,780 bytes flash**, **12,504 bytes
static RAM** on Uno R4 WiFi. The temporary toolchain/build output is ignored and is
not required as a checked-in dependency. The sketch's normal build ID includes a
compile timestamp; `C2_BUILD_ID` can be provided explicitly when building a release.

Native guard/parser tests now include discovery framing, duplicate reply coalescing,
255-count bounds and the retained ordering/watchdog/STOP tests. The root host checks
also exercise the retained main C2/ROS/video software. They do not replace compiling
the full sketch or validating physical timing/networking/motion.

The shared verification command passed all 21 requested checks on this branch:
46 retained backend tests, 72 video-prototype tests, controller/UI/syntax checks,
42 desktop tests, 21 Tk GUI checks, 16 ROS host checks, a 150 ms delayed-reply
loopback soak and the updated native guard/parser tests. Its browser/backend remain
main's baseline; use the separate C2 branch for full-range browser controls.

Before deployment, compare real telemetry/build IDs, verify startup/zero/25% requests,
then intentionally selected higher PWM; test mixed-wheel saturation, hold release,
250 ms watchdog behavior under blocking radio calls, missing controller, page-change
disarm, loss/reordering, STOP/reset, owner protection and Wi-Fi reconnect. Discovery
must not refresh a command/owner lease, clear STOP or enable. Measure output stop
timing and loop/read/send/status durations; no clock/watchdog limits were increased.
Pair this sketch with the reviewed C2 branch and keep main unchanged until acceptance.
