"""
config.py
---------
集中管理所有 API Key、主机端口、路径等配置项。
使用 pydantic-settings 支持从 .env / 环境变量注入。

功能:
- 声明全局配置单例 `settings`
- 任何模块 `from app.config import settings` 即可安全读取

依赖: pydantic, pydantic-settings, python-dotenv
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---- 服务 ----
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = True

    # ---- 唤醒词 ----
    WAKE_WORD: str = "小镜小镜"

    # ---- 本地 ASR (faster-whisper) ----
    WHISPER_MODEL: str = "models/pengzhendong/faster-whisper-small"  # 本地 small 模型路径
    WHISPER_COMPUTE: str = "int8"         # int8 / int8_float16 / float16 / float32
    WHISPER_DEVICE: str = "cpu"           # cpu / cuda
    WHISPER_LANGUAGE: str = "zh"
    WHISPER_BEAM_SIZE: int = 5            # 1=最快, 5=更准 (CPU int8 small 模型 6s 音频约 2-3 秒)
    WHISPER_BEST_OF: int = 5              # 采样候选数量，越高越稳定
    WHISPER_NO_SPEECH_THR: float = 0.35   # 静音判定 (0.6 默认, 降低以保留更多句子)
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    ASR_CHUNK_SECONDS: float = 2.0          # 扫描唤醒词的窗口 (越短响应越快)
    ASR_CHUNK_SECONDS_AWAKE: float = 6.0    # 已唤醒/等待指令时的窗口
    AWAKE_TIMEOUT: float = 15.0             # 唤醒后保持激活态的秒数
    ASR_SILENCE_THRESHOLD: float = 0.001  # 静音判定阈值 (mean abs amplitude)
    ASR_AUTO_START: bool = True           # 后端启动后自动开启麦克风采集
    ASR_INPUT_DEVICE_NAME: str = ""       # 子串匹配，如 "麦克风阵列" "Realtek" 留空=自动选

    # ---- VAD (语音活动检测) ----
    VAD_FRAME_MS: int = 100              # 每帧时长 (毫秒)
    VAD_NOISE_RATIO: float = 3.0         # 语音判定 = 噪声底噪 × 此倍数
    VAD_SILENCE_FRAMES: int = 8          # 连续静音帧数 → 语音结束 (8×100ms=800ms)
    VAD_MIN_SPEECH_MS: int = 400         # 最短语音段 (过短丢弃)
    VAD_MAX_SPEECH_S: float = 12.0       # 最长语音段 (超时截断转写)

    # ---- ListenHub ASR (备用，未使用) ----
    LISTENHUB_API_KEY: str = ""
    LISTENHUB_ENDPOINT: str = "https://api.listenhub.cn/v1/asr"

    # ---- DeepSeek (OpenAI 兼容协议) ----
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # ---- 智普大模型 (备用) ----
    ZHIPU_API_KEY: str = ""
    ZHIPU_MODEL: str = "glm-4-flash"
    AI_SYSTEM_PROMPT: str = (
        "你是智能镜面语音助手『小镜』，性格活泼友善，像朋友一样跟用户聊天。\n\n"
        "## 重要：语音纠错\n"
        "用户输入来自 Whisper 语音识别，经常出现同音字/近音字/繁体字/漏字错误。\n"
        "你必须先根据上下文和发音相似性，猜测用户真正想说的话，然后基于纠正后的含义回答。\n"
        "常见误识别举例：\n"
        "  '再劳你' / '在老你' → '在哪里'\n"
        "  '盡小盡' / '小靜' / '小景' / '效进' → '小镜小镜'（唤醒词，忽略）\n"
        "  '怎麼樣' → '怎么样'\n"
        "  '程度' / '成落' / '成功' → '成都'（城市名）\n"
        "  '今天程度的天气' → '今天成都的天气'\n"
        "  '上海' / '商还' → '上海'\n"
        "  '乌鲁木齐' / '物入目器' → '乌鲁木齐'\n"
        "  '再见' / '载件' → 可能是'再见'\n"
        "  发音相近就大胆纠正，宁可猜对也不要按字面意思回答乱七八糟的话。\n\n"
        "## 回答规则\n"
        "1. 回答必须是简体中文，自然流畅，像朋友一样说话。\n"
        "2. 回复长度：简单操作（播放/暂停/关闭）15字以内，聊天/问答50-100字，可以有趣有个性。\n"
        "3. 必须只输出一个 JSON，格式如下，不要输出其他文本：\n"
        '   {"action":"play_music|pause|next|weather|time|chat|dismiss",'
        '"payload":{...},"reply":"你的回答",'
        '"corrected":"纠正后的用户原话"}\n'
        "   - corrected: 你理解的用户真实意图（简体中文，去掉识别噪音）\n"
        '   - play_music payload: {"keyword":"歌曲或歌手名"}  用户说「推荐一首歌/随便放一首/来首音乐」时，你自己选一首歌填入keyword\n'
        '   - weather payload: {"city":"城市名"}  用户问某地天气时填城市名，如"北京"/"上海"/"成都"。问"今天天气"不带城市则填空 {"city":""}\n'
        '   - time payload: {}\n'
        '   - dismiss: 用户说「关闭/再见/拜拜/不用了/退下/没事了」等告别语时使用\n'
        '   - chat: 闲聊/问答/讲笑话/百科知识等，reply 里尽量给出有用有趣的回答\n'
        "4. 不确定用户说什么时，corrected 填你最佳猜测，reply 友好追问。\n"
        "5. 用户问知识性问题（历史/科学/生活常识等）时，action 用 chat，reply 给出详细有趣的回答。"
    )

    # ---- 网易云音乐 API (NeteaseCloudMusicApi Node 服务) ----
    NETEASE_API_BASE: str = "http://localhost:3000"

    # ---- 高德天气 ----
    AMAP_API_KEY: str = ""
    AMAP_CITY_ADCODE: str = "659002"  # 阿拉尔市；留空则启动时自动用 IP 定位
    AMAP_WEATHER_URL: str = "https://restapi.amap.com/v3/weather/weatherInfo"
    AMAP_IP_URL: str = "https://restapi.amap.com/v3/ip"

    # ---- 路径 ----
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    MUSIC_CACHE_DIR: Path = BASE_DIR.parent / "music"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
settings.MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
