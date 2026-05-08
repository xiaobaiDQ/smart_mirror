"""
utils.py
--------
通用工具: 日志初始化、异步任务调度、时间格式化、JSON 安全解析。

所有其他模块可复用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Awaitable, Callable

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


log = get_logger("smart-mirror")


# ---------- 异步任务调度 ----------
_background_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro: Awaitable[Any], name: str | None = None) -> asyncio.Task:
    """发射并忘记：后台运行协程且保留引用避免被 GC。"""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def run_parallel(*coros: Awaitable[Any]) -> list[Any]:
    return await asyncio.gather(*coros, return_exceptions=True)


# ---------- 时间 ----------
def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


# ---------- JSON 安全解析 ----------
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def safe_json_loads(text: str) -> dict | None:
    """从可能包含 markdown 代码块 / 多余文字的字符串中抽取 JSON。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# ---------- 简单节流 ----------
def throttle(interval_s: float) -> Callable:
    """装饰器：限制异步函数最小调用间隔。"""

    def decorator(func: Callable[..., Awaitable[Any]]):
        last_called = 0.0
        lock = asyncio.Lock()

        async def wrapper(*args, **kwargs):
            nonlocal last_called
            async with lock:
                now = asyncio.get_event_loop().time()
                wait = interval_s - (now - last_called)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_called = asyncio.get_event_loop().time()
            return await func(*args, **kwargs)

        return wrapper

    return decorator
