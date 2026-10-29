"""Application-level, full-duplex link simulator using real loopback UDP sockets.

Capacity is applied separately in each direction. Packets incur serialization
time (payload + 28-byte IPv4/UDP overhead) and configurable propagation delay.
This shapes only packets routed through it, not the Mac's network interfaces.
"""
import asyncio
from collections import deque
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class LinkConfig:
    bandwidth_bps: int = 10_000_000
    latency_ms: float = 40.0

    def validate(self):
        if type(self.bandwidth_bps) is not int or not 0 <= self.bandwidth_bps <= 1_000_000_000:
            raise ValueError("Bandwidth must be an integer from 0 to 1,000,000,000 bps")
        if (type(self.latency_ms) not in (int, float) or not math.isfinite(self.latency_ms)
                or not 0 <= self.latency_ms <= 2000):
            raise ValueError("One-way latency must be between 0 and 2000 ms")


class Receiver(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self.callback = callback
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        self.callback(data, address)

    def error_received(self, exc):
        pass


class Direction:
    MAX_QUEUE = 16

    def __init__(self, name, link):
        self.name, self.link = name, link
        self.queue = deque()
        self.ready = asyncio.Event()
        self.transport = self.worker = None
        self.address = self.peer = self.destination = None
        self.deliveries = set()
        self.stats = {"sent_packets": 0, "sent_payload_bytes": 0, "dropped_packets": 0,
                      "rejected_packets": 0, "last_delay_ms": None}

    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: Receiver(self.receive),
                                                                local_addr=("127.0.0.1", 0))
        self.address = self.transport.get_extra_info("sockname")
        self.worker = asyncio.create_task(self.run())

    def receive(self, data, address):
        if address != self.peer or not 1 <= len(data) <= 4096:
            self.stats["rejected_packets"] += 1
            return
        if self.link.config.bandwidth_bps == 0 or len(self.queue)+len(self.deliveries) >= self.MAX_QUEUE:
            self.stats["dropped_packets"] += 1
            return
        self.queue.append((data, time.monotonic(), self.link.epoch))
        self.ready.set()

    def clear(self):
        self.stats["dropped_packets"] += len(self.queue)
        self.queue.clear()

    async def run(self):
        while True:
            await self.ready.wait()
            while self.queue:
                packet = self.queue.popleft()
                data, arrived, epoch = packet
                remaining = (len(data)+28)*8
                aborted = False
                while remaining > 0:
                    capacity = self.link.config.bandwidth_bps
                    if capacity == 0 or epoch != self.link.epoch:
                        aborted = True
                        break
                    before = time.monotonic()
                    await asyncio.sleep(min(.02, remaining/capacity))
                    remaining -= capacity*(time.monotonic()-before)
                if aborted:
                    self.stats["dropped_packets"] += 1
                    continue
                # Propagation overlaps the serialization of following packets.
                task = asyncio.create_task(self.deliver(data, arrived, epoch, self.link.config.latency_ms))
                self.deliveries.add(task)
                task.add_done_callback(self.deliveries.discard)
            self.ready.clear()

    async def deliver(self, data, arrived, epoch, latency_ms):
        await asyncio.sleep(latency_ms/1000)
        if epoch != self.link.epoch or self.link.config.bandwidth_bps == 0:
            self.stats["dropped_packets"] += 1
            return
        self.transport.sendto(data, self.destination)
        self.stats["sent_packets"] += 1
        self.stats["sent_payload_bytes"] += len(data)
        self.stats["last_delay_ms"] = (time.monotonic()-arrived)*1000

    def state(self):
        return dict(self.stats, queued_packets=len(self.queue), propagating_packets=len(self.deliveries))

    async def close(self):
        tasks = [task for task in [self.worker, *self.deliveries] if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.transport:
            self.transport.close()
        self.queue.clear()


class SimulatedLink:
    def __init__(self, config=LinkConfig()):
        config.validate()
        self.config, self.epoch = config, 0
        self.up = Direction("c2_to_rover", self)
        self.down = Direction("rover_to_c2", self)

    async def start(self):
        await self.up.start()
        await self.down.start()

    def configure(self, config):
        config.validate()
        self.config = config
        if config.bandwidth_bps == 0:
            self.epoch += 1
            self.up.clear()
            self.down.clear()

    def state(self):
        return {"bandwidth_bps": self.config.bandwidth_bps, "latency_ms": self.config.latency_ms,
                "link_up": self.config.bandwidth_bps > 0, "duplex": "symmetric full duplex",
                "transport": "loopback UDP through application shaper", "queue_limit_per_direction": Direction.MAX_QUEUE,
                "c2_to_rover": self.up.state(), "rover_to_c2": self.down.state(),
                "scope": "Control/status messages only; source monitors and raw video do not traverse this link yet"}

    async def close(self):
        await self.up.close()
        await self.down.close()
