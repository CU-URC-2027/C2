"""Explicit bounded UDP discovery plus local saved endpoint settings; no auto-enable."""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
from .legacy import ROOT
from discovery_wire import query, parse_reply


class RoverDiscovery:
    def __init__(self):
        self.task = None
        self.candidates = []
        self.error = None
        self.rejected = 0
        self.stop_event = threading.Event()

    def start(self, host="255.255.255.255", port=4210, local_ipv4="0.0.0.0"):
        if self.task and not self.task.done():
            raise ValueError("A discovery scan is already running")
        ip, local = ipaddress.IPv4Address(host), ipaddress.IPv4Address(local_ipv4)
        if ip.is_multicast or ip.is_unspecified or not (ip.is_private or str(ip)=="255.255.255.255"):
            raise ValueError("Discovery requires a local IPv4 address or LAN broadcast")
        if local.is_multicast or (not local.is_unspecified and not local.is_private):
            raise ValueError("Select a local interface IPv4 or 0.0.0.0 for automatic routing")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Discovery port must be from 1024 to 65535")
        self.error, self.rejected, self.candidates = None, 0, []
        self.stop_event = threading.Event()
        self.task = asyncio.create_task(asyncio.to_thread(self.scan,str(ip),port,str(local)))

    def scan(self, host, port, local):
        nonce = secrets.token_hex(8)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(.1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((local, 0))
            packet = query(nonce)
            deadline, next_probe, probes, replies = time.monotonic()+1.5, time.monotonic(), 0, 0
            broadcast = host=="255.255.255.255" or host.endswith(".255")
            while not self.stop_event.is_set() and time.monotonic()<deadline and replies<256:
                now = time.monotonic()
                if probes<2 and now>=next_probe:
                    sock.sendto(packet,(host,port))
                    probes += 1
                    next_probe = now+.5
                try:
                    data, address = sock.recvfrom(2049)
                except socket.timeout:
                    continue
                replies += 1
                try:
                    source = ipaddress.IPv4Address(address[0])
                    if not source.is_private or source.is_multicast or source.is_unspecified:
                        raise ValueError("Discovery reply is not from a local unicast address")
                    if not broadcast and address[0] != host:
                        raise ValueError("Reply from an unexpected endpoint")
                    row = parse_reply(data, nonce)
                    if row["control_port"] != address[1] or address[1] != port:
                        raise ValueError("Reply does not match the queried control port")
                    row["host"] = address[0]
                    # Keep distinct endpoints with the same claimed identity visible.
                    key = (row["device_id"], row["host"], row["control_port"])
                    self.candidates = [r for r in self.candidates if (r["device_id"],r["host"],r["control_port"])!=key]
                    if len(self.candidates)<16:
                        self.candidates.append(row)
                except (ValueError, TypeError, KeyError, UnicodeError):
                    self.rejected += 1
            if replies>=256: self.error = "Discovery reply limit reached; scan stopped"
        except OSError as exc:
            self.error = f"Discovery failed: {exc}"
        finally:
            sock.close()

    def state(self):
        return {"scanning": bool(self.task and not self.task.done()), "candidates": list(self.candidates),
                "error": self.error, "rejected_replies": self.rejected, "scope": "Two read-only probes in 1.5 seconds; no control claim"}

    async def close(self):
        if self.task:
            self.stop_event.set()
            await asyncio.gather(self.task, return_exceptions=True)


class RoverProfiles:
    def __init__(self):
        self.path = Path(os.environ.get("C2_PROFILE_PATH", ROOT/"data/rover_profiles.json"))
        self.profiles, self.error = [], None
        try:
            if self.path.exists():
                if self.path.stat().st_size>65536: raise ValueError("Profile settings exceed 64 KB")
                content = json.loads(self.path.read_text())
                if not isinstance(content, list) or len(content)>16: raise ValueError("Invalid saved rover list")
                self.profiles = [self.validate(r) for r in content]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error = f"Cannot load saved rovers: {exc}"

    @staticmethod
    def validate(row):
        host = str(ipaddress.IPv4Address(row["host"]))
        if ipaddress.IPv4Address(host).is_multicast or ipaddress.IPv4Address(host).is_unspecified or host=="255.255.255.255":
            raise ValueError("Profile needs a unicast IPv4 address")
        if type(row.get("port")) is not int or not 1024<=row["port"]<=65535: raise ValueError("Invalid saved port")
        if not isinstance(row.get("name"),str) or not 1<=len(row["name"].strip())<=60: raise ValueError("Use a rover name from 1 to 60 characters")
        identity = row.get("device_id")
        if identity is not None:
            import re
            if not isinstance(identity,str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,80}",identity): raise ValueError("Invalid saved identity")
        return {"id": identity or f"{host}:{row['port']}", "name": row["name"].strip(), "host": host,
                "port": row["port"], "device_id": identity}

    def save(self, row):
        row = self.validate(row)
        proposed = [r for r in self.profiles if r["id"]!=row["id"]]+[row]
        if len(proposed)>16: raise ValueError("At most 16 saved rovers")
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
                temp = stream.name
                json.dump(proposed,stream)
                stream.flush()
            os.replace(temp,self.path)
            self.profiles, self.error = proposed, None
        except OSError as exc:
            self.error = f"Cannot save rover profile: {exc}"
            raise ValueError(self.error) from exc
        finally:
            if temp and os.path.exists(temp): os.unlink(temp)

    def state(self):
        return {"profiles": list(self.profiles), "error": self.error, "auto_connect": False}
