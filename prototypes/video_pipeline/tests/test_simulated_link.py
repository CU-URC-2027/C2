import asyncio
import json
import os
import uuid

from simulated_link import LinkConfig, Receiver
from status_runtime import StatusRuntime

IDS = [f'cam-{i:02}' for i in range(1, 6)]


async def until(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


class ExternalTestPublisher:
    """Test fixture only: production StatusRuntime has no publisher/editor."""
    def __init__(self, target):
        self.target, self.session = target, uuid.uuid4().hex
        self.sequence = 0
        self.acks = []
        self.transport = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: Receiver(lambda body, addr: self.acks.append(json.loads(body))), local_addr=('127.0.0.1', 0))

    def publish(self, revision=1, order=None, count=5):
        self.sequence += 1
        row = {'type':'feed_priorities', 'publisher':{'service':'urc-c2-web','pid':os.getpid()},
            'data':{'schema_version':1,'source_session':self.session,'sequence':self.sequence,
                'revision':revision,'ordered_stream_ids':order or IDS,'enabled_count':count}}
        self.transport.sendto(json.dumps(row).encode(), self.target)

    def close(self):
        if self.transport:self.transport.close()


def test_external_udp_round_trip_outage_and_recovery_require_actual_publication():
    async def run():
        runtime = StatusRuntime(IDS, LinkConfig(1_000_000, 50), ingress_port=0)
        await runtime.start()
        client = ExternalTestPublisher(runtime.ingress_address)
        await client.start()
        try:
            assert not runtime.manager.snapshot()['priorities_received']
            await asyncio.sleep(.55)
            assert not runtime.manager.snapshot()['priorities_received']  # No fallback C2 simulator.
            client.publish()
            await until(lambda: client.acks)
            assert runtime.rtt_ms >= 95
            assert runtime.state()['c2']['external'] and runtime.state()['c2']['publisher_pid'] == os.getpid()
            runtime.configure_link(LinkConfig(0, 50))
            client.publish(revision=2, order=IDS[::-1], count=2)
            await asyncio.sleep(.15)
            assert runtime.manager.snapshot()['priority_revision'] == 1
            assert runtime.manager.snapshot()['available_bandwidth_bps'] == 0
            runtime.configure_link(LinkConfig(2_000_000, 10))
            await asyncio.sleep(.08)
            assert runtime.manager.snapshot()['priority_revision'] == 1
            client.publish(revision=2, order=IDS[::-1], count=2)
            await until(lambda: runtime.ack_revision == 2)
            assert runtime.manager.snapshot()['ranked_stream_ids'] == IDS[::-1][:2]
            assert runtime.manager.snapshot()['omitted_stream_ids'] == IDS[::-1][2:]
        finally:
            client.close()
            await runtime.close()
    asyncio.run(run())


def test_low_bandwidth_and_zero_clear_inflight_input_without_synthesizing_a_new_one():
    async def run():
        runtime = StatusRuntime(IDS, LinkConfig(2000, 0), ingress_port=0)
        await runtime.start()
        client = ExternalTestPublisher(runtime.ingress_address)
        await client.start()
        try:
            client.publish()
            await asyncio.sleep(.15)
            assert runtime.manager.priorities is None
            runtime.configure_link(LinkConfig(0, 0))
            client.publish(revision=2, count=0)
            await asyncio.sleep(.1)
            runtime.configure_link(LinkConfig(10_000_000, 0))
            await asyncio.sleep(.08)
            assert runtime.manager.priorities is None
            client.publish(revision=2, count=0)
            await until(lambda: runtime.ack_revision == 2)
            assert runtime.manager.snapshot()['omitted_stream_ids'] == IDS
        finally:
            client.close()
            await runtime.close()
    asyncio.run(run())


def test_external_publisher_disappearance_does_not_generate_priority_heartbeats():
    async def run():
        runtime = StatusRuntime(IDS, LinkConfig(10_000_000, 0), ingress_port=0)
        await runtime.start()
        client = ExternalTestPublisher(runtime.ingress_address)
        await client.start()
        try:
            client.publish()
            await until(lambda: runtime.manager.priorities is not None)
            accepted = runtime.manager.priorities.sequence
            client.close()
            await asyncio.sleep(.6)
            assert runtime.manager.priorities.sequence == accepted
            runtime.manager.priority_received -= 4
            runtime.last_backend_packet -= 4
            assert runtime.state()['status_manager']['priorities_stale']
            assert not runtime.state()['c2']['connected']
        finally:
            client.close()
            await runtime.close()
    asyncio.run(run())


def test_new_external_backend_session_retires_the_previous_publisher():
    async def run():
        runtime = StatusRuntime(IDS, LinkConfig(10_000_000, 0), ingress_port=0)
        await runtime.start()
        first, replacement = [ExternalTestPublisher(runtime.ingress_address) for _ in range(2)]
        await first.start()
        await replacement.start()
        try:
            first.publish(revision=7)
            await until(lambda: first.acks)
            replacement.publish(revision=1, count=2)
            await until(lambda: replacement.acks)
            assert runtime.manager.priorities.source_session == replacement.session
            first.publish(revision=8)
            await asyncio.sleep(.04)
            assert runtime.state()['c2']['session'] == replacement.session
            assert runtime.manager.priorities.revision == 1
            assert runtime.invalid_packets == 1
        finally:
            first.close()
            replacement.close()
            await runtime.close()
    asyncio.run(run())
