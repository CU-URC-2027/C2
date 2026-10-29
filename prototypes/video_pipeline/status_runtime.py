"""Lab receiver/observer for an independently running Python C2 backend.

This process owns no C2 priority configuration and generates no C2 heartbeats.
Actual C2 datagrams enter a local ingress, cross the shaped link, and reach the
StatusManager. ACKs cross the reverse link and return to the original publisher.
"""
import asyncio
from collections import deque
import json
import os
import time
import uuid

from simulated_link import LinkConfig, Receiver, SimulatedLink
from status_manager import BandwidthInput, FeedPriorities, StatusManager


class StatusRuntime:
    def __init__(self, stream_ids, config=LinkConfig(), ingress_port=None):
        self.manager = StatusManager(stream_ids)
        self.link = SimulatedLink(config)
        self.ingress_port = int(os.environ.get('C2_VIDEO_INGRESS_PORT', '8873')) if ingress_port is None else ingress_port
        self.ingress_transport = self.rover_transport = None
        self.ingress_address = self.rover_address = None
        self.publisher_peer = self.publisher_pid = None
        self.published = None
        self.last_backend_packet = None
        self.bandwidth_session = uuid.uuid4().hex
        self.bandwidth_sequence = 0
        self.task = None
        self.running = False
        self.ack_revision = self.ack_sequence = self.last_ack = None
        self.rtt_ms = None
        self.packet_receipts = {}
        self.retired_publishers = set()
        self.invalid_packets = 0
        self.events = deque(maxlen=40)

    def event(self, message):
        self.events.appendleft({'time': time.strftime('%H:%M:%S'), 'message': message})

    async def start(self):
        loop = asyncio.get_running_loop()
        self.rover_transport, _ = await loop.create_datagram_endpoint(lambda: Receiver(self.receive_rover),
            local_addr=('127.0.0.1', 0))
        self.rover_address = self.rover_transport.get_extra_info('sockname')
        await self.link.start()
        self.ingress_transport, _ = await loop.create_datagram_endpoint(lambda: Receiver(self.receive_ingress),
            local_addr=('127.0.0.1', self.ingress_port))
        self.ingress_address = self.ingress_transport.get_extra_info('sockname')
        self.link.up.peer, self.link.up.destination = self.ingress_address, self.rover_address
        self.link.down.peer, self.link.down.destination = self.rover_address, self.ingress_address
        self.running = True
        self.publish_bandwidth()
        self.task = asyncio.create_task(self.run())
        self.event(f'Listening for real C2 backend datagrams at {self.ingress_address[0]}:{self.ingress_address[1]}')

    def receive_ingress(self, body, address):
        try:
            if len(body) > 4096 or address[0] != '127.0.0.1':
                raise ValueError('Invalid local publisher')
            row = json.loads(body)
            if address == self.link.down.address:
                if not self.publisher_peer or not self.published or row.get('type') != 'priority_ack':
                    raise ValueError('Unexpected ACK')
                sequence, revision = row.get('sequence'), row.get('revision')
                if (row.get('source_session') != self.published.source_session
                    or type(sequence) is not int or sequence not in self.packet_receipts
                    or type(revision) is not int or revision != self.packet_receipts[sequence][1]):
                    raise ValueError('Mismatched ACK')
                self.ingress_transport.sendto(body, self.publisher_peer)
                if self.ack_sequence is None or sequence > self.ack_sequence:
                    self.ack_sequence, self.ack_revision = sequence, revision
                    self.last_ack = time.monotonic()
                    self.rtt_ms = (self.last_ack-self.packet_receipts[sequence][0])*1000
                return
            if row.get('type') != 'feed_priorities':
                raise ValueError('Unknown packet')
            publisher = row.get('publisher', {})
            if publisher.get('service') != 'urc-c2-web' or type(publisher.get('pid')) is not int or publisher['pid'] <= 0:
                raise ValueError('Expected Python C2 backend publisher metadata')
            message = FeedPriorities.from_dict(row.get('data'))
            message.validate(self.manager.stream_ids)
            if message.source_session in self.retired_publishers:
                raise ValueError('Retired publisher session')
            changed_session = self.published is None or message.source_session != self.published.source_session
            if not changed_session and (address != self.publisher_peer or message.sequence <= self.published.sequence):
                raise ValueError('Duplicate, old or unexpected publisher packet')
            if changed_session:
                if self.published:
                    if len(self.retired_publishers) >= 32:
                        raise ValueError('Too many publisher sessions; restart the adapter')
                    self.retired_publishers.add(self.published.source_session)
                self.link.epoch += 1
                self.link.up.clear()
                self.link.down.clear()
                self.packet_receipts.clear()
                self.ack_revision = self.ack_sequence = self.last_ack = None
                self.event(f'Actual C2 backend connected: PID {publisher["pid"]}, UDP {address[0]}:{address[1]}')
            self.publisher_peer, self.publisher_pid = address, publisher['pid']
            self.published, self.last_backend_packet = message, time.monotonic()
            self.packet_receipts[message.sequence] = (self.last_backend_packet, message.revision)
            self.packet_receipts = {seq: value for seq, value in self.packet_receipts.items() if seq > message.sequence-128}
            self.ingress_transport.sendto(body, self.link.up.address)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            self.invalid_packets += 1

    def publish_bandwidth(self):
        self.bandwidth_sequence += 1
        self.manager.receive_bandwidth(BandwidthInput(self.bandwidth_session, self.bandwidth_sequence,
            self.link.config.bandwidth_bps))

    def receive_rover(self, body, address):
        try:
            if address != self.link.up.address or len(body) > 4096:
                raise ValueError('Unexpected shaped sender')
            row = json.loads(body)
            if row.get('type') != 'feed_priorities' or self.published is None:
                raise ValueError('No actual publisher')
            message = FeedPriorities.from_dict(row.get('data'))
            if message.source_session != self.published.source_session:
                raise ValueError('Retired C2 backend session')
            previous = self.manager.priorities.revision if self.manager.priorities else None
            if self.manager.receive_priorities(message) and previous != message.revision:
                self.event(f'Status manager received actual C2 revision {message.revision}: {message.enabled_count} enabled')
            ack = {'type': 'priority_ack', 'source_session': message.source_session,
                'sequence': message.sequence, 'revision': message.revision}
            self.rover_transport.sendto(json.dumps(ack, separators=(',', ':')).encode(), self.link.down.address)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            self.invalid_packets += 1

    def configure_link(self, config):
        self.link.configure(config)
        self.publish_bandwidth()
        self.event(f'Link input changed to {config.bandwidth_bps/1e6:g} Mb/s, {config.latency_ms:g} ms one-way')

    async def run(self):
        while self.running:
            await asyncio.sleep(.5)
            self.publish_bandwidth()  # No synthetic priority updates here.

    def state(self):
        now = time.monotonic()
        message = self.published
        age = now-self.last_backend_packet if self.last_backend_packet is not None else None
        return {'c2': {'external': True, 'connected': age is not None and age < 1.5,
                'publisher_service': 'urc-c2-web', 'publisher_pid': self.publisher_pid,
                'publisher_address': list(self.publisher_peer) if self.publisher_peer else None,
                'ingress_address': list(self.ingress_address) if self.ingress_address else None,
                'backend_age_s': age, 'ui_url': 'http://127.0.0.1:8870/#cameras',
                'ordered_stream_ids': list(message.ordered_stream_ids) if message else [],
                'enabled_count': message.enabled_count if message else None,
                'revision': message.revision if message else None,
                'sequence': message.sequence if message else None,
                'session': message.source_session if message else None,
                'ack_revision': self.ack_revision, 'ack_sequence': self.ack_sequence,
                'ack_age_s': now-self.last_ack if self.last_ack is not None else None, 'rtt_ms': self.rtt_ms},
            'process': {'pid': os.getpid(), 'service': 'urc-video-pipeline-prototype', 'priority_input': 'external UDP only'},
            'link': self.link.state(), 'status_manager': self.manager.snapshot(),
            'events': list(self.events), 'invalid_packets': self.invalid_packets}

    async def close(self):
        self.running = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.link.close()
        for transport in (self.ingress_transport, self.rover_transport):
            if transport:
                transport.close()
