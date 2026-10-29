# C2 browser port development

- Preserve `c2_prototype/` and `C2-team/` as the original desktop baseline. Browser work belongs in `c2_web/`, `web/`, `tests/`, `scripts/`, and `docs/`.
- Scope is a browser UI port. Keep the existing generated-demo/HTTP snapshot camera features. Do not select or implement a video encoder, streaming transport, or camera architecture without the user's direction.
- Read `docs/ARCHITECTURE.md` and `docs/PORT_PARITY.md` before changing control behavior. A server tick, transport ping, or repeated sequence must never renew operator input freshness.
- Start disconnected and disarmed. Reconnection, STOP reset, source change, or input recovery must not restore motion automatically. Preserve independent rover-side authority and watchdogs.
- Use only local mocks and synthetic media for automated testing. Physical motors, cameras, serial devices, and network receivers require a deliberate human test setup.
- Keep runtime logs, captured GPS, URLs with credentials, and local environment files out of Git. Do not deploy or expose the command station to a network by changing its bind address.
- Run `uv run pytest`, `uv run python -m unittest discover -s c2_prototype -p 'test_*.py'`, and `node --check web/app.js`.
- Keep engineering status explicit: arm is a preview, pose is a command model, RC is emulated, and final supervisor/ROS 2 integration is planned. Automated software checks do not establish hardware validation or team approval.
