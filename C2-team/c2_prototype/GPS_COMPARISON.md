# GPS versus the virtual path

The GUI can now visualize this question, but the difference must be interpreted
carefully. A path integrated from commands says where an idealized rover would
have gone. It does not measure wheel motion, slip or true location.

## Three tracks to collect

| Track | Meaning | Useful discrepancy |
|---|---|---|
| Command model | Integrate requested forward/turn velocities | Intent versus execution |
| Wheel/IMU odometry | Estimate pose from measured wheel speeds and yaw | Encoder calibration and slip |
| GPS | Satellite-based antenna position | Long-term drift and global positioning |

Compare GPS with wheel/IMU odometry independently before using GPS to correct that
odometry. Comparing GPS against an estimate already fused with the same GPS can
hide errors. A surveyed course, independent reference or calibrated external
tracking is needed to make an actual accuracy claim.

## What this prototype implements

The demo produces one synthetic fix per second with a known offset (+0.7 m East,
-0.4 m North) plus independent 0.3 m Gaussian noise. Cyan shows the reference;
orange shows synthetic GPS. Connecting a GP-20U7 is not simulated as a real fix.
The interface shows the latest 600 pairs (about 10 minutes in demo mode).

For real offline data, navigation.py converts WGS84 latitude/longitude into local
East/North metres through ECEF. It assumes zero ellipsoid height for this short,
horizontal comparison. It is not a terrain/altitude or long-distance navigation
solution. It linearly interpolates reference position at each GPS timestamp,
accepts exact matches, and rejects extrapolation or reference gaps over 1 second.
Only fixes explicitly marked valid=true are compared. Duplicate reference/GPS
timestamps, nonfinite numbers and invalid coordinates are rejected.

Horizontal discrepancy for each pair is sqrt(delta_east^2 + delta_north^2).
Horizontal RMSE is sqrt(mean(delta_east^2 + delta_north^2)). The mean signed E/N
differences expose bias that an unsigned distance alone cannot show. No matching
pairs means unavailable, never zero error. Log import reports unmatched valid
fixes; invalid fixes are excluded from comparison entirely.

## Offline input format

Use JSON Lines: one JSON object per line. Both tracks must already use the same
clock, ENU orientation and origin. An example is in examples/gps_comparison.jsonl.

```json
{"type":"origin","latitude":0.0,"longitude":0.0}
{"type":"reference","time_s":0.0,"east_m":0.0,"north_m":0.0}
{"type":"reference","time_s":0.5,"east_m":0.5,"north_m":0.0}
{"type":"gps","time_s":0.25,"latitude":0.0000090437,"longitude":0.0000112289,"valid":true}
{"type":"gps","time_s":1.0,"latitude":null,"longitude":null,"valid":false}
```

Exactly one origin is required. The example origin is illustrative, not the
user's location. Import through Telemetry & Logs > Load comparison JSONL. This
format differs from the rolling command export: convert command model or recorded
odometry into reference rows and merge GPS fixes before loading. Imports are
limited to 100000 rows; the GUI displays/analyses the latest 600 matched pairs.
The pure compare_log function returns all matched pairs for offline analysis.

## Real collection procedure

1. Identify the exact GPS board, connector pinout and logic/supply levels from its
   documentation before wiring. Put its antenna where it has a useful sky view.
   Capture raw NMEA and fix status on the onboard computer. Add a ROS driver only
   after the serial stream and timestamps are understood.
2. Record GPS measurement time, receipt time, validity, covariance/quality when
   available, and measured wheel/IMU odometry. Do not replace invalid GPS with
   (0,0); do not substitute receipt time for measurement time without labeling it.
3. Set one local ENU origin and rotate/translate the odometry into that frame.
   Initial heading must be measured or established; a stationary GPS fix does not
   establish rover heading. Account for antenna offset from the rover's base.
4. Synchronize computers and document any measured sensor latency. Correct known
   clock offsets before import. Do not align clocks by minimizing the same error
   that will be reported as validation, unless reporting that fitting separately.
5. Record stationary data, straight runs, turns and a return to the starting point.
   Preserve run conditions, wheel geometry and GPS quality alongside each run.
6. Compare latest distance, mean E/N offset and RMSE, plus unmatched/invalid counts.
   Plot discrepancy over time in subsequent analysis to separate bias from drift.

Future ROS frames: map for the global/local geographic reference, odom for the
continuous locally estimated frame, base_link for rover body, gps_link for antenna.
Frame transforms, timestamps and covariance are as important as latitude/longitude.

## Live GPS capture added in 0.4

Connections & Live GPS reads checksum-validated GP-20U7 GGA/RMC over USB or the
optional R4 relay. GPS_HOME_TEST.md gives the home ATmega328 Uno sketch, wiring,
stationary-scatter and measured-path tests. Its exported `gps_capture` records
contain raw NMEA, receipt timestamps and parsed data; they are not directly the
reference/GPS pair schema above. There is no automatic live model/GPS alignment
or fusion in this version. Keep the stationary scatter metric distinct from the
comparison RMSE: the former is spread about a mean, the latter requires a reference.
