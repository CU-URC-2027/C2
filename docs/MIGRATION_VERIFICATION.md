# Migration verification — 2026-10-27

## Executed on this Windows laptop

Python: `C:\Users\Cutle\Anaconda\python.exe` (3.11). No Arduino was flashed or
physical motor endpoint contacted. UDP tests used a loopback mock on this computer.

| Suite | Result | What this establishes |
| --- | --- | --- |
| Existing `c2_prototype` unit/integration tests | 34 passed | Control policy, mock drive/release/STOP, GPS, camera and controller adapters remain working under test |
| Existing `gui_regression.py` | 19 passed | Existing hidden Tk controls, input vector/model, GPS/camera and connection callbacks |
| New ROS-workspace Python tests | 16 passed | 6 policy/encoder tests, 4 loopback OC/MCU tests, 6 actual hidden Tk widget tests with fake ROS transport |

New checks exercise claim/neutral enable, 25% cap, release-to-zero, STOP/reset,
operator timeout, OC freeze, missing MCU replies, replay/epoch rejection, invalid
encoder channels, rollover/rate gaps, input-vector motion while disarmed, Xbox
adapter samples/disconnect, source changes, stale OC state/restart, capture export,
and close-to-STOP. The Xbox is mocked in automated tests, not physically exercised.

The first loopback run in the restricted tool environment could not exchange packets.
After enabling local networking for the test process, all tests passed. This was a
test-environment limitation, not evidence of real router behavior.

Reproduce the new suite from repository root with the package on `PYTHONPATH`:

```bash
PYTHONPATH=ros2_ws/src/urc_c2_chassis python3 -m unittest discover -s ros2_ws/src/urc_c2_chassis/test -v
```

Use Ubuntu/WSLg or a display for Tk tests. Actual ROS testing is separate:

```bash
source /opt/ros/jazzy/setup.bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
ros2 run urc_c2_chassis smoke_test
```

## Preserved baseline

No source changes were made in canonical `c2_prototype/`. The existing firmware is
unchanged. The fallback zip contains that directory from commit `6ae96d1`.

SHA-256 of `releases/c2-bench-v0.4.zip`:

```text
82A3CD7DBAADD1FB53E59D562A642579451DCFBB9A37FCD333BDAB7142277100
```

The previous native C++ guard tests and firmware compilation results remain documented
in the old app's TEST_RESULTS.md; they were not rerun for this migration because firmware
was not changed. They are not physical acceptance results.

## Not yet verified

- WSL installation and Ubuntu startup; installation is paused after the user's impact question.
- `colcon` build, generated ROS message bindings, ROS serialization/QoS and real node execution.
  A forced-mock `smoke_test` is provided but **has not been run under ROS**.
- Physical Xbox visibility/mapping in WSL or native Ubuntu, and Linux GUI rendering.
- Cross-computer ROS discovery on the actual router, WSL networking, latency or packet loss.
- Powered motors, physical stopping time, encoder pins/count calibration, real GPS and arm motion.

The new code is ready for Ubuntu integration testing, not a claim of hardware readiness.
Do not substitute it for the morning app until the staged acceptance gates pass.
