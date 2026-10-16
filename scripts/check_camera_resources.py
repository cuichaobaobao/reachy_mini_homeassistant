"""Cloud-only resource regression checks; no forced garbage collection."""
import asyncio
import gc
import faulthandler
import io
import json
import threading
import time
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import av
from aiortc import VideoStreamTrack, AudioStreamTrack, RTCSessionDescription
from check_av19_media import media

def usage():
    fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    return int(fields["VmRSS"].split()[0]) / 1024, int(fields["Threads"])

def frame(w=640, h=480):
    f = av.VideoFrame(w, h, "yuv420p")
    for p in f.planes:
        p.update(bytes(p.buffer_size))
    return f

def check_jpeg(data, size):
    with av.open(io.BytesIO(data)) as source:
        result = next(source.decode(video=0))
        assert (result.width, result.height) == size

def encoder_stress():
    # Disable cyclic GC only in this standalone test process. Passing requires
    # prompt native-resource release, rather than waiting for periodic GC.
    gc.disable()
    encoder = media._JpegEncoder()
    f = frame()
    for _ in range(30):
        encoder.encode(f)
    baseline = usage()
    for i in range(3000):
        data = encoder.encode(f)
        if i % 500 == 0:
            print("JPEG", i, usage(), flush=True)
    end = usage()
    assert end[0] - baseline[0] < 48, (baseline, end)
    assert end[1] <= baseline[1] + 2, (baseline, end)
    check_jpeg(data, (640, 480))
    for i in range(100):
        size = (320, 240) if i % 2 else (640, 480)
        data = encoder.encode(frame(*size))
    check_jpeg(data, size)
    encoder.close()
    # Also guard the public one-shot helper against the original 30-frame leak.
    before = usage()
    for _ in range(300):
        media._encode_jpeg(f)
    after = usage()
    assert after[0] - before[0] < 48, (before, after)
    assert after[1] <= before[1] + 2, (before, after)
    gc.enable()
    print("PASS 3000 JPEG frames, resize, 300 one-shot calls without cyclic GC", usage(), flush=True)

async def concurrency():
    client = media.ReachyMiniStreamClient("unused", session=None)
    client._frame = frame()
    client._frame_event.set()
    entered, finish = threading.Event(), threading.Event()
    calls = 0
    original = client._jpeg_encoder.encode
    def blocked(f):
        nonlocal calls
        calls += 1
        entered.set()
        assert finish.wait(5)
        return original(f)
    client._jpeg_encoder.encode = blocked
    requests = [asyncio.create_task(client.async_get_image()) for _ in range(20)]
    while not entered.is_set():
        await asyncio.sleep(.001)
    requests[0].cancel()
    await asyncio.sleep(.02)
    assert calls == 1
    shutdown = asyncio.create_task(client.async_shutdown())
    await asyncio.sleep(.02)
    assert not shutdown.done(), "shutdown must await in-flight native encoding"
    finish.set()
    results = await asyncio.gather(*requests, return_exceptions=True)
    await shutdown
    assert isinstance(results[0], asyncio.CancelledError)
    assert all(isinstance(x, bytes) for x in results[1:])
    assert len({id(x) for x in results[1:]}) == 1
    assert client._jpeg_encoder._codec is None
    assert client._jpeg_cache is None and client._jpeg_task is None
    print("PASS 20 simultaneous requests, cancellation and shutdown", flush=True)

async def cancelled_cleanup():
    started, finish = asyncio.Event(), asyncio.Event()
    class PC:
        async def close(self):
            started.set()
            await finish.wait()
    class Session:
        def ws_connect(self, *args, **kwargs):
            raise OSError("expected test disconnect")
    client = media.ReachyMiniStreamClient("unused", session=Session(), pc_factory=PC)
    await client.acquire()
    await asyncio.wait_for(started.wait(), 2)
    shutdown = asyncio.create_task(client.async_shutdown())
    await asyncio.sleep(.02)
    assert not shutdown.done()
    finish.set()
    await asyncio.wait_for(shutdown, 2)
    print("PASS stop during natural session cleanup", flush=True)

async def streaming():
    peers = []
    close_tasks = []
    tracks = []
    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        pc = media._default_pc_factory()
        peers.append(pc)
        video, audio = VideoStreamTrack(), AudioStreamTrack()
        tracks.extend((video, audio))
        pc.addTrack(video)
        pc.addTrack(audio)
        try:
            await ws.send_json({"type": "welcome"})
            async for raw in ws:
                msg = json.loads(raw.data)
                if msg["type"] == "list":
                    await ws.send_json({"type": "list", "producers": [{"id": "p", "meta": {"name": "reachymini"}}]})
                elif msg["type"] == "startSession":
                    await ws.send_json({"type": "sessionStarted", "sessionId": "s"})
                    await pc.setLocalDescription(await pc.createOffer())
                    await ws.send_json({"type": "peer", "sdp": {"type": "offer", "sdp": pc.localDescription.sdp}})
                elif msg["type"] == "peer" and "sdp" in msg:
                    await pc.setRemoteDescription(RTCSessionDescription(**msg["sdp"]))
                elif msg["type"] == "endSession":
                    break
        finally:
            close_task = asyncio.create_task(pc.close())
            close_tasks.append(close_task)
            await asyncio.shield(close_task)
            video.stop()
            audio.stop()
            await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    server = TestServer(app)
    await server.start_server()
    receiver_pcs = []
    def factory():
        pc = media._default_pc_factory()
        receiver_pcs.append(pc)
        return pc
    try:
        async with aiohttp.ClientSession() as session:
            client = media.ReachyMiniStreamClient("127.0.0.1", port=server.port, session=session, pc_factory=factory, idle_timeout=.1)
            samples = []
            for cycle in range(5):
                await client.acquire()
                await client.acquire()
                await client.acquire()
                duration = 120 if cycle == 0 else 5
                deadline = time.monotonic() + duration
                count = 0
                while time.monotonic() < deadline:
                    images = await asyncio.gather(*(client.async_get_image() for _ in range(3)))
                    assert all(x.startswith(b"\xff\xd8") for x in images)
                    pc = receiver_pcs[-1]
                    audio = [r.track for r in pc.getReceivers() if r.track and r.track.kind == "audio"]
                    assert len(audio) == 1
                    assert audio[0]._queue.qsize() < 10
                    count += 1
                    if count % 100 == 0:
                        samples.append(usage())
                        print("LIVE", cycle, count, samples[-1], flush=True)
                    await asyncio.sleep(.1)
                await client.release()
                await client.release()
                assert receiver_pcs[-1].connectionState != "closed"
                await client.release()
                for _ in range(500):
                    if receiver_pcs[-1].connectionState == "closed" and client._jpeg_encoder._codec is None:
                        break
                    await asyncio.sleep(.01)
                else:
                    raise AssertionError("idle cleanup did not finish")
                assert not client._audio_tasks
                assert client._video_task is None
                assert client._jpeg_task is None
                assert client._frame is None
                assert not any(t.name in ("audio-decoder", "video-decoder") for t in threading.enumerate())
                # Await the test producer too; its native encoders must not
                # contaminate the next receiver lifecycle measurement.
                for _ in range(500):
                    if len(close_tasks) > cycle and close_tasks[cycle].done():
                        break
                    await asyncio.sleep(.01)
                else:
                    for task in asyncio.all_tasks():
                        task.print_stack()
                    raise AssertionError("test producer cleanup stalled")
                await close_tasks[cycle]
                print("CLOSED", cycle, usage(), flush=True)
            assert len(receiver_pcs) == 5
            # Ignore startup allocator warmup; allow bounded native allocator caches.
            assert max(x[0] for x in samples[2:]) - samples[2][0] < 96, samples
            assert max(x[1] for x in samples[2:]) - min(x[1] for x in samples[2:]) <= 4, samples
            await client.async_shutdown()
    finally:
        for t in tracks:
            t.stop()
        await asyncio.wait_for(asyncio.gather(*(p.close() for p in peers + receiver_pcs)), 10)
        await server.close()
    print("PASS real WebRTC audio/video, 3 viewers, 120-second view, 5 open/close cycles", flush=True)

async def main():
    encoder_stress()
    await concurrency()
    await cancelled_cleanup()
    await streaming()

if __name__ == "__main__":
    faulthandler.dump_traceback_later(240, exit=True)
    try:
        asyncio.run(main())
    finally:
        faulthandler.cancel_dump_traceback_later()
