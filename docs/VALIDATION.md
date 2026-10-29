# Browser transition verification

## Repository packaging and main integration — October 29, 2026

Main now includes NET5 `971aec7`; the browser branch already contains it. A curated
producer/lab is included under `prototypes/video_pipeline/` with its own locked
Python environment and agent/hardware-porting instructions. `packages/video_protocol/`
is the single framing implementation used by both processes. The private original,
captures, environments, compiled media workers and GStreamer registries are excluded.
Canonical desktop/firmware, historical source, ROS workspace/pins and `verify_all.py`
remain identical to main.

The expanded root verification completed: **33 C2 backend tests, 72 prototype tests,
three browser video-view lifecycle checks, controller and all JavaScript checks,
42 desktop tests, 21 GUI checks, 16 ROS host checks, delayed loopback soak and native
C++ guard compile/tests** passed. The prototype tests do not need FFmpeg/GStreamer/GPU;
its separate environment was exercised. The prototype refuses to reuse a different
service at its port and clearly rejects native Windows media-worker startup.

The newly packaged producer was also launched from this repository, compiled its
own native worker, used the shared protocol package and passed actual five-feed C2
browser playback, 1 Mb/s/400 kb/s reductions, zero-bandwidth stale/stop, recovery and
both receiver/sender reconnect paths. This is Mac/loopback evidence, not Intel/Sigma,
Windows, radio, two-host or DDS validation. The scripts left producer workloads off.
Current GitHub Actions results belong to the PR's checks, not these local figures.
See VIDEO_SYSTEM.md for setup, component ownership and the testing/acceptance boundary.

## Earlier browser transition preparation evidence


October 29, 2026 · local Mac / Python 3.12. NET5 baseline `971aec7` is already
merged into the browser branch. These are engineering prototype checks, not
hardware acceptance or team approval.

## Shared verification command

```sh
uv run --frozen python scripts/verify.py
```

The command completed successfully after the Enable-readiness correction below:

- **33 browser-backend tests passed**, including real fragmented TCP framing,
  receiver/viewer bounds, restart/epoch handling, origin/authority separation,
  NET5/OC input expiry and five simultaneous synthetic TCP inputs with slow viewers.
- **Three video-view lifecycle checks passed** in a Node component harness: explicit
  default-off behavior, one set of sockets/decoders shared across Drive/Cameras,
  display-only primary selection, pause, hiding, other routes and page exit cleanup.
  This harness does not establish browser codec support or real focus behavior.
- Controller mapping checks and syntax checks for every browser JavaScript module passed.
- **42 NET5 desktop unit/integration tests**, **21 hidden desktop GUI checks** and
  **16 ROS chassis host checks**, including dashboard widgets, passed.
- A **10-second loopback soak with 150 ms reply delay** passed drive, release-to-zero,
  command loss stop, no automatic enable and deliberate reconnect.
- Native C++ guard compilation/tests passed. Arduino compilation was explicitly
  skipped; firmware, physical devices and OS network settings were not changed.

The GitHub Actions workflow uses the same command on Ubuntu 24.04 with a virtual
GUI display and pinned action revisions. YAML/triggers were checked locally;
remote CI was not run during that earlier local-only preparation. Current CI results are shown on the PR.
The original `verify_all.py` and canonical/historical desktop and ROS source files
remain unchanged. `--skip-gui` explicitly reports omitted Tk checks. Arduino
compilation is opt-in and never uploads.

## Delayed initial-handshake finding

The initial combined run exposed a real timing failure in the browser's direct
NET5 path. In 10 of 20 diagnostic trials with 150 ms mock replies, Enable immediately
after the first HELLO acknowledgment reached the unchanged 350 ms original-command
age limit before later command progress arrived. It stopped safely, but prevented
reliable initial enable. This was not a video-encoder failure.

The browser now offers/accepts Enable only after a fresh acknowledgment of a
post-handshake non-motion command. The backend rejects premature Enable before
arming locally or sending ARM. A regression checks that confirmation itself never
enables. **Twenty follow-up delayed-enable trials passed.** No upstream NET5 code,
MCU/PC timeout limit, cached-input publication or ROS vendor adapter was changed.

## Actual browser and media checks

The existing native browser supports the received H.264 profiles. Actual five-feed
playback passed from Drive with the selectable large view. A fresh end-to-end run
also passed 1 Mb/s primary-only, 400 kb/s emergency output, zero-bandwidth stale/stop,
bandwidth recovery, C2 TCP receiver restart and sender reconnect. These checks use
real loopback TCP plus actual browser render reports; application pacing is not a
radio packet-loss emulator.

A 12-second browser/mock observation captured 246 samples with all five feeds fresh
and rendering, including 36 samples of nonzero returned mock throttle during a held
keyboard command and zero output after release. Primary-view selection left authority
and the priority revision unchanged. Switching to Cameras disarmed and retained video;
pausing Camera 02 released only its viewer. A non-video route released every browser
viewer while all five TCP inputs continued. The expandable command model still renders.
The split layout was visually checked; a requested narrow viewport override did not
apply in this automation environment, so no mobile-breakpoint acceptance is claimed.

Automation switching between background in-app tabs did not produce an actual OS
focus/visibility change. **Real browser/window focus-loss and physical controller
mapping remain hands-on acceptance work.** Existing route/expiry checks are not a
substitute for those tests. Actual Ubuntu/Jazzy builds, DDS, physical Wi-Fi/motor
stopping, GPS and device integration also remain unverified here. The ROS transport
still uses its documented older pinned adapters.

Private screenshots and detailed API samples remain in the separate local lab,
outside Git. All ten synthetic-source/native-encoder worker PIDs were confirmed gone
after cleanup. Services remain online; generation, encoding, transmission and playback
are off. C2 is disconnected/disarmed. No deployment, LAN exposure, firmware upload or physical operation occurred during those checks. Substantive human review and applicable course
AI disclosure/approval remain required before team deployment.
