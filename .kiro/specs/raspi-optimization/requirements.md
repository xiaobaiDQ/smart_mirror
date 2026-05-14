# Requirements Document

## Introduction

本文档定义智能镜面语音助手项目在树莓派 4B（ARM64, 1-4GB RAM）上部署适配的优化需求。优化涵盖三个方面：前端 UI 简化（移除重动效）、后端内存优化（精简依赖与资源占用）、Linux 音频设备兼容。目标是在树莓派有限的 GPU/CPU/RAM 资源下通过源码直接运行实现流畅体验。

## Glossary

- **Frontend**: 基于 React + Vite 构建的前端 SPA，通过 nginx 静态托管
- **Backend**: 基于 FastAPI 的 Python 后端服务，负责 ASR、AI 对话、音乐播放、天气查询
- **Particle_System**: 前端背景粒子和 AI 弹窗粒子的 DOM 元素 + CSS 动画系统
- **Scanline_Effect**: 屏保中模拟 CRT 扫描线的 CSS 动画效果
- **Neon_Effect**: 使用 box-shadow 和 text-shadow 实现的霓虹发光效果
- **HUD_Corners**: 屏保四角的科幻风格装饰边框元素
- **TTS_Engine**: 使用 pyttsx3 实现的本地文字转语音引擎
- **VAD_Module**: 后端语音活动检测模块，使用 numpy 数组进行音频帧缓存
- **Docker_Image**: 用于部署后端和前端的容器镜像
- **RasPi**: 树莓派 4B 单板计算机（ARM64 架构，1-4GB RAM，VideoCore VI GPU）

## Requirements

### Requirement 1: 移除前端背景粒子系统

**User Story:** As a 用户, I want 镜面界面在树莓派上流畅显示, so that 不会因为 GPU 渲染压力导致卡顿

#### Acceptance Criteria

1. THE Frontend SHALL render the main interface without any background particle span elements
2. THE Frontend SHALL render the AI chat popup without any internal particle span elements
3. WHEN the application loads, THE Frontend SHALL create zero particle-related DOM elements
4. THE Frontend SHALL maintain a total animated DOM element count below 10

### Requirement 2: 移除扫描线和 HUD 角落装饰

**User Story:** As a 用户, I want 屏保界面简洁清晰, so that 时间和天气信息一目了然且不消耗额外 GPU 资源

#### Acceptance Criteria

1. THE Frontend SHALL render the screensaver without the Scanline_Effect element
2. THE Frontend SHALL render the screensaver without HUD_Corners elements
3. THE Frontend SHALL display the clock and weather information using static styling without continuous CSS animations (except the colon blink)

### Requirement 3: 简化霓虹发光效果

**User Story:** As a 用户, I want 文字清晰可读, so that 在镜面显示器上能快速获取信息而不依赖 GPU 密集的阴影渲染

#### Acceptance Criteria

1. THE Frontend SHALL display text without multi-layer text-shadow effects
2. THE Frontend SHALL display panels without box-shadow glow effects
3. THE Frontend SHALL use a clean dark theme with high-contrast text colors for readability
4. THE Frontend SHALL retain the dark background color scheme (dark navy/black base)

### Requirement 4: 减少 CSS 动画数量

**User Story:** As a 用户, I want 界面动画最少化, so that 树莓派 GPU 不会因持续动画而过载

#### Acceptance Criteria

1. THE Frontend SHALL remove the `rise` keyframe animation (background particles)
2. THE Frontend SHALL remove the `floatUp` keyframe animation (AI popup particles)
3. THE Frontend SHALL remove the `scan` keyframe animation (scanline)
4. THE Frontend SHALL remove the `pulse` keyframe animation (AI dot)
5. THE Frontend SHALL retain only the `blink` keyframe animation for the clock colon and the `dot` keyframe animation for the thinking indicator
6. WHEN the AI assistant is in thinking state, THE Frontend SHALL display a simple text-based indicator with minimal animation

### Requirement 5: 移除未使用的后端依赖

**User Story:** As a 开发者, I want 后端只安装必要的 Python 包, so that 容器内存占用和镜像体积最小化

#### Acceptance Criteria

1. THE Backend SHALL not include the zhipuai package in its dependencies
2. THE Backend SHALL not include the pyttsx3 package in its dependencies
3. THE Backend SHALL declare all remaining dependencies with pinned versions in requirements.txt

### Requirement 6: 使用浏览器端 Web Speech API 替代 pyttsx3 TTS

**User Story:** As a 开发者, I want TTS 在浏览器端执行, so that 后端不需要加载 TTS 引擎和 espeak-ng 系统依赖从而节省内存

#### Acceptance Criteria

1. WHEN the Backend receives text to speak, THE Backend SHALL send a WebSocket message with type `tts_speak` containing the text content to the Frontend
2. WHEN the Frontend receives a `tts_speak` WebSocket message, THE Frontend SHALL use the browser Web Speech API (speechSynthesis) to speak the text
3. THE Frontend SHALL prefer a Chinese voice (zh-CN) when available in the browser speech synthesis voices
4. IF the browser does not support Web Speech API, THEN THE Frontend SHALL silently skip TTS playback and log a warning to the console
5. THE Backend SHALL remove the pyttsx3 import and the `_tts_speak` synchronous method
6. THE Backend SHALL remove the espeak-ng system dependency from the Docker image

### Requirement 7: Linux 音频设备兼容（免驱 USB 麦克风/喇叭）

**User Story:** As a 开发者, I want 后端在树莓派 Linux 上自动识别免驱 USB 麦克风和喇叭, so that 无需额外配置即可正常录音和播放

#### Acceptance Criteria

1. THE Backend SHALL use ALSA-compatible audio device enumeration on Linux (sounddevice uses PortAudio which supports ALSA)
2. THE Backend SHALL prefer USB audio devices over HDMI or built-in audio when selecting input device on Linux
3. THE Backend SHALL log all detected input devices at startup for debugging
4. IF no USB microphone is detected, THEN THE Backend SHALL log an error message with troubleshooting hints (check `arecord -l`)
5. THE Backend device selection blacklist SHALL include "hdmi" and "bcm2835" (树莓派内置音频，质量差) on Linux
6. THE requirements.txt SHALL include `sounddevice` and `numpy` which are the only audio dependencies needed (PortAudio system library must be installed separately via `apt install libportaudio2`)

### Requirement 8: 优化 VAD 内存使用

**User Story:** As a 开发者, I want VAD 模块的内存使用受到限制, so that 在 1GB RAM 的树莓派上也不会因音频缓存导致 OOM

#### Acceptance Criteria

1. THE VAD_Module SHALL limit the pre-roll buffer to a maximum of 1 second of audio frames
2. THE VAD_Module SHALL limit the accumulated speech frames buffer to a maximum of 30 seconds of audio
3. IF the speech frames buffer exceeds 30 seconds, THEN THE VAD_Module SHALL stop the current recognition session and process the accumulated audio
4. THE VAD_Module SHALL reuse pre-allocated numpy arrays where possible instead of creating new arrays per audio callback

### Requirement 9: 后端运行时内存限制

**User Story:** As a 开发者, I want 后端服务在树莓派上内存占用可控, so that 系统有足够内存给前端浏览器和操作系统

#### Acceptance Criteria

1. THE Backend SHALL operate with a steady-state RSS memory usage below 200MB under normal operation (idle + periodic weather updates)
2. WHEN processing a voice interaction (ASR + AI reply), THE Backend SHALL not exceed 350MB peak RSS memory

### Requirement 10: 删除 Docker 部署文件

**User Story:** As a 开发者, I want Docker 相关文件移除, so that 项目结构更清晰且不会误导部署方式

#### Acceptance Criteria

1. THE project SHALL not contain the `docker/` directory (docker-compose.yml, Dockerfile.backend, Dockerfile.frontend, nginx.conf)
2. THE project SHALL include a README or comment in .env.example explaining how to run directly on RasPi (pip install + npm build + uvicorn)

