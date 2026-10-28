# NET5: connection recovery and reproducible bench checks

## What changed

- The Python app separates known-disabled idle degradation from active motion faults.
  Fresh replies alone are insufficient: recent command acknowledgment is still
  required before Enable or Reset STOP. Idle recovery never sends ARM.
- While waiting for ARM confirmation, non-motion PINGs continue at 10 Hz.
  No DRIVE is sent before confirmation. This resolves a reproduced 150 ms reply
  delay transition failure without changing original send timestamps or limits.
- Active faults remain latched. The MCU watchdog is still 250 ms; the PC command
  acknowledgment limit is still 350 ms. A stalled UI still causes a safe stop.
- NET5 detects Wi-Fi loss, disables outputs, latches STOP, clears the old session,
  and attempts Wi-Fi/UDP recovery every five seconds. Calls into WiFiS3 may block,
  but recovery runs only with outputs disabled. After recovery reconnect C2,
  Reset STOP, wait for confirmation, center controls and Enable deliberately.
- Failed initial network startup now also enters the disabled retry path.
- OLED refresh is suppressed while enabled. Its last screen can therefore be
  stale until disarm; use C2 feedback for current state. Idle refresh is 2 Hz.
- MCU state includes maximum loop gap, last UDP-handler and OLED durations,
  packet/rejection counts, last rejection category and recovery count. These
  travel in rover_state/first-fault logs; maximum gap includes recovery pauses.
- The larger chassis text panel retains its scroll position during updates.
- Local Wi-Fi credentials are excluded from Git, rather than editing a tracked file.

## Setup

Use the top-level c2_prototype folder. The nested historical C2-team/c2_prototype
copy and releases/c2-bench-v0.4.zip are not this release.

For a fresh clone, create firmware/mini_rover_c2/wifi_credentials.local.h:

```cpp
#pragma once
#define C2_WIFI_SSID "YOUR_ROUTER_SSID"
#define C2_WIFI_PASSWORD "YOUR_ROUTER_PASSWORD"
```

Existing credentials on the development laptop were preserved in that local file.
Do not commit it. Compile/upload mini_rover_c2.ino for Uno R4 WiFi and verify
C2-NET5-20261028 on USB serial. This update was not uploaded by the assistant.
Firmware compiled with GPS disabled; the optional GPS mode needs its own bench run.

## Hardware-free testing

```text
python verify_all.py
python c2_prototype/soak_test.py --seconds 60 --delay-ms 150
python c2_prototype/app.py --xbox
```

The verification runner runs unit/integration tests, hidden GUI checks, and a
localhost-only sustained drive test with delayed replies, release to zero,
command loss, no automatic re-enable, and explicit reconnect. Pass --cxx and
--arduino-cli (optionally --arduino-config) to include native/firmware compilation.
Missing compilers are explicitly reported as skipped, not passed. For a headless
machine, --skip-gui reports that omission. In the app, Start local test creates
an in-process localhost mock; this does not access motor hardware.

## Next physical acceptance test

1. Motor supply off, Arduino powered by USB: verify NET5, select Xbox before
   connecting, and observe disabled communication for at least two minutes.
2. With C2 still connected, reboot the router. Observe USB NETWORK loss/recovery
   messages, outputs disabled, and the printed current IP on recovery. Reconnect
   C2 explicitly. Verify that it cannot move before Reset STOP and Enable.
3. Wheels lifted: Enable with neutral sticks and LB released; hold LB for a small
   command. Release LB and check zero output. Test STOP, controller unplugging,
   window focus loss and router interruption. No recovery may restart motion.
4. Save logs before reconnecting after a fault. Record USB messages and whether
   the board rebooted. Compare USB-only tests against tests with motor power on.

## Limits and deferred architecture

The mock reproduces protocol timing, not WiFiS3 radio behavior, electrical noise,
I2C bus behavior or actual motor stopping distance. A compile cannot validate
router recovery. The MCU watchdog is loop-serviced; a blocking library call can
still delay physical stop. Actual timing and supply integrity require hardware.

Input/network/UI separation remains a future architectural change. This release
keeps the existing fail-closed behavior during a Tk stall; no background thread
replays the last drive command. Moving SDL input off its event thread without
platform-specific testing would introduce a new risk rather than establish a fix.

The ROS workspace is separate and retains its pinned vendor transport; NET5
behavior has not silently been copied into it. Host tests are not ROS runtime
or Ubuntu validation. Arm controls remain previews; no arm transport was added.
