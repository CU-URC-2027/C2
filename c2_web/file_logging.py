"""Opt-in diagnostics with bounded, nonblocking submission and one disk worker."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
from queue import Empty, Full, Queue
import subprocess
import threading
import time
import uuid


class DiagnosticLog:
    def __init__(self, repository=None, queue_limit=2048, flush_interval=1.0):
        self.repository = repository
        self.queue_limit = queue_limit
        self.flush_interval = flush_interval
        self.enabled = False
        self.directory = self.path = self.error = None
        self.written = self.dropped = self.bytes_written = 0
        self.started_utc = self.flushed_utc = None
        self._queue = Queue(maxsize=queue_limit)
        self._thread = None
        self._stop = threading.Event()
        self._reason = "Operator disabled logging"

    @staticmethod
    def utc():
        return datetime.now(timezone.utc).isoformat()

    def start(self, directory, initial):
        """Call off the event loop: path validation/opening can touch slow disks."""
        if self.enabled or (self._thread and self._thread.is_alive()):
            raise ValueError("Stop the current log before starting another")
        try:
            if not isinstance(directory, str) or not directory.strip() or len(directory) > 4096:
                raise ValueError("Enter an existing absolute folder path on the backend computer")
            folder = Path(directory.strip()).expanduser()
            if not folder.is_absolute():
                raise ValueError("Use an absolute folder path (or ~ for your home folder)")
            folder = folder.resolve(strict=True)
            if not folder.is_dir():
                raise ValueError("The log destination must be an existing folder")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            path = folder / f"c2-diagnostics-{stamp}-{uuid.uuid4().hex[:8]}.jsonl"
            # Exclusive creation: never truncate an existing file; private by default.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                stream = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
            except BaseException:
                os.close(fd)
                raise
        except (OSError, RuntimeError, ValueError) as exc:
            self.error = f"Cannot start file logging: {exc}"
            raise ValueError(self.error) from exc
        self.directory, self.path = str(folder), str(path)
        self.error = None
        self.written = self.dropped = self.bytes_written = 0
        self.started_utc, self.flushed_utc = self.utc(), None
        self._queue = Queue(maxsize=self.queue_limit)
        self._stop = threading.Event()
        self._reason = "Operator disabled logging"
        revision = dirty = None
        if self.repository:
            try:
                revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repository,
                                                   timeout=1, stderr=subprocess.DEVNULL, text=True).strip()
                dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                                     cwd=self.repository, timeout=1, text=True).strip())
            except (OSError, subprocess.SubprocessError):
                pass
        self._queue.put_nowait({"type": "session_start", "utc": self.started_utc,
                               "schema_version": 1, "git_revision": revision, "git_dirty": dirty,
                               "pid": os.getpid(), "platform": platform.platform(),
                               "python": platform.python_version(), "initial": initial})
        self.enabled = True
        self._thread = threading.Thread(target=self._write, args=(stream,), name="c2-diagnostic-log", daemon=True)
        self._thread.start()

    def submit(self, kind, data):
        """No JSON serialization, filesystem access or waiting on the control thread.

        Callers pass immutable snapshots, not objects the runtime will later mutate.
        """
        if not self.enabled:
            return
        try:
            self._queue.put_nowait({"type": kind, "utc": self.utc(), "data": data})
        except Full:
            self.dropped += 1

    def _write_record(self, stream, row):
        line = json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n"
        stream.write(line)
        self.written += 1
        self.bytes_written += len(line.encode("utf-8"))

    def _write(self, stream):
        reported_drops, last_flush = 0, time.monotonic()
        try:
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    row = self._queue.get(timeout=.1)
                except Empty:
                    row = None
                if row is not None:
                    self._write_record(stream, row)
                if self.dropped != reported_drops:
                    self._write_record(stream, {"type": "log_gap", "utc": self.utc(),
                                                "dropped_records_total": self.dropped})
                    reported_drops = self.dropped
                if time.monotonic()-last_flush >= self.flush_interval or (row and row["type"] != "tick"):
                    stream.flush()
                    self.flushed_utc, last_flush = self.utc(), time.monotonic()
            self._write_record(stream, {"type": "session_end", "utc": self.utc(), "reason": self._reason,
                                        "dropped_records_total": self.dropped})
            stream.flush()
            self.flushed_utc = self.utc()
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"File logging stopped: {type(exc).__name__}: {exc}"
        finally:
            self.enabled = False
            try:
                stream.close()
            except OSError as exc:
                self.error = f"File log close failed: {exc}"
            # Discard queued snapshots on write failure, preserving the loss count.
            while True:
                try:
                    self._queue.get_nowait()
                    self.dropped += 1
                except Empty:
                    break

    def stop(self, reason="Operator disabled logging"):
        """Call off the event loop. A stalled disk must not hold up motion expiry."""
        self.enabled = False
        self._reason = reason
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                self.error = "Log writer is still stopping; the disk may be unresponsive"

    def state(self):
        return {"enabled": self.enabled, "directory": self.directory, "path": self.path,
                "written_records": self.written, "bytes_written": self.bytes_written,
                "queued_records": self._queue.qsize(), "queue_limit": self.queue_limit,
                "dropped_records": self.dropped, "error": self.error,
                "started_utc": self.started_utc, "last_flush_utc": self.flushed_utc,
                "stopping": bool(not self.enabled and self._thread and self._thread.is_alive())}
