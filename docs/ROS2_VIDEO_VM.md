# Two-VM ROS video prototype

November 3, 2026. Implemented and exercised on two Ubuntu 24.04.5 ARM64 Parallels
VMs with ROS 2 Jazzy, Fast DDS 2.14.7 and rmw_fastrtps 8.4.4. This is an opt-in
video experiment. It leaves chassis transports, firmware, watchdogs, the existing
`ros2_ws/` workspace and its vendor pins unchanged. Start from the repository's
normal browser backend; no code from the separate Distributed-Computers repository
is required. Recovery/PWM experiments on other branches remain independent.

## Processes and ownership

```text
C2 VM                                            Rover VM
browser → Python backend                         Python lab process
          priorities + explicit link budget ─ROS→ StatusManager → EncodingDecision
          plan + health                    ←ROS─ metadata adapter
          TCP H.264 receiver                ←TCP─ Transmission ← replay/hardware
browser ← WebCodecs/WebSocket relay
```

One ROS participant runs inside each application process. The lab observes and
controls actual source/replay/transmission lifecycles; the real C2 backend owns
priority order, omissions and the explicit comms/test budget. There is no C2 simulator
in the rover process. Browser video actions do not renew operator input or enable
chassis controls. Media bytes bypass ROS and the metadata-only policy cores.

| Endpoint | Owner and purpose |
| --- | --- |
| Private C2 TCP 5100 | Fast DDS metadata, including discovery; built-in UDP/SHM transports disabled |
| Private C2 TCP 8874 | Five separate rover-to-C2 encoded-video connections, exact rover peer allowlist |
| C2 localhost HTTP 8870 | Actual browser backend and video WebSockets |
| Rover localhost HTTP 8872 | Architecture canvas and workload controls |
| Optional private TCP 8890 | Explicit development browser forward, exact host peer allowlist |

Default namespace is `/urc_video_lab`, domain **198** (separate from the earlier
domain-197 ROS-demo experiment). Topics are `priorities` (`FeedPriorities`),
`link_budget` (`VideoLinkBudget`), `status_inputs` (`StatusInputs`), `encoding_plan`
(`EncodingPlan`) and `health` (`VideoHealth`), all under that namespace.
`CameraEncodingPlan` carries each camera's settings and reason. Definitions live in
`prototypes/video_pipeline/ros2/urc_video_interfaces/`; package maintainer/license
placeholders and team interface approval remain unresolved.

C2 sends configuration/budget at 2 Hz. Status/plan/health publish at 5 Hz. Reliable,
depth-one metadata QoS uses a three-second transient-local lifespan for priorities
and one-second volatile lifespan for the other topics. Receipt freshness and ordering
are still checked by the unchanged StatusManager. Only real budget messages refresh
budget receipt; a UI tick never invents capacity. Stale priorities or budget inhibit
output. Session/sequence checks reject delayed retired rover health after restart.
The owning application pumps a bounded number of ROS callbacks with nonblocking
`spin_once`; heavy media work stays outside these callbacks.

The generated TCP profile deliberately supports **one application participant per
VM**. Additional ROS processes/CLI nodes need a reviewed discovery/port configuration;
do not launch multiple server participants on 5100. This is not a general production
ROS graph or a security/authentication deployment.

## Prepare each VM

Prerequisites: Ubuntu 24.04, ROS 2 Jazzy base and development tools including
`colcon`, `rosidl_default_generators`, `rmw_fastrtps_cpp`, Python 3.12, `uv`, and Git.
Use the ROS system interpreter so the binary Jazzy `rclpy` extension matches Python.
Keep the new video workspace separate from `ros2_ws/`.

```sh
sudo apt-get install python3-venv python3-pip python3-numpy python3-tk ffmpeg
mkdir -p ~/urc-video-vm
cd ~/urc-video-vm
git clone --branch feat/ros2-video-vm https://github.com/CU-URC-2027/C2.git repo
/usr/bin/python3 -m venv --system-site-packages venv
cd repo
mkdir -p artifacts
uv export --frozen --no-dev --no-emit-project --no-emit-package urc-video-protocol \
  -o artifacts/c2-requirements.txt
uv export --frozen --project prototypes/video_pipeline --no-dev --no-emit-project \
  --no-emit-package urc-video-protocol -o artifacts/rover-requirements.txt
../venv/bin/python -m pip install --require-hashes -r artifacts/c2-requirements.txt
../venv/bin/python -m pip install --require-hashes -r artifacts/rover-requirements.txt
../venv/bin/python -m pip install --no-deps -e packages/video_protocol
```

Both sets were installed in each acceptance VM for a common environment. Separate
role environments are also possible, but build the interfaces with the interpreter
each role will actually use. The prototype lock selects NumPy 1.26 on Linux/Python
3.12. A NumPy 2.5.4 ARM wheel produced illegal-instruction failures in these VMs;
Ubuntu's 1.26.4 imported and published typed ROS messages successfully. Mac dependency
selection remains NumPy 2. Do not replace system ROS Python with a downloaded uv
interpreter or install incompatible NumPy while attempting a media workaround.

Build only the new interface package, on **both** VMs:

```sh
source /opt/ros/jazzy/setup.bash
mkdir -p ~/urc-video-vm/ros_ws/src
ln -s ~/urc-video-vm/repo/prototypes/video_pipeline/ros2/urc_video_interfaces \
  ~/urc-video-vm/ros_ws/src/urc_video_interfaces
cd ~/urc-video-vm/ros_ws
colcon build --packages-select urc_video_interfaces --cmake-args \
  -DPython3_EXECUTABLE="$HOME/urc-video-vm/venv/bin/python" \
  -DPYTHON_EXECUTABLE="$HOME/urc-video-vm/venv/bin/python"
```

The example addresses below are the tested private guest addresses; substitute the
actual addresses on a new network. Configure C2:

```sh
cd ~/urc-video-vm/repo
../venv/bin/python scripts/configure_video_tcp.py c2 \
  --address 10.211.55.6 --c2-address 10.211.55.6 \
  --overlay ~/urc-video-vm/ros_ws/install --output ~/urc-video-vm/network
```

Configure rover similarly, with role `rover`, `--address 10.211.55.7` and the same
C2 address. The script writes explicit opt-in `network/env.bash` and `tcp.xml`;
it does not change shell startup, firewall, SSH or chassis configuration.

## Generate and run the pre-encoded test

Generate fixtures **once, offline** on a machine with FFmpeg/libx264. This is explicit
software fixture generation, with no software encoder running in the VM pipeline.
Copy the resulting entire directory to the rover VM if generated elsewhere.

```sh
cd ~/urc-video-vm/repo/prototypes/video_pipeline
~/urc-video-vm/venv/bin/python make_fixtures.py --output ~/urc-video-vm/fixtures
```

This creates 31 finite, distinct H.264 fixtures plus a hashed manifest: seven profiles
for Camera 01 and six each for Camera 02–05. Fixtures include AUD framing, repeated
SPS/PPS, one-second IDR intervals and no B frames. Manifest dimensions/FPS/profile,
hashes, file count/size and required IDR parameter sets are validated at startup.
Keep fixtures/captures/builds ignored and outside the source tree or in `artifacts/`.

On the C2 VM:

```sh
source ~/urc-video-vm/network/env.bash
cd ~/urc-video-vm/repo
../venv/bin/python scripts/ros_video.py c2 --bind 10.211.55.6 --peer 10.211.55.7
```

On the rover VM:

```sh
source ~/urc-video-vm/network/env.bash
cd ~/urc-video-vm/repo
../venv/bin/python scripts/ros_video.py rover --peer 10.211.55.6 \
  --fixtures ~/urc-video-vm/fixtures
```

In the C2 VM browser, open `http://127.0.0.1:8870/#cameras`; in the rover VM browser,
open `http://127.0.0.1:8872/`. Send all five priorities in C2. In the lab enable
**video streams → fixture replay → transmission**. In C2 click **Start live video**.
Each is a separate control and defaults off after process restart. No motion link
or Enable action is required. The lab's budget is read-only in ROS mode: adjust
**Available bandwidth** and **Share available to video** in the real C2 Cameras UI.
These values simulate a comms allocation; they are not a measured link estimator.

The ReplayBank allocates no raw frames or preview conversions. ReplayWorker loops
the selected fixture at its declared FPS, produces monotonic PTS/sequences, changes
sessions for format changes, supplies IDR recovery, and uses the existing bounded
encoded-output handoff and transmission queues. Disabling it joins its threads.
The raw route explicitly rejects replay mode. Lab labels identify `preencoded_test`
and hardware remains unvalidated. Omit `--fixtures` only for a deliberate real encoder
port/test following [HARDWARE_ADAPTERS.md](../prototypes/video_pipeline/HARDWARE_ADAPTERS.md).
There is no automatic fallback from hardware encoding to replay/software.

## Optional browser viewing from the Mac host

HTTP remains localhost-bound in both apps. For this trusted private Parallels test,
`scripts/preview_forward.py` provides an explicit, exact-peer, bounded TCP forward.
It does not authenticate users; stop it when no longer needed. The tested host bridge
address was `10.211.55.2`.

Run on the C2 VM (a separate terminal):

```sh
~/urc-video-vm/venv/bin/python ~/urc-video-vm/repo/scripts/preview_forward.py \
  --listen 10.211.55.6 --port 8890 --target 127.0.0.1 --target-port 8870 \
  --allow-peer 10.211.55.2
```

On the rover VM use listen `10.211.55.7` and target port `8872`. On the Mac, from
the repository root, run each in a separate terminal:

```sh
python3 scripts/preview_forward.py --listen 127.0.0.1 --port 8890 \
  --target 10.211.55.6 --target-port 8890 --allow-peer 127.0.0.1
python3 scripts/preview_forward.py --listen 127.0.0.1 --port 8892 \
  --target 10.211.55.7 --target-port 8890 --allow-peer 127.0.0.1
```

Open [VM C2](http://127.0.0.1:8890/#cameras) and [VM lab](http://127.0.0.1:8892/).
The localhost origin also supplies the secure browser context WebCodecs needs.
Browser rendering was tested on the Mac using these forwards; Ubuntu desktop browser
decoding was not validated. ROS and encoded video still traverse the two guest IP
stacks. The original Mac services at 8870/8872, if present, are separate processes.

## Acceptance and limits

The November 3 run passed the full shared host verification (22 checks, including
49 backend and 75 prototype tests), both real Jazzy interface builds, typed ROS
traffic and these actual browser/VM scenarios:

| Test input/action | Observed result |
| --- | --- |
| 20 Mb/s, 70% video share | All five received/decoded/rendered; priority-dependent HD/SD profiles within provisional Sigma limits |
| 10 Mb/s, 70% share | All five played after upgrade stabilization; final snapshot had one 1080p30, two 360p30 and two 360p15 feeds |
| 1 Mb/s, 70% share | Primary only at 640×360/30 |
| 400 kb/s, 70% share | Primary only at 320×180/15 |
| Zero bandwidth | No active media workers/flows; browser feeds become stale |
| Camera 05 first, others omitted | Only Camera 05 selected/transmitted |
| Sender reconnect plus C2 receiver restart | All five returned with new connection epochs |
| Pause/resume actual C2 publication | Inputs expire and output stops, then all five recover |
| Restart both applications | Fresh ROS sessions reconnect; all workloads stay off until explicitly enabled; five-feed playback works again |

Independent FFprobe inspection checked all 31 files' actual H.264 dimensions, frame
counts and absence of B frames. Raw elementary-stream frame-rate inference is not
the replay clock; the manifest/worker schedules FPS. An 8,635-packet NIC capture
contained both ROS TCP directions on 5100 and 15 media connection epochs on 8874.
Remote source-to-receiver ages remain unknown (`null`), even if a remote sender claims
a shared clock. No clock synchronization or end-to-end latency measurement is claimed.
Shared URV1/URB1 framing is unchanged; only explicit bind/destination configuration and
the existing remote clock-scope value are used.

**Replay has a fixed bitrate per fixture/profile.** A same-profile target bitrate
change does not re-encode or rewrite it. The UI exposes requested, fixture nominal and
measured rates separately; short repeated clips and IDR bursts can exceed the nominal
fixture rate. Application pacing/deadlines remain active. These tests validate policy,
format changes, ordering, shutdown, transport and recovery, not live rate-control
accuracy or quality. The Sigma limits (five sessions, 248.832 MP/s output, 20% bitrate
headroom) remain planning estimates. VM CPU/browser render limits, a virtual network
on one host, hardware encoding, physical cameras, radio impairment, actual comms
estimation and independent-host clock mapping still require separate tests.

After testing: C2 **Stop live video**, then lab **Disable transmission → Disable
output → Disable video streams**. Confirm zero jobs/subscribers/viewers and no
source/encoder processes. Ctrl-C stops each application/forward; restarting apps
does not restore workload toggles. Services may remain ready with all workloads off.
Detailed JSON snapshots, packet capture and screenshots stay in local ignored
`artifacts/`; they are not team approval or hardware acceptance.
