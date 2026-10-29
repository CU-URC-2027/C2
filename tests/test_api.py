import json

from fastapi.testclient import TestClient
import pytest

from c2_web.api import create_app


def ack(ws, action, data=None):
    ws.send_json({"action": action, "data": data or {}, "request_id": 1})
    while True:
        message = ws.receive_json()
        if message["type"] == "ack":
            return message


def test_http_resources_and_origin_boundary():
    with TestClient(create_app()) as c:
        assert c.get("/").status_code == 200
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/health").json()["running"]
        assert c.get("/api/state").json()["control"]["left"] == 0
        assert c.get("/api/state", headers={"Origin": "https://other.example"}).status_code == 403
        assert c.get("/api/state", headers={"Host": "other.example"}).status_code == 403
        assert c.get("/api/logs/commands").headers["content-type"].startswith("application/x-ndjson")
        assert len(c.get("/api/gps/example").text.splitlines()) == 21


def test_websocket_invalid_input_disarms_and_disconnect_clears_owner():
    app = create_app()
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ack(ws, "input", {"seq": 0})["ok"]
            assert ack(ws, "enable")["ok"]
            assert app.state.station.control.armed
            assert not ack(ws, "input", {"seq": 1, "throttle": "bad"})["ok"]
            assert not app.state.station.control.armed
            assert ack(ws, "stop")["ok"]
            assert app.state.station.control.stopped
            assert ack(ws, "reset_stop")["ok"]
            assert not app.state.station.control.armed
        assert app.state.station.owner is None


def test_snapshot_demo_and_camera_errors():
    with TestClient(create_app()) as c:
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert ack(ws, "camera", {"camera": "front", "mode": "demo"})["ok"]
            image = c.get("/api/cameras/front/image")
            assert image.status_code == 200 and image.content.startswith(b"\xff\xd8")
            assert not ack(ws, "camera", {"camera": "front", "mode": "snapshot", "url": "file:///etc/hosts"})["ok"]
            assert c.get("/api/cameras/front/image").status_code == 404


def test_cross_origin_websocket_rejected():
    from starlette.websockets import WebSocketDisconnect
    with TestClient(create_app()) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws", headers={"Origin": "https://other.example"}):
                pass
