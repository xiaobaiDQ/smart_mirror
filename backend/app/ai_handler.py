"""
ai_handler.py
-------------
调用智普大模型 (GLM) 解析用户文本，返回 JSON 指令或自然语言回答。

执行逻辑:
1. 前端/ASR -> handle_user_text(text)
2. 立即向 WebSocket 广播 {type: "ai_thinking"}，前端弹窗「AI 正在思考…」
3. 异步调用智普 GLM；解析响应 JSON {action, payload, reply}
4. 广播 {type: "ai_reply", reply, action}
5. 若 action 非 chat，转交 command_executor 执行
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import time
from typing import Any
import httpx

from .config import settings
from .utils import get_logger, safe_json_loads

log = get_logger("ai")


_CORRECTION_PROMPT = (
    "你是语音识别纠错器。输入是 Whisper 对中文语音的识别结果，"
    "经常包含严重的同音字/近音字/繁体字/漏字错误。\n"
    "请根据发音相似性和上下文，输出你认为用户真正想说的简体中文句子。\n"
    "规则：只输出纠正后的一句话，不要解释，不要加标点以外的内容。\n"
    "示例：\n"
    "  输入: 请问我现在再劳你 → 输出: 请问我现在在哪里\n"
    "  输入: 盡小盡今天天氣怎麼樣 → 输出: 小镜小镜今天天气怎么样\n"
    "  输入: 今天程度的天气 → 输出: 今天成都的天气\n"
    "  输入: 小镜小镜 → 输出: 小镜小镜\n"
)


# 共享 httpx 客户端，避免每次请求都新建连接
_http_client: httpx.AsyncClient | None = None
_last_user_text_norm = ""
_last_user_text_ts = 0.0


def _build_context_message() -> str | None:
    from .command_executor import executor

    now = datetime.now()
    lines: list[str] = [
        f"当前时间: {now.strftime('%Y-%m-%d %H:%M (%A)')}",
    ]
    w = getattr(executor, "last_weather", None) or {}
    if w.get("city"):
        parts = [f"用户所在城市: {w.get('city')}"]
        if w.get("weather"):
            parts.append(f"天气: {w['weather']}")
        if w.get("temperature"):
            parts.append(f"{w['temperature']}°C")
        if w.get("humidity"):
            parts.append(f"湿度 {w['humidity']}%")
        if w.get("winddirection") or w.get("windpower"):
            parts.append(f"{w.get('winddirection','')}风 {w.get('windpower','')}")
        lines.append("；".join(parts))
    if len(lines) == 1:
        return None
    return ("[实时上下文]\n" + "\n".join(lines) +
            "\n用户问当地天气时用 weather action（city留空），reply 里用上面的天气数据自然回答。"
            "\n用户问其他城市天气时用 weather action 并填 city，系统会自动查询。"
            "\n注意：weather action 支持查询任何中国城市，绝对不要说「无法查询」。"
            "\n用户问时间/星期时用 time action，reply 里直接告诉用户具体时间。")


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client

# 纠错锁：同一时间只跑一个纠错请求
_correct_lock = asyncio.Lock()


async def _deepseek_request(messages: list[dict], temperature: float = 0.3,
                             response_format: dict | None = None,
                             timeout: float = 30.0) -> str:
    """通用 DeepSeek 请求。"""
    if not settings.DEEPSEEK_API_KEY:
        return ""
    url = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body: dict = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 512,
        "stream": False,
    }
    if response_format:
        body["response_format"] = response_format
    client = _get_client()
    r = await client.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


async def correct_asr_text(raw: str) -> str:
    """用 DeepSeek 纠正 Whisper 识别结果。如果上一个纠错还在跑，直接跳过用原文。"""
    if not settings.DEEPSEEK_API_KEY or not raw.strip():
        return raw
    # 乱码检测
    alnum_ratio = sum(1 for c in raw if c.isdigit() or c in '×+=-*/,.;:') / max(len(raw), 1)
    if alnum_ratio > 0.4:
        log.info("ASR 纠错跳过（疑似乱码 %.0f%%）: %r", alnum_ratio * 100, raw)
        return raw
    # 如果锁被占用（上一个纠错还没完），直接用原文，不排队
    if _correct_lock.locked():
        log.info("ASR 纠错跳过（上一个还在进行中）: %r", raw)
        return raw
    async with _correct_lock:
        try:
            result = await asyncio.wait_for(
                _deepseek_request(
                    [{"role": "system", "content": _CORRECTION_PROMPT},
                     {"role": "user", "content": raw}],
                    temperature=0.1,
                    timeout=6.0,
                ),
                timeout=8.0,
            )
            corrected = result.strip().strip('"').strip("'")
            if corrected:
                log.info("ASR 纠错: %r → %r", raw, corrected)
                return corrected
        except asyncio.TimeoutError:
            log.warning("ASR 纠错超时(8s)，使用原文: %r", raw)
        except Exception as e:  # noqa: BLE001
            log.warning("ASR 纠错失败: %s", e)
    return raw


async def _call_deepseek(text: str) -> str:
    """调用 DeepSeek 进行问答。"""
    if not settings.DEEPSEEK_API_KEY:
        return f'{{"action":"chat","payload":{{}},"reply":"(mock) 我收到了：{text}"}}'

    messages = [{"role": "system", "content": settings.AI_SYSTEM_PROMPT}]
    ctx = _build_context_message()
    if ctx:
        messages.append({"role": "system", "content": ctx})
    messages.append({"role": "user", "content": text})

    return await _deepseek_request(
        messages, temperature=0.6,
        response_format={"type": "json_object"},
    )


async def handle_user_text(text: str) -> None:
    """主入口：处理一段用户文本问答。"""
    global _last_user_text_norm, _last_user_text_ts
    from .command_executor import executor
    from .websocket_server import manager

    text = (text or "").strip()
    if not text:
        return
    norm = "".join(text.split()).lower()
    now = time.time()
    if norm and norm == _last_user_text_norm and now - _last_user_text_ts < 10.0:
        log.info("忽略重复 AI 输入: %s", text)
        return
    _last_user_text_norm = norm
    _last_user_text_ts = now

    log.info("AI input: %s", text)
    if (ctx := _build_context_message()):
        log.debug("AI context: %s", ctx.replace("\n", " | "))
    await manager.broadcast({"type": "ai_thinking", "question": text})

    try:
        raw = await _call_deepseek(text)
        log.info("AI raw: %s", raw)
        data = safe_json_loads(raw) or {"action": "chat", "reply": raw, "payload": {}}
    except Exception as e:  # noqa: BLE001
        err_name = type(e).__name__
        log.exception("AI 调用失败: %s: %s", err_name, e)
        data = {"action": "chat", "reply": f"抱歉，AI 暂时响应不了，请稍后再试。", "payload": {}}

    action = (data.get("action") or "chat").lower()
    reply = data.get("reply") or ""
    payload = data.get("payload") or {}
    corrected = data.get("corrected") or text  # AI 纠正后的用户原话
    log.info("AI parsed: action=%s corrected=%r reply=%r", action, corrected, reply)

    # weather action：不发 ai_reply，保持 thinking 状态，等真实数据再发
    if action != "weather":
        await manager.broadcast(
            {"type": "ai_reply", "question": corrected, "reply": reply, "action": action}
        )
        log.info("AI ai_reply broadcasted")
        # TTS 朗读回复
        if reply and action != "dismiss":
            asyncio.create_task(executor.tts(reply))

    from .asr_handler import asr_handler

    # dismiss：用户说了关闭/再见 → 退出唤醒态，前端关弹窗
    if action == "dismiss":
        asr_handler.is_awake = False
        if asr_handler._awake_timeout:
            asr_handler._awake_timeout.cancel()
        log.info("DISMISS: 唤醒态已关闭")
        await manager.broadcast({"type": "dismiss"})
        return

    # 回答完毕续期唤醒态，方便用户连续追问
    await asr_handler.set_awake()

    # weather：统一走 _weather_then_reply，用真实数据回复
    if action == "weather":
        asyncio.create_task(_weather_then_reply(
            executor, manager, corrected, payload))
    elif action != "chat":
        asyncio.create_task(executor.dispatch(action, payload, reply))


async def _weather_then_reply(executor, manager, question, payload):
    """查询天气（本地或其他城市），用真实数据更新弹窗。"""
    city = (payload.get("city") or "").strip()
    try:
        data = await executor.weather(payload)
        c = data.get("city") or city or "当地"
        w = data.get("weather") or "-"
        t = data.get("temperature") or "-"
        h = data.get("humidity") or ""
        wd = data.get("winddirection") or ""
        wp = data.get("windpower") or ""
        parts = [f"{c}现在{w}，{t}°C"]
        if h:
            parts.append(f"湿度{h}%")
        if wd:
            parts.append(f"{wd}风{wp}")
        real_reply = "，".join(parts) + "。"
    except Exception as e:  # noqa: BLE001
        log.error("查询 %s 天气失败: %s", city or '本地', e)
        real_reply = f"抱歉，{city or '当地'}的天气暂时查不到。"

    # 用真实数据更新弹窗
    await manager.broadcast(
        {"type": "ai_reply", "question": question, "reply": real_reply, "action": "weather"}
    )
    # TTS 朗读天气
    asyncio.create_task(executor.tts(real_reply))
