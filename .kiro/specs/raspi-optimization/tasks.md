# Implementation Plan: raspi-optimization

## Overview

针对树莓派 4B 的优化实现计划，按模块分步推进：前端 UI 简化 → 后端 TTS 迁移 → 依赖清理 → Linux 音频适配 → VAD 内存优化 → Docker 文件删除。每步增量构建，确保无孤立代码。

## Tasks

- [x] 1. 前端 UI 简化：移除粒子系统和装饰元素
  - [x] 1.1 App.jsx 移除背景粒子 DOM
    - 删除 `bg-particles` div 及其所有 span 子元素
    - 删除 `bg-grid` div
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 1.2 ScreenSaver.jsx 移除扫描线和 HUD 角落
    - 删除 `scanline` div 元素
    - 删除 4 个 `hud-corner` div 元素
    - 确保时钟和天气信息保留静态样式（冒号 blink 除外）
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 1.3 AIChatPopup.jsx 移除粒子 DOM
    - 删除 `ai-particles` div 及其所有 span 子元素
    - _Requirements: 1.2, 1.3_

  - [x] 1.4 重写 sci-fi-theme.css 为简洁深色主题
    - 移除 `.neon-text` 多层 text-shadow 效果
    - 移除 `.glass` box-shadow glow 效果
    - 移除 `.hud-corner`、`.scanline` 相关样式
    - 保留深色背景色方案（dark navy/black base）
    - 改用高对比度纯色文字
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 1.5 精简 animations.css 只保留 blink 和 dot
    - 移除 `rise` keyframe（背景粒子）
    - 移除 `floatUp` keyframe（AI 弹窗粒子）
    - 移除 `scan` keyframe（扫描线）
    - 移除 `pulse` keyframe（AI dot）
    - 移除 `.bg-particles`、`.ai-particles` 相关样式
    - 保留 `blink`（时钟冒号）和 `dot`（思考指示器）keyframe
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 2. Checkpoint - 前端 UI 简化验证
  - Ensure all tests pass, ask the user if questions arise.
  - 验证前端构建成功（npm run build）
  - 确认无粒子 DOM、无扫描线、无 HUD 角落、动画只剩 blink/dot

- [ ] 3. 后端 TTS 迁移：pyttsx3 → WebSocket + Web Speech API
  - [ ] 3.1 修改 command_executor.py 的 tts() 方法
    - 将 `tts()` 改为 async 方法
    - 实现通过 WebSocket broadcast 发送 `{"type": "tts_speak", "text": text}` 消息
    - 添加闭麦防回声逻辑（mute_for + mark_tts_output）
    - 移除 pyttsx3 import 和 `_tts_speak` 同步方法
    - _Requirements: 6.1, 6.5_

  - [ ] 3.2 前端 WebSocketService 新增 tts_speak 消息处理
    - 监听 `tts_speak` 类型消息
    - 使用 Web Speech API（speechSynthesis）朗读文本
    - 优先选择 zh-CN 中文语音
    - Web Speech API 不可用时静默跳过并 console.warn
    - _Requirements: 6.2, 6.3, 6.4_

  - [ ]* 3.3 Write property test for TTS broadcast (Property 2)
    - **Property 2: TTS broadcast delivers text faithfully**
    - **Validates: Requirements 6.1, 6.2**

- [ ] 4. 后端依赖清理
  - [ ] 4.1 修改 requirements.txt 移除无用依赖
    - 移除 `zhipuai` 包
    - 移除 `pyttsx3` 包
    - 确保所有剩余依赖使用 `==` 精确版本锁定
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 4.2 Write property test for pinned versions (Property 1)
    - **Property 1: All dependencies use pinned versions**
    - **Validates: Requirements 5.3**

- [ ] 5. Linux 音频设备适配
  - [ ] 5.1 修改 asr_handler.py 设备选择逻辑
    - 在 Linux 平台追加黑名单：`hdmi`、`bcm2835`
    - USB 设备优先级提升（名称含 "usb" 的设备排序靠前）
    - 启动时日志输出所有检测到的输入设备
    - 未检测到 USB 麦克风时输出 ERROR 日志 + 提示 `arecord -l`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 5.2 Write property test for device selection (Property 3)
    - **Property 3: Linux audio device selection prefers USB and excludes blacklisted devices**
    - **Validates: Requirements 7.2, 7.5**

- [ ] 6. VAD 内存优化
  - [ ] 6.1 修改 VAD 模块缓冲区实现
    - `pre_roll` 改为 `collections.deque(maxlen=PRE_ROLL_N)`，PRE_ROLL_N 基于 1 秒计算
    - `speech_frames` 添加 30 秒上限，超限时强制截断并提交转写
    - 更新 config 中 `VAD_MAX_SPEECH_S = 30.0` 和 `VAD_PRE_ROLL_S = 1.0`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 6.2 Write property test for pre-roll buffer bound (Property 4)
    - **Property 4: Pre-roll buffer is bounded**
    - **Validates: Requirements 8.1**

  - [ ]* 6.3 Write property test for speech frames buffer bound (Property 5)
    - **Property 5: Speech frames buffer is bounded and triggers processing**
    - **Validates: Requirements 8.2, 8.3**

- [ ] 7. Checkpoint - 后端功能验证
  - Ensure all tests pass, ask the user if questions arise.
  - 验证后端启动无 import 错误
  - 确认 TTS WebSocket 消息格式正确
  - 确认 VAD 缓冲区限制生效

- [x] 8. 删除 Docker 部署文件
  - [x] 8.1 删除 docker/ 目录
    - 删除 `docker/docker-compose.yml`
    - 删除 `docker/Dockerfile.backend`
    - 删除 `docker/Dockerfile.frontend`
    - 删除 `docker/nginx.conf`
    - 删除 `docker/` 目录
    - _Requirements: 10.1_

- [x] 9. Final checkpoint - 全量验证
  - Ensure all tests pass, ask the user if questions arise.
  - 确认前端 build 成功、后端启动正常
  - 确认所有需求覆盖

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 前端使用 JavaScript/JSX (React + Vite)，后端使用 Python (FastAPI)
- 每个 checkpoint 确保增量验证，避免问题累积
- Property tests 使用 hypothesis (Python) 和 fast-check (JavaScript)
