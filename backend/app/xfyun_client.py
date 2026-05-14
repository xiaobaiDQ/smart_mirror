"""
xfyun_client.py
---------------
讯飞在线语音听写 WebSocket 客户端。

负责与讯飞 iFlytek 语音听写服务端建立 WebSocket 连接，
通过 HMAC-SHA256 签名鉴权，流式发送音频帧并接收识别结果。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime
from time import mktime
from typing import TYPE_CHECKING
from wsgiref.handlers import format_date_time

import websockets

from .config import settings
from .utils import get_logger

if TYPE_CHECKING:
    import numpy as np

log = get_logger("xfyun")


class XFYunClient:
    """讯飞在线语音听写 WebSocket 客户端"""

    HOST = "iat-api.xfyun.cn"
    PATH = "/v2/iat"
    URL = f"wss://{HOST}{PATH}"

    def __init__(
        self,
        app_id: str,
        api_key: str,
        api_secret: str,
        language: str = "zh_cn",
        domain: str = "iat",
    ):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.language = language
        self.domain = domain

    def _build_auth_url(self) -> str:
        """构造 HMAC-SHA256 签名鉴权 URL。

        签名原文格式:
            host: iat-api.xfyun.cn
            date: <RFC1123 格式时间>
            GET /v2/iat HTTP/1.1
        """
        # 生成 RFC1123 格式时间
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 构造签名原文
        signature_origin = (
            f"host: {self.HOST}\n"
            f"date: {date}\n"
            f"GET {self.PATH} HTTP/1.1"
        )

        # HMAC-SHA256 签名
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")

        # 构造 authorization
        authorization_origin = (
            f'api_key="{self.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode("utf-8")
        ).decode("utf-8")

        # 拼接最终 URL
        params = urllib.parse.urlencode({
            "authorization": authorization,
            "date": date,
            "host": self.HOST,
        })
        return f"{self.URL}?{params}"

    def _audio_to_pcm(self, audio: "np.ndarray") -> bytes:
        """float32 [-1,1] → PCM 16-bit signed integer bytes (little-endian)."""
        import numpy as np

        # Clip to [-1, 1] then scale to int16 range
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        return pcm.tobytes()

    def _split_frames(self, pcm: bytes, frame_size: int = 1280) -> list[bytes]:
        """将 PCM 数据按 frame_size 字节分帧。

        Args:
            pcm: PCM 音频字节数据
            frame_size: 每帧字节数，默认 1280 (40ms at 16kHz 16-bit mono)

        Returns:
            帧列表，最后一帧可能小于 frame_size
        """
        if not pcm:
            return []
        return [pcm[i:i + frame_size] for i in range(0, len(pcm), frame_size)]
    def _parse_response(self, message: str) -> tuple[str, bool]:
        """解析讯飞响应 JSON，提取并拼接文本。

        Args:
            message: 讯飞 WebSocket 返回的 JSON 字符串

        Returns:
            (text_segment, is_final) 元组
            - text_segment: 本次响应中的文本片段
            - is_final: 是否为最终结果 (data.status == 2)
        """
        try:
            resp = json.loads(message)
        except json.JSONDecodeError:
            log.error("讯飞响应 JSON 解析失败: %s", message[:200])
            return "", True

        code = resp.get("code", -1)
        if code != 0:
            log.error("讯飞返回错误 code=%d: %s", code, resp.get("message", ""))
            return "", True

        data = resp.get("data", {})
        status = data.get("status", 0)
        is_final = (status == 2)

        result = data.get("result", {})
        ws_list = result.get("ws", [])

        text = ""
        for ws in ws_list:
            cw_list = ws.get("cw", [])
            for cw in cw_list:
                text += cw.get("w", "")

        return text, is_final
    async def transcribe(self, audio: "np.ndarray") -> str:
        """将 float32 音频转写为文本。

        Args:
            audio: 16kHz mono float32 numpy array

        Returns:
            识别文本，失败返回空字符串
        """
        # 空凭证检查
        if not self.app_id or not self.api_key or not self.api_secret:
            log.warning("讯飞凭证未配置，跳过转写")
            return ""

        if len(audio) == 0:
            return ""

        try:
            return await asyncio.wait_for(self._do_transcribe(audio), timeout=10.0)
        except asyncio.TimeoutError:
            log.error("讯飞 ASR 超时 (>10s)")
            return ""
        except Exception as e:  # noqa: BLE001
            log.error("讯飞 ASR 异常: %s", e)
            return ""

    async def _do_transcribe(self, audio: "np.ndarray") -> str:
        """实际转写逻辑（被 transcribe 包裹超时控制）。"""
        import numpy as np
        pcm = self._audio_to_pcm(audio)
        frames = self._split_frames(pcm)
        if not frames:
            return ""

        duration_s = len(audio) / 16000
        peak = float(np.abs(audio).max())
        log.info("讯飞转写: %.1fs, %d帧, peak=%.4f", duration_s, len(frames), peak)

        url = self._build_auth_url()

        full_text = ""

        async with websockets.connect(url) as ws:
            # 发送音频帧
            for i, frame in enumerate(frames):
                # 确定帧状态
                if len(frames) == 1:
                    status = 2  # 唯一一帧
                elif i == 0:
                    status = 0  # 首帧
                elif i == len(frames) - 1:
                    status = 2  # 末帧
                else:
                    status = 1  # 中间帧

                audio_b64 = base64.b64encode(frame).decode("utf-8")

                if status == 0:
                    # 首帧：包含 common + business + data
                    payload = {
                        "common": {"app_id": self.app_id},
                        "business": {
                            "language": self.language,
                            "domain": self.domain,
                            "accent": "mandarin",
                            "vad_eos": 3000,
                        },
                        "data": {
                            "status": 0,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": audio_b64,
                        },
                    }
                else:
                    # 中间帧/末帧：仅 data
                    payload = {
                        "data": {
                            "status": status,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": audio_b64,
                        }
                    }

                await ws.send(json.dumps(payload))

                # 帧间间隔 40ms（末帧发完不等）
                if status != 2:
                    await asyncio.sleep(0.04)

            # 接收所有响应直到最终结果
            while True:
                try:
                    message = await ws.recv()
                except websockets.exceptions.ConnectionClosed:
                    break

                text_seg, is_final = self._parse_response(message)
                if text_seg:
                    full_text += text_seg
                if is_final:
                    break

        result = full_text.strip()
        log.info("讯飞结果: %r", result if result else "(空)")
        return result


# 模块级单例实例
xfyun_client = XFYunClient(
    app_id=settings.XFYUN_APPID,
    api_key=settings.XFYUN_API_KEY,
    api_secret=settings.XFYUN_API_SECRET,
    language=settings.XFYUN_LANGUAGE,
    domain=settings.XFYUN_DOMAIN,
)
