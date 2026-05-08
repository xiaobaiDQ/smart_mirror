# Smart Mirror — 嵌入式智能交互镜

一个面向树莓派 4B (8GB) 的全栈智能交互镜系统：
唤醒词触发 → ListenHub ASR 语音转文本 → 智普大模型 AI 问答 → QQ 音乐播放 / TTS / 天气查询 → 科幻风前端实时展示。

## 功能概览

- **屏保模式**：显示时间 + 天气（高德 API），科幻霓虹粒子 UI。
- **唤醒词 + ASR**：ListenHub 语音识别，唤醒后才接受指令。
- **AI 问答**：智普（Zhipu GLM）大模型，弹窗展示「AI 正在思考…」→ 回答。
- **在线音乐**：QQ 音乐 API 播放 / 暂停 / 切歌。
- **TTS**：回答文本合成语音播报。
- **实时通信**：FastAPI + WebSocket 前后端解耦，异步并发。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + 原生 CSS (科幻主题) |
| 后端 | FastAPI + Uvicorn + WebSocket + asyncio |
| AI | 智普 GLM (ChatGLM) |
| ASR | ListenHub |
| 音乐 | QQ 音乐 第三方 API |
| 天气 | 高德开放平台 |
| 部署 | Docker + docker-compose (arm64 树莓派) |

## 目录结构

```
smart-mirror/
├── frontend/              # React + Vite 前端
├── backend/               # FastAPI 后端
├── docker/                # Dockerfile & compose
├── music/                 # 音乐缓存 / 示例
└── README.md
```

## 快速开始（本机开发）

### 后端

```bash
cd backend
pip install -r requirements.txt
# 配置环境变量 (或复制 .env 示例)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。

## Docker 部署 (树莓派 4B)

```bash
cd docker
docker compose up -d --build
```

容器会映射 `/dev/snd` 音频设备以支持麦克风 / 扬声器。

## 环境变量

在 `backend/` 下创建 `.env`：

```
LISTENHUB_API_KEY=xxx
ZHIPU_API_KEY=xxx
QQ_MUSIC_API_BASE=http://localhost:3300
AMAP_API_KEY=xxx
AMAP_CITY_ADCODE=110000
WAKE_WORD=小镜小镜
HOST=0.0.0.0
PORT=8000
```

## 执行流程

1. FastAPI 启动，WebSocket `/ws` 就绪。
2. 前端连接 WebSocket，进入屏保（时间 + 天气）。
3. `asr_handler` 监听麦克风，检测唤醒词 → 录制语音 → 转文本。
4. 文本经 `ai_handler` 发送至智普 GLM，返回 JSON 指令或自然回答。
5. `command_executor` 根据指令执行：播放音乐 / 查询天气 / TTS。
6. WebSocket 将状态实时推送前端：`AIChatPopup` 显示思考/回答，`MusicControl` 同步播放状态。

## 模块解耦

- 所有后端模块均为 `async`，通过 `asyncio.create_task` 并行执行。
- 前端组件通过 `WebSocketService` 单例订阅消息；各 UI 组件互不耦合。
- 新增技能仅需扩展 `command_executor.py`。

## License

MIT
