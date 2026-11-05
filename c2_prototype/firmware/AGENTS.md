# Experimental Arduino branch

Read docs/EXPERIMENTAL_ARDUINO.md from the repository root and the existing
firmware README. Work here belongs to `experimental/arduino-connection-pwm`; the
browser/backend counterpart is `fix/connection-recovery-discovery`.

- Preserve C2V1 guards, independent 250 ms drive timeout, startup-disabled outputs,
  explicit ARM/STOP/reset and owner lease rules. Discovery never enters that machine.
- The MCU permits physical 0–255 mixed-wheel PWM; C2 owns the requested 0–100% cap
  and starts at 25%. Do not add a hidden 25%/50% limit or infer speed from duty cycle.
- Discovery is rate-limited, non-claiming and suppressed while armed. Keep response
  buffers bounded and valid JSON; metadata is not authentication.
- Apply real transitions immediately, coalesce only redundant confirmations, and
  retain bounded receive work and watchdog checks around synchronous calls.
- Compile/native-test only unless physical testing/upload is explicitly authorized.
  Keep credentials, media, logs, toolchains and binaries out of Git. State hardware
  validation gaps; preserve unrelated historical copies and ROS transport pins.
