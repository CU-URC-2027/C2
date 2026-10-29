import pytest


@pytest.fixture(autouse=True)
def isolate_priority_publisher(monkeypatch):
    # Ordinary tests must not publish into a separately running local receiver.
    monkeypatch.setenv("C2_VIDEO_PRIORITIES_ENABLED", "0")
