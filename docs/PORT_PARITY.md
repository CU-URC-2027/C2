# Desktop → browser parity

October 27, 2026. Scope is the repository's 0.4 desktop prototype, not a complete field-ready C2 system. Original source files are preserved.

| Existing behavior | Browser implementation | Engineering status |
| --- | --- | --- |
| Drive mixing, wheel cap, deadman, neutral enable | Same `Control`, virtual stick, keyboard and standard Gamepad API | Software policy tested; physical mapping needs validation |
| Xbox controller via pygame | Browser standard gamepad, left Y / right X, LB hold | No physical controller exercised in this build |
| RC source demo | RC emulation selector | Preview only; blocked from connected chassis |
| STOP / reset / disarm | Persistent safety bar and Esc; reset stays disarmed | Mock/unit tested; independent physical stop required |
| Guarded UDP connection | Same `RoverLink`, host/port controls and explicit enable | Loopback mock tested; no rover operated |
| Local mock, ACK-loss injection | Connections page | Real loopback UDP and independent mock watchdog |
| Arm joint jog | All five joints and hold-to-jog command preview | No hardware transport; chassis disconnected |
| Command trajectory and wheel values | Canvas path, pose, wheel meters/history | Explicit toy model, not odometry |
| Four camera panes | Four generated-demo/HTTP snapshot slots | Existing functionality ported; future camera design remains open |
| Demo camera images | Moving synthetic JPEG grid | No camera opened |
| GPS serial / rover / demo | Headless serial adapter, guarded rover NMEA, synthetic mode | Parser and synthetic modes tested; no USB GPS accessed |
| GPS validity / scatter / local track | Same parser/statistics, browser metrics/plots | Precision semantics retained |
| Reference comparison | JSONL import, sample/error/bias metrics, overlay plot | Same coordinate/timestamp comparison algorithm |
| Command / GPS logging | Bounded memory buffers and JSONL downloads | No automatic disk capture; schema described in development guide |
| UI event/status display | Shared station event history and raw feedback | Backend owns state; multiple tabs share it |
| Safety on input loss | Independent backend task and new-input deadline | Tested, including recovery requiring deliberate enable |
| Browser authority / connection loss | Single operator; all viewers can STOP/disarm | New behavior; loopback application only |

Additional honest boundaries: battery is unavailable, final supervisor/ROS 2 is planned, physical networking and timing are unvalidated. Serial ports and real controller mapping await hardware-specific tests. Camera streaming/encoding architecture is intentionally outside this port, per the user's October 27 clarification.

See `VALIDATION.md` for observed checks and known limits. This is AI-assisted prototype implementation requiring substantive human review and validation under the course policy; it is not an approved design or submission-ready artifact.
