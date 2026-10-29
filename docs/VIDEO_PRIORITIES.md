# C2-owned video priority inputs

The Python C2 backend owns the Camera 01–05 order and enabled/omitted boundary. The browser's Cameras page edits a draft and submits it over the existing owner-checked WebSocket as `video_priorities`, with `ordered_stream_ids`, `enabled_count`, and `expected_revision`. Every known ID (`cam-01` … `cam-05`) must occur exactly once. Positions before `enabled_count` are enabled, in priority order; the rest are explicitly omitted. All/none enabled are valid.

`c2_web/priorities.py` retains the accepted configuration for the life of the backend process and publishes it every 500 ms to an independent local receiver. Browser reload/closure does not stop configuration publication. This heartbeat is unrelated to operator motion input; it never refreshes a chassis input timestamp. Server restart creates a new source session and restores the initial all-enabled numeric order.

The initial adapter is loopback UDP at `127.0.0.1:8873`, configured on the Cameras page. It sends no raw/encoded video and is not a selected production video transport. Publication can be paused explicitly or disabled for a process with `C2_VIDEO_PRIORITIES_ENABLED=0`. Ordinary tests disable the default publisher to avoid affecting an independently running receiver.

Example envelope (revision/count/order are illustrative inputs):

```json
{
  "type": "feed_priorities",
  "publisher": {"service": "urc-c2-web", "pid": 12345},
  "data": {
    "schema_version": 1,
    "source_session": "a32characterlowercasehexsessionid",
    "sequence": 42,
    "revision": 2,
    "ordered_stream_ids": ["cam-05", "cam-01", "cam-02", "cam-03", "cam-04"],
    "enabled_count": 2
  }
}
```

The receiver replies to the actual sender IP/port with:

```json
{"type":"priority_ack","source_session":"a32characterlowercasehexsessionid","sequence":42,"revision":2}
```

An ACK must arrive from the configured receiver and match a retained sent sequence, session and configuration revision. The C2 UI reports its age and round trip. A missing receiver affects this configuration status only, not the chassis control task. PID/source session and socket address make the actual publisher observable; they are not authentication. All socket endpoints remain local in this adapter.

`GET /api/video/priorities` exposes current backend-owned state for observation, including PID, source session, local/destination addresses, sent/acknowledged revisions and freshness. The private architecture viewer is an independent subscriber and is not part of this repository. It must not synthesize or own a replacement C2 configuration. A future ROS 2 or other transport adapter can use the same configuration contract after interface review.
