# C2 browser port development

- Keep the canonical `c2_prototype/` synchronized with the reviewed upstream backend baseline (currently `c2-net5-recovery` at `971aec7`); preserve the historical `C2-team/` copy. Browser work belongs in `c2_web/`, `web/`, `tests/`, `scripts/`, and `docs/`.
- Scope is a browser UI port with backend-owned video priority configuration/publication. Keep existing generated-demo/HTTP snapshot features. Do not add video encoders or a production video transport; the local priority datagrams carry configuration only. Keep the separate architecture lab out of this repository.
- Read `docs/ARCHITECTURE.md` and `docs/PORT_PARITY.md` before changing control behavior. A server tick, transport ping, or repeated sequence must never renew operator input freshness.
- Start disconnected and disarmed. Reconnection, STOP reset, source change, or input recovery must not restore motion automatically. Preserve independent rover-side authority and watchdogs.
- Use only local mocks and synthetic media for automated testing. Physical motors, cameras, serial devices, and network receivers require a deliberate human test setup.
- Keep runtime logs, captured GPS, URLs with credentials, and local environment files out of Git. Do not deploy or expose the command station to a network by changing its bind address.
- Run `uv run pytest`, `uv run python -m unittest discover -s c2_prototype -p 'test_*.py'`, `node tests/controller_test.mjs`, and `node --check web/app.js`. Changes to OC behavior also need the upstream ROS chassis host tests. Never claim DDS execution from host-only tests.
- Keep engineering status explicit: arm is a preview, pose is a command model, RC is emulated, and ROS/DDS needs its actual runtime. OC loopback uses the upstream Python policy/bridge without DDS. Automated software checks do not establish hardware validation or team approval.
