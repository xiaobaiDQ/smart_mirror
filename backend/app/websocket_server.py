"""
websocket_server.py
-------------------
WebSocket 连接管理 & 广播。

功能:
- 维护当前已连接客户端集合
- 提供 `broadcast(message)` 向所有客户端推送 JSON
- 支持多用户并发
- 处理前端主动消息（如手动文本指令、音乐控制点击）

执行逻辑:
- FastAPI 在 /ws 端点接受连接 → 注册到 ConnectionManager
- 任何模块 (ai_handler / command_executor) 均可调用 manager.broadcast(...)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .utils import get_logger

log = get_logger("ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)
        log.info("WS connected. total=%d", len(self.active))
        await self.send(ws, {"type": "hello", "msg": "smart-mirror backend ready"})

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active.discard(ws)
        log.info("WS disconnected. total=%d", len(self.active))

    async def send(self, ws: WebSocket, message: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            log.warning("send failed: %s", e)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """向所有客户端并发推送消息。"""
        if not self.active:
            return
        data = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        await asyncio.gather(
            *(self._safe_send(ws, data, dead) for ws in list(self.active)),
            return_exceptions=True,
        )
        if dead:
            async with self._lock:
                for ws in dead:
                    self.active.discard(ws)

    @staticmethod
    async def _safe_send(ws: WebSocket, data: str, dead: list[WebSocket]) -> None:
        try:
            await ws.send_text(data)
        except Exception:  # noqa: BLE001
            dead.append(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    """FastAPI route handler: /ws"""
    # 延迟导入，避免循环依赖
    from .ai_handler import handle_user_text
    from .command_executor import executor

    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(ws, {"type": "error", "msg": "invalid json"})
                continue

            mtype = msg.get("type")
            if mtype == "user_text":
                # 前端手动输入文本问答
                asyncio.create_task(handle_user_text(msg.get("text", "")))
            elif mtype == "music_control":
                asyncio.create_task(executor.music_control(msg.get("action", "")))
            elif mtype == "ping":
                await manager.send(ws, {"type": "pong"})
            else:
                log.debug("unknown message type: %s", mtype)
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception as e:  # noqa: BLE001
        log.exception("ws error: %s", e)
        await manager.disconnect(ws)
