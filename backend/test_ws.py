import asyncio
import websockets

async def test():
    try:
        async with websockets.connect("ws://localhost:8002/ws") as ws:
            msg = await ws.recv()
            print("Connected! Got:", msg)
    except Exception as e:
        print("Failed:", e)

asyncio.run(test())
