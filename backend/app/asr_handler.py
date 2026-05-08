"""
asr_handler.py
--------------
本地 ASR (faster-whisper) + 唤醒词检测。

执行逻辑:
- mic_loop 持续按 ASR_CHUNK_SECONDS 秒切片采样 (sounddevice)
- 每段音频先做能量阈值过滤静音
- 非静音段 → faster-whisper 转中文文本
- feed_text 判断唤醒词 / 转 ai_handler

依赖: sounddevice, faster-whisper, numpy
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from typing import TYPE_CHECKING

from .config import settings
from .utils import fire_and_forget, get_logger

if TYPE_CHECKING:
    import numpy as np

log = get_logger("asr")


class ASRHandler:
    def __init__(self) -> None:
        self.wake_word = settings.WAKE_WORD
        self.is_awake = False
        self._awake_timeout: asyncio.Task | None = None
        self._model = None  # 懒加载
        # 当用户说出唤醒词但后面没接指令时，下一段录音用更长窗口
        self._awaiting_command: bool = False
        # TTS 播报期间闭麦，防止 AI 自己的声音被再次识别成输入
        self._mic_muted_until: float = 0.0
        # 音乐播放中：提高 VAD 阈值，避免麦克风采到音乐误触发
        self._music_playing: bool = False
        self._last_tts_norm: str = ""
        self._last_tts_until: float = 0.0
        self._last_asr_norm: str = ""
        self._last_asr_ts: float = 0.0
        self._mic_lock_path = os.path.join(tempfile.gettempdir(), "smart_mirror_mic_loop.pid")

    def mute_until(self, ts: float) -> None:
        """把麦克风静音到某个绝对时间戳 (time.time() 纪元秒)。"""
        if ts > self._mic_muted_until:
            self._mic_muted_until = ts

    def set_mute_until(self, ts: float) -> None:
        self._mic_muted_until = ts

    def mute_for(self, seconds: float) -> None:
        import time as _t
        self.mute_until(_t.time() + max(0.0, seconds))

    def mark_tts_output(self, text: str, seconds: float = 25.0) -> None:
        self._last_tts_norm = self._norm_for_echo(text)
        self._last_tts_until = time.time() + seconds

    def _norm_for_echo(self, text: str) -> str:
        return re.sub(r"[\W_]+", "", text or "").lower()

    def _is_tts_echo(self, text: str) -> bool:
        if time.time() > self._last_tts_until:
            return False
        current = self._norm_for_echo(text)
        previous = self._last_tts_norm
        if len(current) < 4 or len(previous) < 4:
            return False
        return current in previous or previous in current

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _acquire_mic_owner(self) -> bool:
        current = os.getpid()
        try:
            if os.path.exists(self._mic_lock_path):
                raw = open(self._mic_lock_path, "r", encoding="utf-8").read().strip()
                old_pid = int(raw or "0")
                if old_pid != current and self._pid_alive(old_pid):
                    log.warning("检测到已有 mic_loop 进程 PID=%d，本进程跳过麦克风采集", old_pid)
                    return False
            with open(self._mic_lock_path, "w", encoding="utf-8") as f:
                f.write(str(current))
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("mic_loop 单实例锁失败，继续启动: %s", e)
            return True

    # ---------- 唤醒词 ----------
    # 兼容 Whisper 输出的繁体 / 同音字 / 漏字
    # "小" 同音/形近: 小消晓肖宵筱孝校效校
    # "镜" 同音/形近 (jing/jin/qing/jin等): 镜静景敬竞净进尽京经今紧锦谨晋仅近紧鏡靜競淨進盡經緊錦
    _XIAO = "小消晓肖宵筱孝校晓"
    _JING = "镜静景敬竞净进尽京经今紧锦谨晋仅近鏡靜競淨進盡經緊錦"
    _WAKE_RE = re.compile(
        rf"[{_XIAO}]\s*[{_JING}]"
        rf"(?:\s*[{_XIAO}]?\s*[{_JING}])?"
    )

    def _normalize(self, text: str) -> str:
        return re.sub(r"[\s，,。.！!?？、]", "", text)

    def _match_wake(self, text: str) -> bool:
        return bool(self._WAKE_RE.search(self._normalize(text)))

    def _strip_wake(self, text: str) -> str:
        return self._WAKE_RE.sub("", self._normalize(text)).strip(" ，,。.！!?？、")

    async def set_awake(self, seconds: float | None = None) -> None:
        if seconds is None:
            seconds = settings.AWAKE_TIMEOUT
        self.is_awake = True
        log.info("WAKE activated for %.1fs", seconds)
        if self._awake_timeout and not self._awake_timeout.done():
            self._awake_timeout.cancel()

        async def _expire() -> None:
            await asyncio.sleep(seconds)
            self.is_awake = False
            log.info("WAKE expired")

        self._awake_timeout = asyncio.create_task(_expire())

    # ---------- 文本入口 ----------
    async def feed_text(self, text: str) -> None:
        from .ai_handler import correct_asr_text, handle_user_text
        from .websocket_server import manager

        text = (text or "").strip()
        if not text:
            return
        log.info("ASR raw: %s  (awake=%s)", text, self.is_awake)
        if self._mic_muted_until > time.time():
            log.info("闭麦期间忽略 ASR: %s", text)
            return
        if self._is_tts_echo(text):
            log.info("忽略 TTS 回声: %s", text)
            return
        norm = self._norm_for_echo(text)
        now = time.time()
        if norm and norm == self._last_asr_norm and now - self._last_asr_ts < 8.0:
            log.info("忽略重复 ASR: %s", text)
            return
        self._last_asr_norm = norm
        self._last_asr_ts = now

        # ★ DeepSeek 纠错（当前禁用，如需启用改为 True）
        # if False:
        #     await manager.broadcast({"type": "asr_step", "step": "correcting", "raw": text})
        #     text = await correct_asr_text(text)
        #     log.info("ASR corrected: %s", text)
        #     await manager.broadcast({"type": "asr_step", "step": "corrected", "text": text})

        await manager.broadcast({"type": "asr_text", "text": text, "awake": self.is_awake})

        if not self.is_awake:
            if self._match_wake(text):
                await self.set_awake()
                await manager.broadcast(
                    {"type": "wake", "status": "awake", "wake_word": self.wake_word}
                )
                tail = self._strip_wake(text)
                if tail:
                    self._awaiting_command = False
                    fire_and_forget(handle_user_text(tail))
                else:
                    self._awaiting_command = True
            return

        # 已唤醒：作为问题/指令
        self._awaiting_command = False
        fire_and_forget(handle_user_text(text))

    # ---------- 模型 + 音频 ----------
    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # 延迟导入

            log.info(
                "加载 Whisper 模型 model=%s device=%s compute=%s ...",
                settings.WHISPER_MODEL, settings.WHISPER_DEVICE, settings.WHISPER_COMPUTE,
            )
            self._model = WhisperModel(
                settings.WHISPER_MODEL,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE,
            )
            log.info("Whisper 模型加载完成")
        return self._model

    _input_device: int | None = None
    _input_sr: int = 16000
    _device_picked: bool = False

    def _candidate_devices(self):
        """按 WASAPI > WDM-KS > DirectSound > MME 顺序产出 (device_idx, sample_rate)。"""
        import sounddevice as sd

        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception as e:  # noqa: BLE001
            log.error("枚举音频设备失败: %s", e)
            return

        priority = ["WASAPI", "WDM-KS", "DirectSound", "MME"]
        # 黑名单：蓝牙 HFP / 虚拟设备
        blacklist = (
            "hands-free", "hfp", "bluetooth", "todesk",
            "virtual audio", "立体声混音", "stereo mix",
            "扬声器", "speaker", "output", "loopback", "what u hear",
            # 蓝牙/无线耳机 (HFP 通话麦克风音质差，跳过)
            "耳机", "tws", "headset", "earphone", "earbud", "airpod", "buds",
        )
        # 用户指定的设备名子串（最高优先级）
        wanted = (settings.ASR_INPUT_DEVICE_NAME or "").strip().lower()

        order: list[tuple[int, int, int, dict]] = []  # (priority, device_idx, info)
        for i, info in enumerate(devices):
            if info.get("max_input_channels", 0) <= 0:
                continue
            api_idx = info.get("hostapi", -1)
            if api_idx < 0 or api_idx >= len(hostapis):
                continue
            api_name = hostapis[api_idx].get("name", "")
            dev_name = (info.get("name") or "").lower()
            if any(b in dev_name for b in blacklist):
                continue
            try:
                p = next(p for p, n in enumerate(priority) if n in api_name)
            except StopIteration:
                p = len(priority)
            # 用户指定的名字提到最前
            user_pref = 0 if (wanted and wanted in dev_name) else 1
            order.append((user_pref, p, i, info))

        order.sort(key=lambda x: (x[0], x[1]))
        for _u, _p, idx, info in order:
            sr = int(info.get("default_samplerate") or settings.AUDIO_SAMPLE_RATE)
            api_name = hostapis[info["hostapi"]].get("name", "?")
            log.info("候选输入设备 idx=%d api=%s sr=%d name=%s",
                     idx, api_name, sr, info.get("name"))
            yield idx, sr

    def _open_test_record(self, device_idx: int, sr: int, seconds: float = 0.3):
        """用极短录音验证设备能否打开。失败抛异常。"""
        import sounddevice as sd

        a = sd.rec(
            int(seconds * sr),
            samplerate=sr,
            channels=settings.AUDIO_CHANNELS,
            dtype="float32",
            device=device_idx,
        )
        sd.wait()
        return a

    def _pick_input_device(self) -> bool:
        if self._device_picked:
            return self._input_device is not None
        for idx, sr in self._candidate_devices():
            try:
                self._open_test_record(idx, sr)
                self._input_device = idx
                self._input_sr = sr
                log.info("✅ 选定输入设备 idx=%d sr=%d", idx, sr)
                self._device_picked = True
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("设备 idx=%d sr=%d 不可用: %s", idx, sr, e)
        log.error("❌ 未找到可用麦克风")
        self._device_picked = True
        return False

    def _record_chunk(self, seconds: float):
        import sounddevice as sd
        import numpy as np

        if not self._device_picked and not self._pick_input_device():
            raise RuntimeError("无可用麦克风")

        sr = self._input_sr
        audio = sd.rec(
            int(seconds * sr),
            samplerate=sr,
            channels=settings.AUDIO_CHANNELS,
            dtype="float32",
            device=self._input_device,
        )
        sd.wait()
        audio = audio.reshape(-1)

        # 重采样到 16kHz (whisper 要求)
        target_sr = settings.AUDIO_SAMPLE_RATE
        if sr != target_sr:
            n_target = int(len(audio) * target_sr / sr)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n_target, dtype=np.float32),
                np.arange(len(audio), dtype=np.float32),
                audio,
            ).astype(np.float32)
        return audio

    def _resample(self, audio, source_sr: int):
        """重采样到 16kHz (Whisper 要求)。"""
        import numpy as np
        target_sr = settings.AUDIO_SAMPLE_RATE
        if source_sr == target_sr:
            return audio
        n_target = int(len(audio) * target_sr / source_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_target, dtype=np.float32),
            np.arange(len(audio), dtype=np.float32),
            audio,
        ).astype(np.float32)

    # 详细的领域提示词（给 Whisper 的"词表偏置"），大幅降低同音字/漏字错误
    _INITIAL_PROMPT = (
        "以下是普通话句子的简体中文转写。"
        "唤醒词：小镜小镜、小镜。"
        "常见指令：今天天气怎么样、北京天气、上海天气、乌鲁木齐天气、现在几点了、"
        "播放音乐、暂停、下一首、上一首、声音大一点、声音小一点。"
        "常见问题：讲个笑话、今天日期、你是谁、帮我查一下、打开灯、关闭灯、"
        "请问我现在在哪里、给我讲个故事、明天天气怎么样。"
        "数字示例：一二三四五六七八九十、零、百、千、万、亿、"
        "一百二十三、三千五百、一万八、二十五度、百分之六十、"
        "一月二月三月、一号、十五号、二十号、三十一号、"
        "一点半、两点十五分、三点四十五、下午六点、晚上八点、"
        "一百块、五十元、两千三百四十五。"
    )

    def _transcribe(self, audio) -> str:
        model = self._load_model()
        segments, _info = model.transcribe(
            audio,
            language=settings.WHISPER_LANGUAGE,
            task="transcribe",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "threshold": 0.4},
            beam_size=settings.WHISPER_BEAM_SIZE,
            best_of=settings.WHISPER_BEST_OF,
            temperature=[0.0, 0.2, 0.4],          # 失败时降级采样
            no_speech_threshold=settings.WHISPER_NO_SPEECH_THR,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,
            initial_prompt=self._INITIAL_PROMPT,
        )
        return "".join(s.text for s in segments).strip()

    # ---------- 主循环 ----------
    async def mic_loop(self) -> None:
        if not self._acquire_mic_owner():
            return

        try:
            import sounddevice as sd  # noqa: F401
            import numpy as np
        except ImportError as e:
            log.error("sounddevice / numpy 未安装: %s", e)
            return

        # 列出设备方便排查
        try:
            default_in = sd.default.device[0] if sd.default.device else None
            log.info("默认输入设备: %s", default_in)
        except Exception:  # noqa: BLE001
            pass

        # 预热模型 (首次推理慢)
        try:
            await asyncio.to_thread(self._load_model)
        except Exception as e:  # noqa: BLE001
            log.exception("Whisper 模型加载失败: %s", e)
            return

        # 选麦克风
        ok = await asyncio.to_thread(self._pick_input_device)
        if not ok:
            log.error("未找到可用麦克风设备，mic_loop 退出。请检查 Windows 隐私 → 麦克风设置")
            return

        import queue as _queue
        import time as _t

        sr = self._input_sr
        frame_ms = settings.VAD_FRAME_MS
        frame_samples = int(sr * frame_ms / 1000)
        audio_q: _queue.Queue = _queue.Queue(
            maxsize=int(settings.VAD_MAX_SPEECH_S * 1000 / frame_ms + 200)
        )

        def _on_audio(indata, frames, time_info, status):
            if status:
                log.warning("audio stream: %s", status)
            try:
                audio_q.put_nowait(indata[:, 0].copy())
            except _queue.Full:
                pass

        log.info(
            "麦克风流启动 device=%s sr=%d frame=%dms vad_silence=%d×%dms",
            self._input_device, sr, frame_ms,
            settings.VAD_SILENCE_FRAMES, frame_ms,
        )

        _fail_count = 0
        while True:
            # ---- 打开音频流 ----
            try:
                stream = sd.InputStream(
                    samplerate=sr,
                    channels=settings.AUDIO_CHANNELS,
                    dtype="float32",
                    device=self._input_device,
                    blocksize=frame_samples,
                    callback=_on_audio,
                )
                stream.start()
            except Exception as e:  # noqa: BLE001
                _fail_count += 1
                wait = min(2 ** _fail_count, 30)
                log.error("麦克风流打开失败 (第%d次，%ds后重试): %s", _fail_count, wait, e)
                if _fail_count >= 3:
                    self._device_picked = False
                    try:
                        await asyncio.to_thread(self._pick_input_device)
                        sr = self._input_sr
                        frame_samples = int(sr * frame_ms / 1000)
                    except Exception:  # noqa: BLE001
                        pass
                await asyncio.sleep(wait)
                continue

            _fail_count = 0
            log.info("✅ 麦克风流已打开")

            # ---- VAD 状态 ----
            noise_floor: float = settings.ASR_SILENCE_THRESHOLD
            is_speaking = False
            speech_frames: list = []
            speech_frame_count = 0
            silence_count = 0
            pre_roll: list = []
            PRE_ROLL_N = 3          # ~300ms 前置缓冲，避免起始被切
            log_counter = 0

            try:
                while True:
                    # 批量取帧（不阻塞事件循环）
                    batch: list = []
                    while not audio_q.empty():
                        try:
                            batch.append(audio_q.get_nowait())
                        except _queue.Empty:
                            break
                    if not batch:
                        await asyncio.sleep(0.05)
                        continue

                    for frame in batch:
                        # TTS 闭麦期间丢弃
                        if self._mic_muted_until > _t.time():
                            is_speaking = False
                            speech_frames.clear()
                            speech_frame_count = 0
                            silence_count = 0
                            continue

                        level = float(np.abs(frame).mean())
                        # 音乐播放时大幅提高阈值，只有大声说话才触发
                        # 但已唤醒时用稍低阈值，方便下达指令
                        if self._music_playing and not self.is_awake:
                            threshold = max(noise_floor * settings.VAD_NOISE_RATIO * 4, 0.02)
                        elif self._music_playing and self.is_awake:
                            threshold = max(noise_floor * settings.VAD_NOISE_RATIO * 2, 0.01)
                        else:
                            threshold = max(noise_floor * settings.VAD_NOISE_RATIO, 0.0008)

                        log_counter += 1
                        if log_counter % max(1, 3000 // frame_ms) == 0:
                            log.info(
                                "audio level=%.4f noise=%.4f thr=%.4f speaking=%s",
                                level, noise_floor, threshold, is_speaking,
                            )

                        if level > threshold:
                            if not is_speaking:
                                is_speaking = True
                                speech_frame_count = len(pre_roll)
                                speech_frames = list(pre_roll)
                                pre_roll.clear()
                            silence_count = 0
                            speech_frame_count += 1
                            speech_frames.append(frame)
                        elif is_speaking:
                            silence_count += 1
                            speech_frame_count += 1
                            speech_frames.append(frame)

                            duration_ms = speech_frame_count * frame_ms

                            if (silence_count >= settings.VAD_SILENCE_FRAMES
                                    or duration_ms >= settings.VAD_MAX_SPEECH_S * 1000):
                                if duration_ms >= settings.VAD_MIN_SPEECH_MS:
                                    audio = np.concatenate(speech_frames)
                                    audio = self._resample(audio, sr)
                                    log.info("VAD 语音段 %.1fs，转写中…", duration_ms / 1000)
                                    from .websocket_server import manager as _mgr
                                    await _mgr.broadcast({"type": "asr_step", "step": "recognizing"})
                                    text = await asyncio.to_thread(self._transcribe, audio)
                                    if text:
                                        await self.feed_text(text)
                                    else:
                                        log.info("Whisper 未识别出文本")
                                        await _mgr.broadcast({"type": "asr_step", "step": "idle"})
                                else:
                                    log.debug("VAD 跳过短语音 %.0fms", duration_ms)
                                is_speaking = False
                                speech_frames.clear()
                                speech_frame_count = 0
                                silence_count = 0
                        else:
                            # 静音：指数滑动更新噪声底噪
                            noise_floor = noise_floor * 0.97 + level * 0.03
                            noise_floor = max(noise_floor, 0.00005)
                            pre_roll.append(frame)
                            if len(pre_roll) > PRE_ROLL_N:
                                pre_roll.pop(0)

            except Exception as e:  # noqa: BLE001
                log.error("mic_loop VAD 错误: %s", e)
            finally:
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                while not audio_q.empty():
                    try:
                        audio_q.get_nowait()
                    except _queue.Empty:
                        break

            # 流断开，重试
            _fail_count += 1
            wait = min(2 ** _fail_count, 30)
            log.warning("麦克风流断开，%ds后重试", wait)
            await asyncio.sleep(wait)


asr_handler = ASRHandler()
