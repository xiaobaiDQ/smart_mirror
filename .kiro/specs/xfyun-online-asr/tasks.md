# Implementation Plan: 讯飞在线 ASR 替换 faster-whisper

## Overview

将 ASR 引擎从本地 faster-whisper 替换为讯飞在线语音听写 WebSocket 接口。按模块逐步实现：配置 → 客户端核心 → ASR 集成 → 依赖清理，每步配合属性测试验证正确性。

## Tasks

- [x] 1. 更新配置模块与环境变量
  - [x] 1.1 修改 `backend/app/config.py`，移除 Whisper 配置项（WHISPER_MODEL, WHISPER_COMPUTE, WHISPER_DEVICE, WHISPER_LANGUAGE, WHISPER_BEAM_SIZE, WHISPER_BEST_OF, WHISPER_NO_SPEECH_THR），新增讯飞配置项（XFYUN_APPID, XFYUN_API_KEY, XFYUN_API_SECRET, XFYUN_LANGUAGE="zh_cn", XFYUN_DOMAIN="iat"）
    - _Requirements: 1.4, 3.1, 3.2, 3.3_
  - [x] 1.2 修改 `backend/.env.example`，移除 Whisper 相关环境变量，添加 XFYUN_APPID, XFYUN_API_KEY, XFYUN_API_SECRET 占位条目
    - _Requirements: 3.4_

- [x] 2. 实现 XFYunClient 核心类
  - [x] 2.1 创建 `backend/app/xfyun_client.py`，实现 `XFYunClient.__init__` 和 `_build_auth_url` 方法（HMAC-SHA256 签名鉴权 URL 构造）
    - 使用 hmac, hashlib, base64, urllib.parse 标准库
    - 签名原文格式：host + date + request-line
    - _Requirements: 2.1, 2.2_
  - [ ]* 2.2 编写属性测试：Auth URL 签名可验证
    - **Property 1: Auth URL signature is verifiable**
    - **Validates: Requirements 2.1**
  - [x] 2.3 实现 `_audio_to_pcm` 方法（float32 → PCM 16-bit signed integer）
    - np.clip + (audio * 32767).astype(np.int16).tobytes()
    - _Requirements: 4.1_
  - [ ]* 2.4 编写属性测试：Float32 到 PCM int16 转换正确性
    - **Property 4: Float32 to PCM int16 conversion**
    - **Validates: Requirements 4.1**
  - [x] 2.5 实现 `_split_frames` 方法（PCM 数据按 1280 字节分帧）
    - _Requirements: 4.2_
  - [ ]* 2.6 编写属性测试：PCM 分帧大小正确性
    - **Property 5: PCM framing produces correct frame sizes**
    - **Validates: Requirements 4.2**
  - [ ]* 2.7 编写属性测试：帧状态分配遵循协议
    - **Property 6: Frame status assignment follows protocol**
    - **Validates: Requirements 4.3**
  - [x] 2.8 实现 `_parse_response` 方法（解析讯飞 JSON 响应，提取并拼接文本）
    - 遍历 data.result.ws[].cw[].w 拼接
    - 返回 (text_segment, is_final) 元组
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 2.9 编写属性测试：响应解析正确拼接文本
    - **Property 7: Response parsing extracts and concatenates text correctly**
    - **Validates: Requirements 5.1, 5.2**

- [x] 3. 实现 XFYunClient 转写主流程
  - [x] 3.1 实现 `transcribe` 异步方法：空凭证检查 → 建立 WebSocket 连接 → 构造首帧（含 common + business + data）→ 分帧发送（40ms 间隔）→ 接收结果 → 拼接返回
    - 使用 websockets 库建立连接
    - asyncio.wait_for 实现 10 秒超时
    - 所有异常捕获并返回空字符串
    - _Requirements: 2.3, 2.4, 3.5, 4.3, 4.4, 4.5, 5.3, 8.1, 8.2_
  - [ ]* 3.2 编写属性测试：空凭证守卫
    - **Property 3: Empty credentials guard**
    - **Validates: Requirements 3.5**
  - [ ]* 3.3 编写属性测试：首帧包含必需协议字段
    - **Property 2: First frame contains required protocol fields**
    - **Validates: Requirements 2.3**
  - [ ]* 3.4 编写单元测试：mock WebSocket 验证完整 transcribe 流程
    - 测试正常流程、连接失败、超时、错误码响应
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 4. Checkpoint - 确保 XFYunClient 所有测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. 修改 ASR_Handler 集成讯飞客户端
  - [x] 5.1 修改 `backend/app/asr_handler.py`：移除 faster-whisper 导入和 `_load_model` 方法，移除 `_transcribe` 方法中的 Whisper 调用
    - _Requirements: 1.1, 1.2_
  - [x] 5.2 在 `backend/app/xfyun_client.py` 底部创建模块级 `xfyun_client` 实例（从 config 读取凭证），在 `asr_handler.py` 中新增 `_transcribe_xfyun` 异步方法调用该实例
    - _Requirements: 6.4, 6.5_
  - [x] 5.3 修改 `mic_loop` 中的转写调用：将 `await asyncio.to_thread(self._transcribe, audio)` 替换为 `await self._transcribe_xfyun(audio)`，转写失败时广播 idle 状态
    - _Requirements: 7.3, 8.3, 8.4_
  - [ ]* 5.4 编写属性测试：重采样保持时长
    - **Property 8: Resample preserves duration**
    - **Validates: Requirements 6.5**

- [x] 6. 更新依赖与启动日志
  - [x] 6.1 修改 `backend/requirements.txt`：移除 faster-whisper 包，确认 websockets 已存在
    - _Requirements: 9.1, 9.2, 9.3_
  - [x] 6.2 修改 `backend/app/main.py`：更新 lifespan 日志，移除 Whisper 模型加载相关日志，添加讯飞 ASR 就绪日志
    - _Requirements: 1.1, 1.2_

- [x] 7. Final checkpoint - 确保所有测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- 标记 `*` 的任务为可选属性测试/单元测试任务，可跳过以加速 MVP
- 每个任务引用具体需求编号以确保可追溯性
- 属性测试使用 hypothesis 库，每个属性至少 100 次迭代
- 所有错误处理遵循统一原则：不中断 mic_loop，不抛出异常，失败返回空字符串
