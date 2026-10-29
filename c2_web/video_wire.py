"""Compatibility imports; the canonical contract is packages/video_protocol."""
from urc_video_protocol import (
    MAGIC, BROWSER_MAGIC, HEADER, META, MAX_META, MAX_PAYLOAD, STREAM_IDS,
    validate, pack, pack_browser, read, nal_info,
)
