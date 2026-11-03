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
  urgent confirmation. Redundant DISARM/STOP packets can be processed in the existing
  bounded four-packet batch with one reply, instead of returning/sending per duplicate.
- Telemetry adds device ID (cached MAC), boot diagnostic ID, build identifier, Wi-Fi
  co-processor firmware and last completed UDP read/send/Wi-Fi status/loop timing,
  max send/loop timing, TX failures and discovery-query count. The existing `udp_ms`
  covers the handler; timing fields can describe the previous completed operation.
  `max_loop_gap_ms` is a lifetime maximum, not every loop's duration. Identity is
  diagnostic/selection metadata, not cryptographic authentication.

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
