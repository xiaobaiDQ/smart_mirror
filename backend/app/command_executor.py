"""
command_executor.py
-------------------
根据 AI 指令执行实际操作：
- QQ 音乐 API 播放 / 暂停 / 切歌
- TTS 回答播报 (pyttsx3 本地)
- 高德天气 / 时间查询
- 其它扩展技能

设计要点:
- 所有方法异步，均通过 WebSocket 广播状态给前端
- 音乐状态保存在内存 self.state，可供前端拉取或 AI 二次决策
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import time
from typing import Any

import httpx

from .config import settings
from .utils import get_logger

log = get_logger("cmd")


class CommandExecutor:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "music": {
                "playing": False,
                "title": "",
                "artist": "",
                "url": "",
                "cover": "",
            }
        }
        # 最近一次高德天气数据 (ai_handler 会读取以给大模型提供上下文)
        self.last_weather: dict[str, Any] = {}
        # 动态城市 adcode (优先级: payload > 此变量 > settings.AMAP_CITY_ADCODE)
        self._adcode: str = ""
        self._adcode_city: str = ""
        self._last_action_key: str = ""
        self._last_action_ts: float = 0.0

    async def _resolve_adcode(self) -> str:
        """通过高德 IP 定位 → 逆地理编码，拿区县级 adcode + 详细地址。"""
        # 如果配置了固定 adcode，始终使用（优先级最高，避免 IP 定位不准）
        if settings.AMAP_CITY_ADCODE:
            return settings.AMAP_CITY_ADCODE
        if self._adcode:
            return self._adcode
        if not settings.AMAP_API_KEY:
            return "110000"
        try:
            async with httpx.AsyncClient(timeout=6.0) as c:
                # 第一步：IP 定位拿经纬度范围
                r = await c.get(settings.AMAP_IP_URL,
                                params={"key": settings.AMAP_API_KEY})
                j = r.json()
                rect = j.get("rectangle") or ""
                city = j.get("city") or ""
                ad = j.get("adcode") or ""

                # 第二步：如果有 rectangle，用逆地理编码拿精确区县
                if rect and isinstance(rect, str) and ";" in rect:
                    # rectangle 格式: "lng1,lat1;lng2,lat2" 取中心点
                    p1, p2 = rect.split(";")[:2]
                    lng1, lat1 = p1.split(",")
                    lng2, lat2 = p2.split(",")
                    center_lng = (float(lng1) + float(lng2)) / 2
                    center_lat = (float(lat1) + float(lat2)) / 2
                    location = f"{center_lng:.6f},{center_lat:.6f}"
                    rg = await c.get(
                        "https://restapi.amap.com/v3/geocode/regeo",
                        params={"key": settings.AMAP_API_KEY,
                                "location": location,
                                "extensions": "base"})
                    gj = rg.json()
                    comp = (gj.get("regeocode") or {}).get("addressComponent") or {}
                    district = comp.get("district") or ""
                    township = comp.get("township") or ""
                    district_ad = comp.get("adcode") or ad
                    province = comp.get("province") or ""
                    city_name = comp.get("city") or city
                    # 组装详细地址
                    if isinstance(city_name, list):
                        city_name = city_name[0] if city_name else ""
                    detail = f"{province}{city_name}{district}{township}".strip()
                    if district_ad and isinstance(district_ad, str):
                        self._adcode = district_ad
                        self._adcode_city = detail or city
                        log.info("IP 精确定位: %s (adcode=%s)", self._adcode_city, district_ad)
                        return district_ad

                # 没有 rectangle 或逆地理失败，用 IP 返回的市级 adcode
                if ad and isinstance(ad, str):
                    self._adcode = ad
                    self._adcode_city = city if isinstance(city, str) else ""
                    log.info("IP 定位(市级): %s (adcode=%s)", self._adcode_city, ad)
                    return ad
        except Exception as e:  # noqa: BLE001
            log.warning("IP 定位失败: %s", e)
        return settings.AMAP_CITY_ADCODE or "110000"

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------
    async def dispatch(self, action: str, payload: dict, reply: str = "") -> None:
        key = f"{action}:{json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)}"
        now = time.time()
        if key == self._last_action_key and now - self._last_action_ts < 10.0:
            log.info("忽略重复指令: %s", key)
            return
        self._last_action_key = key
        self._last_action_ts = now

        handler = {
            "play_music": self.play_music,
            "pause": lambda p: self.music_control("pause"),
            "next": lambda p: self.music_control("next"),
            "weather": self.weather,
            "time": self.time_now,
        }.get(action)

        if handler is None:
            log.warning("未知 action: %s", action)
            return

        try:
            await handler(payload)
        except Exception as e:  # noqa: BLE001
            log.exception("执行 %s 失败: %s", action, e)

    # ------------------------------------------------------------------
    # 音乐
    # ------------------------------------------------------------------
    async def _get_play_url(self, client, song_id: int) -> str:
        """尝试获取歌曲播放链接，返回 URL 或空字符串。"""
        # 优先 /song/url
        try:
            resp = await client.get(
                f"{settings.NETEASE_API_BASE}/song/url",
                params={"id": song_id, "br": 320000},
            )
            if resp.status_code == 200:
                url = (resp.json().get("data") or [{}])[0].get("url") or ""
                if url:
                    return url
        except Exception:  # noqa: BLE001
            pass
        # fallback /song/url/v1
        try:
            resp2 = await client.get(
                f"{settings.NETEASE_API_BASE}/song/url/v1",
                params={"id": song_id, "level": "standard"},
            )
            if resp2.status_code == 200:
                url = (resp2.json().get("data") or [{}])[0].get("url") or ""
                if url:
                    return url
        except Exception:  # noqa: BLE001
            pass
        return ""

    async def play_music(self, payload: dict) -> None:
        """通过网易云音乐 API 搜索并获取播放 URL。
        如果首选歌曲需要 VIP（无链接），自动从搜索结果中找下一首可播放的。
        """
        from .websocket_server import manager

        keyword = payload.get("keyword") or payload.get("song") or ""
        if not keyword:
            return
        now = time.time()
        keyword_key = "".join(str(keyword).split()).lower()
        last_key = getattr(self, "_last_music_keyword", "")
        last_ts = getattr(self, "_last_music_ts", 0.0)
        if keyword_key and keyword_key == last_key and now - last_ts < 20.0:
            log.info("忽略重复播放音乐: %s", keyword)
            return
        self._last_music_keyword = keyword_key
        self._last_music_ts = now
        log.info("搜索音乐: %s", keyword)

        play_url = ""
        title = keyword
        artist = ""
        cover = ""
        song_id = None

        # 最多重试 2 次（等待网易云 API 恢复）
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # 搜索歌曲（取多条以备 VIP 跳过）
                    search = await client.get(
                        f"{settings.NETEASE_API_BASE}/search",
                        params={"keywords": keyword, "limit": 20, "type": 1},
                    )
                    if search.status_code >= 500:
                        raise httpx.HTTPStatusError("API 不可用", request=search.request, response=search)
                    sdata = search.json()
                    songs = sdata.get("result", {}).get("songs", [])
                    if not songs:
                        log.warning("未搜索到歌曲: %s", keyword)
                        return

                    # 逐首尝试获取可用播放链接
                    for idx, song in enumerate(songs):
                        sid = song.get("id")
                        url = await self._get_play_url(client, sid)
                        if url:
                            song_id = sid
                            title = song.get("name") or keyword
                            artists = song.get("artists") or song.get("ar") or []
                            artist = artists[0].get("name", "") if artists else ""
                            album = song.get("album") or song.get("al") or {}
                            cover = album.get("picUrl") or ""
                            play_url = url
                            if idx > 0:
                                log.info("第1首需VIP，跳到第%d首: %s - %s", idx + 1, title, artist)
                            break
                        else:
                            sname = song.get("name", "?")
                            log.debug("第%d首 [%s] 无可用链接，跳过", idx + 1, sname)

                    # 搜索成功就跳出重试循环
                    break

            except Exception as e:  # noqa: BLE001
                if attempt < 2:
                    log.warning("网易云 API 请求失败 (第%d次，3s后重试): %s", attempt + 1, e)
                    await asyncio.sleep(3)
                else:
                    log.error("网易云音乐 API 失败（已重试3次）: %s", e)
                    return

        if not play_url:
            # 所有结果都无链接
            if songs:
                song = songs[0]
                song_id = song.get("id")
                title = song.get("name") or keyword
                artists = song.get("artists") or song.get("ar") or []
                artist = artists[0].get("name", "") if artists else ""
                album = song.get("album") or song.get("al") or {}
                cover = album.get("picUrl") or ""
                log.warning("所有搜索结果均无可用播放链接(VIP): %s", title)

        self.state["music"] = {
            "playing": bool(play_url),
            "title": title,
            "artist": artist or "",
            "url": play_url,
            "cover": cover,
            "id": song_id,
        }
        from .asr_handler import asr_handler
        asr_handler._music_playing = bool(play_url)
        asr_handler.is_awake = False
        if asr_handler._awake_timeout:
            asr_handler._awake_timeout.cancel()
        asr_handler.mute_for(8.0)
        await manager.broadcast({"type": "music_state", **self.state["music"]})

    async def music_control(self, action: str) -> None:
        from .websocket_server import manager

        action = (action or "").lower()
        if action == "pause":
            self.state["music"]["playing"] = False
        elif action == "play":
            self.state["music"]["playing"] = True
        elif action == "next":
            # 交给前端处理 "下一首" 行为（本示例不维护播放列表）
            pass
        from .asr_handler import asr_handler
        asr_handler._music_playing = self.state["music"].get("playing", False)
        await manager.broadcast(
            {"type": "music_control", "action": action, **self.state["music"]}
        )

    # ------------------------------------------------------------------
    # 天气 / 时间
    # ------------------------------------------------------------------
    async def _city_to_adcode(self, city_name: str) -> str | None:
        """通过高德地理编码 API 将城市名转为 adcode。"""
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={"key": settings.AMAP_API_KEY, "address": city_name},
                )
                geocodes = r.json().get("geocodes") or []
                if geocodes:
                    ad = geocodes[0].get("adcode") or ""
                    if ad:
                        log.info("城市 '%s' → adcode=%s", city_name, ad)
                        return ad
        except Exception as e:  # noqa: BLE001
            log.error("地理编码失败: %s", e)
        return None

    async def _fetch_weather(self, adcode: str) -> dict:
        """通过 adcode 查询天气，返回数据字典。"""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    settings.AMAP_WEATHER_URL,
                    params={
                        "key": settings.AMAP_API_KEY,
                        "city": adcode,
                        "extensions": "base",
                    },
                )
                j = r.json()
                live = (j.get("lives") or [{}])[0]
                data = {
                    "city": live.get("city", ""),
                    "weather": live.get("weather", ""),
                    "temperature": live.get("temperature", ""),
                    "winddirection": live.get("winddirection", ""),
                    "windpower": live.get("windpower", ""),
                    "humidity": live.get("humidity", ""),
                    "reporttime": live.get("reporttime", ""),
                }
                log.info("天气查询: %s → %s %s°C", data["city"], data["weather"], data["temperature"])
                return data
        except Exception as e:  # noqa: BLE001
            log.error("weather error: %s", e)
            return {"city": "?", "weather": "-", "temperature": "-"}

    async def weather(self, payload: dict | None = None) -> dict:
        """查询天气。
        - 如果 payload 带 city（AI 问其他城市），只查询不更新右上角。
        - 否则查询本地天气并更新右上角。
        """
        from .websocket_server import manager

        if not settings.AMAP_API_KEY:
            data = {"city": "未配置", "weather": "-", "temperature": "-"}
            self.last_weather = data
            await manager.broadcast({"type": "weather", **data})
            return data

        city_name = (payload or {}).get("city") or ""
        is_other_city = bool(city_name)

        if city_name:
            adcode = await self._city_to_adcode(city_name)
            if not adcode:
                log.warning("无法解析城市: %s", city_name)
                return {"city": city_name, "weather": "-", "temperature": "-"}
        else:
            adcode = (payload or {}).get("adcode") or await self._resolve_adcode()

        data = await self._fetch_weather(adcode)

        if is_other_city:
            # 问其他城市天气：不更新右上角，数据仅用于 AI 回复
            log.info("其他城市天气查询（不更新面板）: %s", data.get("city"))
        else:
            # 本地天气：更新右上角
            self.last_weather = data
            await manager.broadcast({"type": "weather", **data})
        return data

    async def time_now(self, payload: dict | None = None) -> None:
        from .websocket_server import manager

        await manager.broadcast(
            {"type": "time", "now": datetime.now().isoformat(timespec="seconds")}
        )

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------
    async def tts(self, text: str) -> None:
        """通过 WebSocket 通知前端使用 Web Speech API 朗读。"""
        if not text:
            return
        from .websocket_server import manager
        from .asr_handler import asr_handler
        estimated_seconds = max(len(text) * 0.3, 3.0)
        asr_handler.mute_for(estimated_seconds + 2.0)
        asr_handler.mark_tts_output(text, estimated_seconds + 5.0)
        log.info("TTS → 前端: %s", text[:50])
        await manager.broadcast({"type": "tts_speak", "text": text})


executor = CommandExecutor()
