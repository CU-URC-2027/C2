"""Real TCP synthetic AU load plus mock chassis; no physical device or decoder."""
import asyncio
import json

from c2_web.runtime import Runtime
from c2_web.video_receiver import VideoReceiver
from c2_web.video_wire import pack

KEY = b'\x00\x00\x01\x67\x64\x00\x28abc\x00\x00\x01\x68abc\x00\x00\x01\x65' + b'\xff'*24000


async def wait_for(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


async def test_five_tcp_feeds_and_slow_viewers_cannot_renew_motion_input():
    runtime, receiver = Runtime(), VideoReceiver()
    runtime.register('operator')
    await runtime.start()
    await receiver.start()
    viewers, tasks = [], []

    async def produce(camera):
        reader, writer = await asyncio.open_connection('127.0.0.1', receiver.port)
        try:
            sequence = 0
            while True:
                sequence += 1
                writer.write(pack(dict(stream_id=camera, session='a'*32,
                    sequence=sequence, pts_us=sequence*33333, width=640,
                    height=360, keyframe=True, codec='h264', format='annexb'), KEY))
                await writer.drain()
                assert json.loads(await reader.readline())['sequence'] == sequence
                await asyncio.sleep(1/30)
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        for camera in receiver.channels:
            # Leave one subscriber deliberately unread on every feed.
            viewers.append(receiver.subscribe(camera))
            tasks.append(asyncio.create_task(produce(camera)))
        await runtime.action('operator', 'connect', {'mode': 'mock'})
        await wait_for(runtime.direct_enable_ready)
        await runtime.action('operator', 'input', {'seq': 1})
        await runtime.action('operator', 'enable', {})
        for sequence in range(2, 22):
            await runtime.action('operator', 'input', {'seq': sequence, 'throttle': .5, 'deadman': True})
            await asyncio.sleep(.05)
        assert runtime.mock.enabled and runtime.mock.throttle > 0
        input_stamp = runtime.last_input
        for _ in range(12):
            await runtime.action('operator', 'heartbeat', {})
            for viewer in viewers:
                viewer.update_report({'type': 'render', 'rendered_frames': 1, 'render_fps': 30})
            await asyncio.sleep(.05)
        assert runtime.last_input == input_stamp
        assert not runtime.control.armed and not runtime.mock.enabled and runtime.mock.throttle == 0
        assert all(c['received_frames'] >= 20 for c in receiver.state()['cameras'])
        assert all(len(v.queue) <= 6 and v.bytes <= 4*1024*1024 and v.dropped > 0 for v in viewers)
        assert all(not task.done() for task in tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for viewer in viewers:
            receiver.unsubscribe(viewer)
        await receiver.stop()
        await runtime.close()
