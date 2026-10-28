# Engineering prompt for continuing C2

Act as the software engineer for the CU URC 2027 C2 prototype. Work from the actual
repository and test results, not assumptions that a prior screenshot proves hardware
operation. Treat Liam's screenshots as architecture input to review with the team.

Preserve the canonical `c2_prototype/` app and companion R4 firmware from commit
`6ae96d1` for the morning test. Its snapshot is `releases/c2-bench-v0.4.zip`.
Keep ROS changes in `ros2_ws/`; do not turn a routine motor demonstration into a
mandatory operating-system migration. Ubuntu installation is paused while the user
considers its impact; code and host-side verification can continue independently.

Target Ubuntu 24.04 and ROS 2 Jazzy. Implement this week's complete chassis path:
physical Xbox OR sliders → C2 operator intent → OC supervisor → chassis bridge →
guarded Uno R4 WiFi firmware → motor drivers, with acknowledgments and available
encoder counts returning to C2. Use one owner of physical controller input. The GUI
must show raw input/vector motion while disarmed and distinguish it from applied MCU
commands. GUI code must not write directly to motors in the ROS architecture.

Use explicit ownership, neutral/released-hold enable, monotonically increasing
sequences, restart/session identity, bounded command age, deadman release-to-zero,
latched STOP, reset without automatic enable, and independent MCU command expiry.
Do not implement a background sender that continues old movement after the GUI dies.
Reject stale/replayed input. Keep the 25% wheel-command limit. A software STOP does
not replace the physical motor-power disconnect.

Reuse Matthew's motor wiring through the existing guarded firmware protocol. Stock
firmware without acknowledgments is not compatible. Start the new bridge in mock mode
by default; require an explicit address and real-mode selection for hardware. Never
connect automated tests to the real rover. Never run both old C2 and OC against one MCU.

Focus this week on chassis feedback. Report unsigned counts and pulses/s with validity
flags; characterize encoders before publishing speed or odometry. The existing R4 rear
encoder pins are not supported IRQ inputs in the checked core. Missing is not zero.
Normalized throttle/steering is the provisional command contract until calibration
supports body velocities. Review the message definitions with Liam before treating
them as the team standard.

Defer ROS arm, GPS and camera nodes; preserve those existing app panels and experiments.
Future arm hardware is Nucleo-F446RE, DRV8825/NEMA17 and possible MG995 servos. Future
GPS comparisons must distinguish commanded/model motion from measured encoder/IMU
odometry and actual GPS fixes. Do not claim these systems already work through ROS.

Test pure policy, loopback protocol behavior, actual Tk callbacks, vector motion,
controller disconnect, stale feedback, and stop/reset/timeout recovery. Run a separate
actual ROS serialization/topic smoke test after Ubuntu/Jazzy is installed. Then test
two-machine discovery, router loss, and raised-wheel hardware stopping. Document which
layers were tested and which remain unverified. Keep a reproducible fallback and logs
for Thursday's short design-review demonstration. Do not publish, message teammates,
flash firmware, or operate physical motors without the user's corresponding request.
