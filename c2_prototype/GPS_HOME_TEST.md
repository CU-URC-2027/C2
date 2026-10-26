# GP-20U7: home Uno test and rover integration

Your home board is an **ATmega328 Uno**, which is different from Matthew's Uno R4
WiFi. The included home sketch uses SoftwareSerial for GPS and USB for the PC.
It never sends motor commands or writes configuration commands back to the GPS.

## Wiring the home test

Use the standard three-wire GP-20U7. SparkFun's documentation identifies red as
VCC, black as GND and white as TX. Verify your actual leads/board markings; do not
infer connector pin numbers from which way a photo faces. If yours has a different
connector or carrier, identify its pinout before applying power.
[SparkFun lead identification](https://community.sparkfun.com/t/gp-20u7-connector-pin-numbers/42068).

| GP-20U7 / connection | ATmega328 Uno |
|---|---|
| VCC, normally red | Regulated **3.3 V**, not 5 V |
| GND, normally black | GND |
| TX, normally white | **D4** (software UART RX) |
| No GPS RX lead on this version | **D5 remains unconnected** |
| Uno USB | Computer USB, for power/programming/data |

SparkFun's archived product documentation specifies approximately 40 mA at 3.3 V
and default 9600-baud serial. Use a 3.3 V supply with adequate current capacity;
verify the regulator rating on your particular development-board clone. If its
3.3 V rail is uncertain, use a separate regulated 3.3 V supply with common ground;
do not tie two regulator outputs together. Keep GPS power separate from a noisy
motor rail. [SparkFun product documentation, archived](https://static6.arrow.com/aropdfconversion/3512fdb2cc46e563a5958ccaae4bf6aeaede80c3/pgurl_13755900101485272.pdf).

This is a one-way connection: GPS TX → Uno RX. Never connect a 5 V Uno output to
the GPS signal. A 3.3 V GPS output is safe for the Uno input; if its logic-high
level does not meet the receiver's specified threshold, use a suitable 3.3-to-5 V
UART buffer. Do not use an RS-232 ±voltage adapter.

## Upload, observe, then use C2

1. Open `firmware/gps_uno_bridge/gps_uno_bridge.ino` in Arduino IDE.
2. Select **Arduino Uno** from Arduino AVR Boards and the home board's USB port.
   This is NOT the Uno R4 board selection. Upload with no motor hardware attached.
3. Open Serial Monitor at **115200**. The sketch reads the GPS at **9600**, then
   forwards the raw NMEA text over USB. The different baud rates are intentional.
4. Look for `$GPGGA,...*xx` and `$GPRMC,...*xx` sentences. Receiving text means the
   serial path works; it does not necessarily mean the GPS has a valid position.
5. Place the antenna outdoors, facing open sky, and wait several minutes. A GGA
   fix-quality field of 0 means no fix. Do not treat blank fields as coordinates.
6. Close Serial Monitor. Start C2 → **Connections & Live GPS → Scan ports**. Select
   this Uno's COM port, **115200**, then **Connect USB GPS**. One program owns the
   serial port at a time. Opening the port may reset the Uno briefly.
7. Confirm VALID FIX, sensible latitude/longitude, recent fix age, satellites and
   HDOP. The plot uses East/North metres relative to the first valid fix. The app
   rejects bad checksums, malformed coordinates and repeated/backwards UTC samples.

No data: check port, monitor ownership, common ground and TX→D4. Garbled data:
check both baud rates and logic levels. Valid NMEA but no fix: improve sky view.
HDOP is a geometry indicator, not a direct metre accuracy measurement.

## Experiment A: stationary scatter, about 10 minutes

Keep the GPS at one marked location after it obtains a stable fix. In C2 click
**Start new GPS run**, leave the antenna still for five minutes, then **Save GPS run**.
Record sky conditions, time, valid sample count, satellites/HDOP, bad sentences and
stationary scatter RMS. Repeat near a building to observe multipath/obstruction.
Do not move it during either stationary run.

The statistic is `sqrt(mean((E-mean(E))² + (N-mean(N))²))` across retained valid
fixes. It describes precision about the sample mean, not accuracy against ground
truth. A consistently biased receiver can have small scatter. Logs retain up to
20,000 raw NMEA records; displayed scatter uses the most recent 3,600 valid fixes.

Acceptance: fresh fixes and an updating track appear; the saved JSONL contains raw
NMEA and parsed samples; unplugging GPS/USB produces NO FRESH FIX rather than a
new point at (0,0). A valid fix expires 2.5 seconds after its last GGA receipt.
Do not obscure receipt age: it is not a full sensor-to-display latency estimate.

## Experiment B: walk a measured path and return

With no motors attached, carry the antenna/laptop around a measured 10–20 m route,
pause at marked corners, then return to the starting marker and pause again. Log
one continuous run. Compare the plotted displacement with tape-measured distance,
and compare the averages of the first/last stationary segments. GPS noise may be
comparable to short segments; this is a coarse displacement/closure test.
A USB tether to a stationary PC limits the route, so use a portable laptop.

## Adding it to Matthew's rover

**Option A — preserve all rover wiring:** use this Uno as a GPS USB bridge plugged
into the future onboard computer, or use a suitable USB UART adapter. The onboard
computer later publishes NavSatFix over ROS. The present GUI can read the bridge
only when its USB port is local to the C2 PC. A USB connection to a different PC
needs a forwarding/ROS node; that remote bridge is a planned stage, not implemented.

**Option B — one-board R4 wireless bench test:** the companion R4 sketch includes
an opt-in Serial1 GPS relay. Matthew currently assigns D0 to the front-left encoder
and D1 to OLED button C. Serial1 uses BOTH pins, even when GPS only transmits.
Enabling it without physically freeing those pins creates a conflict.

With power off, make this complete change together:

| Signal | Existing wiring | GPS option |
|---|---|---|
| Front-left encoder | D0 | Move to **A2** |
| OLED button C | D1 | Move/isolate and reroute to **A3** |
| Sonar trigger/echo | A2/A3 | Disconnect; sonar is disabled |
| GPS TX | Unconnected | **D0 / RX1**, through suitable logic buffering if needed |
| R4 D1 / TX1 | OLED button | Free, leave unconnected to three-wire GPS |
| GPS VCC/GND | Unconnected | Regulated 3.3 V / common ground |

If the display/button shield hardwires D1, changing a macro alone does not free it;
its connection must actually be isolated/rerouted. The tested R4 core maps A2 to
external IRQ7, separate from the remaining front-right input D11/IRQ4. Verify
front-left encoder counts after moving it. Rear D9/D13 interrupt support remains
unavailable; this option does not fix that existing allocation issue.

The R4 uses 5 V GPIO. Do not assume every 3.3 V UART TX meets its input-high
specification. A suitable buffer such as a 5 V powered 74AHCT125 can translate the
GPS's 3.3 V TX to the R4 RX; follow that exact part's supply, enable and decoupling
requirements. Never feed 5 V back into GPS. Confirm levels with the scope before
connecting. The GPS supply itself remains 3.3 V.

After wiring/level checks, set `C2_ENABLE_GPS` to **1** in `c2_config.h`, compile and
upload. The firmware switches the two pin definitions and disables sonar. Connect
the rover in C2, then click **Use rover GPS**. Raw NMEA travels back over the same
UDP connection, tagged with the active session; Python validates fix/checksum.
GPS reception does not enable motors or refresh their command watchdog. Test GPS
first with motor power isolated, then check interference with motors running raised.
Return to the original physical wiring before turning this option off again.

## Comparing GPS with the C2 motion model

The cyan rover trace integrates commanded wheel motion using assumed speed/track
width. It is not ground truth. For a future moving comparison, record GPS, encoder/
IMU odometry and commands concurrently; define a common ENU origin, align initial
heading, synchronize timestamps and account for antenna offset. Then compare
matched timestamps, rejecting invalid fixes and long gaps. A difference can come
from slip, wrong speed calibration, timing, heading or GPS error.

The existing Telemetry comparison accepts the reference/GPS JSONL schema in
[GPS_COMPARISON.md](GPS_COMPARISON.md). Live `gps_capture` exports are intentionally
a separate raw record format; they are not yet an automatic model/GPS fusion or
import pipeline. The stationary and measured-path experiments above work now and
provide real evidence before adding odometry and synchronized comparison.
