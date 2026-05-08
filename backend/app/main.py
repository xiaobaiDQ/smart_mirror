"""
main.py
-------
FastAPI 应用入口。
- 注册 WebSocket /ws
- 提供 REST: /api/weather, /api/asr/text, /api/music/state
- 启动时拉起后台任务：麦克风采集 (可选) + 周期刷新天气

运行:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .asr_handler import asr_handler
from .command_executor import executor
from .config import settings
from .utils import fire_and_forget, get_logger
from .watchdog import set_mic_task, watchdog_loop
from .websocket_server import manager, websocket_endpoint

log = get_logger("main")


async def _weather_loop() -> None:
    while True:
        try:
            await executor.weather()
        except Exception as e:  # noqa: BLE001
            log.error("weather loop: %s", e)
        await asyncio.sleep(10 * 60)  # 10 分钟


async def _time_loop() -> None:
    while True:
        await executor.time_now()
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("smart-mirror backend starting on %s:%d", settings.HOST, settings.PORT)
    fire_and_forget(_weather_loop(), "weather-loop")
    fire_and_forget(_time_loop(), "time-loop")
    if settings.ASR_AUTO_START:
        log.info("启动本地 Whisper ASR mic_loop")
        mic_task = fire_and_forget(asr_handler.mic_loop(), "mic-loop")
        set_mic_task(mic_task)
    else:
        log.info("ASR_AUTO_START=False，跳过麦克风采集")

    # 启动守护进程：监控 NeteaseCloudMusicApi + mic_loop
    fire_and_forget(watchdog_loop(check_interval=30), "watchdog")

    yield
    log.info("smart-mirror backend shutdown")


app = FastAPI(title="Smart Mirror", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "awake": asr_handler.is_awake}


@app.get("/api/weather")
async def api_weather() -> dict:
    return await executor.weather()


@app.get("/api/music/state")
async def api_music_state() -> dict:
    return executor.state["music"]


@app.post("/api/asr/text")
async def api_asr_text(body: dict) -> dict:
    """外部设备把识别到的文本 POST 进来；等价于麦克风链路。"""
    await asr_handler.feed_text(body.get("text", ""))
    return {"ok": True}


@app.websocket("/ws")
async def ws_route(ws: WebSocket) -> None:
    await websocket_endpoint(ws)
