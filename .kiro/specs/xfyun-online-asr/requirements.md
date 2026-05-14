# Requirements Document

## Introduction

将智能镜面语音助手的 ASR（自动语音识别）引擎从本地部署的 faster-whisper 模型替换为讯飞（iFlytek）在线语音听写 WebSocket 实时流式接口。保留现有的麦克风采集、VAD 语音活动检测、唤醒词检测及 AI 处理链路不变，仅替换语音转文字的底层实现。

## Glossary

- **ASR_Handler**: 语音识别处理模块，负责麦克风采集、VAD 检测、语音转写及唤醒词判断
- **XFYun_Client**: 讯飞在线语音听写 WebSocket 客户端，负责与讯飞服务端建立连接、发送音频帧、接收识别结果
- **VAD**: Voice Activity Detection，语音活动检测，用于判断音频中是否包含人声
- **PCM**: Pulse Code Modulation，脉冲编码调制，原始音频数据格式
- **Feed_Text**: ASR_Handler 中的文本入口方法，接收识别文本并进行唤醒词检测和指令分发

## Requirements

### Requirement 1: 移除 faster-whisper 本地模型依赖

**User Story:** As a developer, I want to remove the faster-whisper local model dependency, so that the system no longer requires GPU/CPU-intensive local inference and large model files.

#### Acceptance Criteria

1. THE ASR_Handler SHALL NOT import or reference the faster-whisper library
2. THE ASR_Handler SHALL NOT load any local Whisper model files
3. THE requirements.txt SHALL NOT include the faster-whisper package
4. THE config.py SHALL NOT contain Whisper-specific configuration items (WHISPER_MODEL, WHISPER_COMPUTE, WHISPER_DEVICE, WHISPER_BEAM_SIZE, WHISPER_BEST_OF, WHISPER_NO_SPEECH_THR)

### Requirement 2: 讯飞 WebSocket 鉴权连接

**User Story:** As a developer, I want the system to authenticate with iFlytek's WebSocket API using HMAC-SHA256 signatures, so that the ASR service can be accessed securely.

#### Acceptance Criteria

1. THE XFYun_Client SHALL construct the authentication URL using APPID, APIKey, and APISecret via HMAC-SHA256 signature
2. THE XFYun_Client SHALL connect to the endpoint wss://iat-api.xfyun.cn/v2/iat with the signed URL
3. WHEN the WebSocket connection is established, THE XFYun_Client SHALL send the first frame with common and business parameters including language and domain settings
4. IF the authentication fails, THEN THE XFYun_Client SHALL log the error and return an empty transcription result

### Requirement 3: 讯飞配置管理

**User Story:** As a developer, I want iFlytek credentials and parameters managed through environment variables, so that secrets are not hardcoded and configuration is flexible.

#### Acceptance Criteria

1. THE config.py SHALL define XFYUN_APPID, XFYUN_API_KEY, and XFYUN_API_SECRET configuration items with empty string defaults
2. THE config.py SHALL define XFYUN_LANGUAGE configuration item with default value "zh_cn"
3. THE config.py SHALL define XFYUN_DOMAIN configuration item with default value "iat" (普通话)
4. THE .env.example SHALL include XFYUN_APPID, XFYUN_API_KEY, and XFYUN_API_SECRET placeholder entries
5. IF any of XFYUN_APPID, XFYUN_API_KEY, or XFYUN_API_SECRET is empty, THEN THE ASR_Handler SHALL log a warning and skip transcription

### Requirement 4: 音频帧流式发送

**User Story:** As a developer, I want audio data sent to iFlytek in properly formatted frames, so that the streaming recognition works correctly.

#### Acceptance Criteria

1. WHEN a VAD speech segment is detected, THE XFYun_Client SHALL convert the audio from float32 to PCM 16-bit signed integer format
2. THE XFYun_Client SHALL split the PCM audio into frames of 1280 bytes (40ms at 16kHz 16-bit mono)
3. THE XFYun_Client SHALL send the first audio frame with status=0 (first frame), intermediate frames with status=1 (continue), and the last frame with status=2 (last frame)
4. THE XFYun_Client SHALL base64-encode each audio frame before sending
5. WHILE sending audio frames, THE XFYun_Client SHALL maintain a 40ms interval between consecutive frame transmissions

### Requirement 5: 识别结果接收与拼接

**User Story:** As a developer, I want to receive and assemble iFlytek's streaming recognition results into complete text, so that the downstream wake-word detection and AI processing work correctly.

#### Acceptance Criteria

1. WHEN the XFYun_Client receives a response message, THE XFYun_Client SHALL parse the JSON and extract the recognition result from data.result.ws[].cw[].w fields
2. THE XFYun_Client SHALL concatenate all word segments (w fields) in order to form the complete sentence
3. WHEN the response status is 2 (recognition complete), THE XFYun_Client SHALL close the WebSocket connection and return the final assembled text
4. IF the response contains a non-zero error code, THEN THE XFYun_Client SHALL log the error message and return an empty string

### Requirement 6: 保留 VAD 与麦克风采集逻辑

**User Story:** As a developer, I want the existing microphone capture and VAD logic preserved, so that the system continues to detect speech segments before sending them for recognition.

#### Acceptance Criteria

1. THE ASR_Handler SHALL retain the sounddevice-based microphone input stream with callback-driven frame capture
2. THE ASR_Handler SHALL retain the energy-threshold-based VAD logic including noise floor adaptation, silence frame counting, and minimum/maximum speech duration enforcement
3. THE ASR_Handler SHALL retain the pre-roll buffer for capturing speech onset
4. WHEN a valid speech segment is detected by VAD, THE ASR_Handler SHALL pass the audio to XFYun_Client for transcription instead of the local Whisper model
5. THE ASR_Handler SHALL resample audio to 16kHz mono before passing to XFYun_Client

### Requirement 7: 保留唤醒词检测与下游处理

**User Story:** As a developer, I want the wake-word detection and downstream AI processing chain preserved, so that the user experience remains unchanged after the ASR engine replacement.

#### Acceptance Criteria

1. THE ASR_Handler SHALL retain the feed_text method with wake-word regex matching logic
2. THE ASR_Handler SHALL retain the TTS echo suppression, duplicate detection, and mute-period filtering
3. WHEN XFYun_Client returns recognized text, THE ASR_Handler SHALL pass the text to feed_text for wake-word detection and command dispatch
4. THE ASR_Handler SHALL continue broadcasting ASR status updates (asr_step) via the WebSocket manager to the frontend

### Requirement 8: 错误处理与重试

**User Story:** As a developer, I want robust error handling for the online ASR service, so that transient network issues do not crash the system.

#### Acceptance Criteria

1. IF the WebSocket connection to iFlytek fails, THEN THE XFYun_Client SHALL log the error and return an empty transcription result without raising an exception
2. IF the WebSocket connection times out (exceeding 10 seconds without response), THEN THE XFYun_Client SHALL close the connection and return an empty string
3. WHEN a transcription attempt fails, THE ASR_Handler SHALL continue the mic_loop and attempt transcription on the next detected speech segment
4. THE ASR_Handler SHALL broadcast an "idle" status via WebSocket manager when transcription fails, to reset the frontend state

### Requirement 9: 依赖更新

**User Story:** As a developer, I want the project dependencies updated to reflect the new ASR engine, so that the project can be cleanly installed without unnecessary packages.

#### Acceptance Criteria

1. THE requirements.txt SHALL include the websockets package (already present) for WebSocket client functionality
2. THE requirements.txt SHALL NOT include the faster-whisper package
3. THE requirements.txt SHALL NOT introduce any new heavy dependencies beyond what is needed for WebSocket communication and HMAC signing (both available in Python standard library)
