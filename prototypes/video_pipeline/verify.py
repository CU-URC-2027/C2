"""Exercise the running local source lab. Uses synthetic streams only.

Close/collapse other preview nodes before running so preview-idle checks have a
single owner. This probe does not pause sources or select an encoder.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import time

import httpx
from PIL import Image

from sources import SPECS

URL = "http://127.0.0.1:8872"


def state():
    response = httpx.get(URL+"/api/state", timeout=5)
    response.raise_for_status()
    return response.json()


def probe_raw(spec):
    response = httpx.get(f"{URL}/sources/{spec.id}.nv12?frames=3", timeout=8)
    response.raise_for_status()
    assert response.headers["x-pixel-format"] == "nv12"
    assert int(response.headers["x-width"]) == spec.width
    assert int(response.headers["x-height"]) == spec.height
    assert len(response.content) == spec.frame_bytes*3
    hashes = [hashlib.sha256(response.content[i*spec.frame_bytes:(i+1)*spec.frame_bytes]).hexdigest()
              for i in range(3)]
    assert len(set(hashes)) == 3, "The moving source must advance between raw frames"
    return {"source": spec.id, "dimensions": [spec.width, spec.height],
            "pixel_format": "nv12", "frames": 3, "bytes": len(response.content), "distinct_frames": True}


def main():
    first = state()
    assert not first["previews_enabled"], "Collapse the preview node before running this probe"
    time.sleep(.7)
    second = state()
    assert all(s["running"] for s in second["sources"])
    assert all(b["sequence"] > a["sequence"] for a, b in zip(first["sources"], second["sources"]))
    assert [s["preview_count"] for s in first["sources"]] == [s["preview_count"] for s in second["sources"]]
    with ThreadPoolExecutor(max_workers=5) as pool:
        raw = list(pool.map(probe_raw, SPECS))
    client = "verification"
    httpx.post(f"{URL}/api/previews/{client}", json={"visible": True}).raise_for_status()
    try:
        time.sleep(.4)
        previews = []
        for spec in SPECS:
            response = httpx.get(f"{URL}/preview/{spec.id}.jpg")
            response.raise_for_status()
            image = Image.open(BytesIO(response.content))
            assert image.size == (480, 270)
            previews.append(hashlib.sha256(response.content).hexdigest())
        assert len(set(previews)) == 5
    finally:
        httpx.post(f"{URL}/api/previews/{client}", json={"visible": False}).raise_for_status()
    time.sleep(.3)
    idle = state()
    time.sleep(.6)
    after = state()
    assert not after["previews_enabled"]
    assert [s["preview_count"] for s in idle["sources"]] == [s["preview_count"] for s in after["sources"]]
    assert all(b["sequence"] > a["sequence"] for a, b in zip(idle["sources"], after["sources"]))
    result = {"date": date.today().isoformat(), "raw_probes": raw, "preview_images_distinct": True,
              "preview_dimensions": [480, 270], "collapsed_preview_counts_stable": True,
              "sources_advance_without_previews": True,
              "fps_observed": {s["id"]: round(s["fps_actual"], 3) for s in after["sources"]}}
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    (output/"source-verification.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
