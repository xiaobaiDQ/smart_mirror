"""
watchdog.py
-----------
后台守护任务：定期检查关键服务健康状态，异常时自动恢复。

监控项:
1. NeteaseCloudMusicApi (Node.js :3000) — 挂了自动重启
2. mic_loop 协程 — 如果意外退出则重新拉起
3. 前端 dev server (可选) — 仅日志提醒
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import httpx

from .config import settings
from .utils import fire_and_forget, get_logger

log = get_logger("watchdog")

# NeteaseCloudMusicApi 项目目录（相对于 backend 的上级目录）
_NETEASE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "NeteaseCloudMusicApi")
)
_node_proc: subprocess.Popen | None = None


# ------------------------------------------------------------------
# NeteaseCloudMusicApi 管理
# ------------------------------------------------------------------
async def _check_netease() -> bool:
    """检查网易云 API 是否在线，返回 True=健康。"""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.NETEASE_API_BASE}/search",
                            params={"keywords": "test", "limit": 1, "type": 1})
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _start_netease() -> subprocess.Popen | None:
    """启动 NeteaseCloudMusicApi Node 进程。"""
    global _node_proc
    if not os.path.isdir(_NETEASE_DIR):
        log.error("NeteaseCloudMusicApi 目录不存在: %s", _NETEASE_DIR)
        return None
    # 找 node 可执行文件
    node = "node"
    try:
        _node_proc = subprocess.Popen(
            [node, "app.js"],
            cwd=_NETEASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        log.info("✅ 已启动 NeteaseCloudMusicApi (PID=%d)", _node_proc.pid)
        return _node_proc
    except Exception as e:  # noqa: BLE001
        log.error("启动 NeteaseCloudMusicApi 失败: %s", e)
        return None


def _kill_netease():
    """终止已有的 Node 进程。"""
    global _node_proc
    if _node_proc and _node_proc.poll() is None:
        try:
            _node_proc.terminate()
            _node_proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                _node_proc.kill()
            except Exception:  # noqa: BLE001
                pass
    _node_proc = None


# ------------------------------------------------------------------
# mic_loop 监控
# ------------------------------------------------------------------
_mic_task: asyncio.Task | None = None


def set_mic_task(task: asyncio.Task) -> None:
    global _mic_task
    _mic_task = task


async def _ensure_mic_loop():
    """检查 mic_loop 是否还活着，死了就重启。"""
    from .asr_handler import asr_handler

    if _mic_task is None:
        return
    if _mic_task.done():
        exc = _mic_task.exception() if not _mic_task.cancelled() else None
        log.warning("mic_loop 已退出 (exception=%s)，正在重启…", exc)
        new_task = fire_and_forget(asr_handler.mic_loop(), "mic-loop")
        set_mic_task(new_task)


# ------------------------------------------------------------------
# 主守护循环
# ------------------------------------------------------------------
async def watchdog_loop(check_interval: float = 30.0) -> None:
    """每隔 check_interval 秒检查一次所有服务。"""
    log.info("🛡️ 守护进程启动，检查间隔 %.0fs", check_interval)

    # 首次启动：确保 NeteaseCloudMusicApi 在线
    await asyncio.sleep(5)  # 等后端完全启动
    if not await _check_netease():
        log.warning("NeteaseCloudMusicApi 未在线，尝试自动启动…")
        _start_netease()
        await asyncio.sleep(8)  # 等 Node 启动

    _consecutive_netease_fail = 0

    while True:
        try:
            await asyncio.sleep(check_interval)

            # --- 检查网易云 API ---
            if await _check_netease():
                if _consecutive_netease_fail > 0:
                    log.info("✅ NeteaseCloudMusicApi 恢复正常")
                _consecutive_netease_fail = 0
            else:
                _consecutive_netease_fail += 1
                log.warning(
                    "⚠️ NeteaseCloudMusicApi 不可用 (连续%d次)",
                    _consecutive_netease_fail,
                )
                if _consecutive_netease_fail >= 2:
                    log.info("正在重启 NeteaseCloudMusicApi…")
                    _kill_netease()
                    await asyncio.sleep(1)
                    _start_netease()
                    await asyncio.sleep(8)
                    if await _check_netease():
                        log.info("✅ NeteaseCloudMusicApi 重启成功")
                        _consecutive_netease_fail = 0
                    else:
                        log.error("❌ NeteaseCloudMusicApi 重启后仍不可用")

            # --- 检查 mic_loop ---
            await _ensure_mic_loop()

        except asyncio.CancelledError:
            log.info("守护进程收到取消信号，退出")
            break
        except Exception as e:  # noqa: BLE001
            log.error("守护进程异常: %s", e)
            await asyncio.sleep(10)
