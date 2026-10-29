# Shared video protocol

- Read README.md and `../../docs/VIDEO_SYSTEM.md` before changing the contract.
- `urc_video_protocol/__init__.py` is the one canonical Python framing implementation.
  C2 and the video prototype import this local package through their locked environments.
  Do not add another serializer copy or import a running app into this package.
- Keep it standard-library only. No sockets are opened here; `read` only consumes
  an already-owned async reader. No media processing, control authority or policy.
- URV1 and URB1 are version identities. Keep byte lengths, units, validation bounds,
  clock scope and keyframe/session meanings compatible, or introduce an explicitly
  reviewed version and update sender, receiver, browser and contract tests together.
- Run the repository's `uv run --frozen python scripts/verify.py` after changes.
  The C2 wire tests cover fragmentation/invalid records; prototype tests assert both
  compatibility shims use this same implementation. Host checks do not prove codecs.
