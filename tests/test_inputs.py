from io import BytesIO

import httpx
from PIL import Image
import pytest

from c2_web.inputs import fetch_snapshot


def image_bytes():
    out = BytesIO()
    Image.new("RGB", (8, 8)).save(out, format="PNG")
    return out.getvalue()


@pytest.mark.parametrize("content_type,body,status,works", [
    ("image/png", image_bytes(), 200, True),
    ("text/html", b"<html>not a camera</html>", 200, False),
    ("image/jpeg", b"invalid jpeg", 200, False),
    ("image/png", b"x"*(4*1024*1024+1), 200, False),
    ("image/png", b"", 302, False),
])
async def test_snapshot_boundary(monkeypatch, content_type, body, status, works):
    original = httpx.AsyncClient
    def client(**kwargs):
        return original(transport=httpx.MockTransport(lambda req: httpx.Response(
            status, content=body, headers={"Content-Type": content_type})), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    if works:
        assert await fetch_snapshot("http://camera.test/snapshot") == body
    else:
        with pytest.raises((ValueError, httpx.HTTPError, OSError)):
            await fetch_snapshot("http://camera.test/snapshot")
