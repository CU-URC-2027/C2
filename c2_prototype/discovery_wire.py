"""Read-only LAN discovery; these packets never enter the command state machine."""
import json
import re

MARKER = "C2DISC1,"


def query(nonce):
    if not re.fullmatch(r"[0-9a-f]{16}", nonce):
        raise ValueError("Invalid discovery nonce")
    return (MARKER+nonce+"\n").encode("ascii")


def parse_query(data):
    try:
        text = data.decode("ascii")
    except UnicodeError:
        return None
    return text[8:24] if re.fullmatch(r"C2DISC1,[0-9a-f]{16}\n?", text) else None


def parse_reply(data, nonce):
    if len(data) > 2048:
        raise ValueError("Discovery reply too large")
    row = json.loads(data)
    if not isinstance(row, dict) or row.get("type") != "c2_discovery" or row.get("v") != 1 or row.get("nonce") != nonce:
        raise ValueError("Unrelated discovery reply")
    if row.get("control_protocol") != "C2V1" or row.get("watchdog_ms") != 250:
        raise ValueError("Incompatible rover protocol")
    if not isinstance(row.get("device_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", row["device_id"]):
        raise ValueError("Invalid device identity")
    if type(row.get("control_port")) is not int or not 1024 <= row["control_port"] <= 65535:
        raise ValueError("Invalid discovery control port")
    if any(type(row.get(k)) is not bool for k in ("busy", "enabled", "stopped")):
        raise ValueError("Invalid rover availability")
    if row["enabled"] and (row["stopped"] or not row["busy"]):
        raise ValueError("Contradictory rover availability")
    return {k: row[k] for k in ("device_id", "control_port", "busy", "enabled", "stopped")} | {
        "build": str(row.get("build", "unknown"))[:100], "boot_id": str(row.get("boot_id", "unknown"))[:80]}
