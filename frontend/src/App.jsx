/**
 * App.jsx
 * 顶层：连接 WebSocket，渲染屏保 + AI 弹窗 + 音乐控件 + 背景粒子。
 * 提供一个开发用输入框方便手动触发 AI（生产可移除）。
 */
import React, { useEffect, useState } from 'react';
import ScreenSaver from './components/ScreenSaver.jsx';
import AIChatPopup from './components/AIChatPopup.jsx';
import MusicControl from './components/MusicControl.jsx';
import VoiceListener from './components/VoiceListener.jsx';
import wsService from './components/WebSocketService.js';

export default function App() {
  const [devText, setDevText] = useState('');

  useEffect(() => {
    wsService.connect();
  }, []);

  const sendDev = (e) => {
    e.preventDefault();
    if (!devText.trim()) return;
    // 走 ASR 文本通道 (等价唤醒后提问)
    fetch('/api/asr/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: `小镜小镜 ${devText}` }),
    });
    setDevText('');
  };

  return (
    <div className="app">
      <div className="bg-grid" />
      <div className="bg-particles">
        {Array.from({ length: 40 }).map((_, i) => (
          <span key={i} style={{ '--i': i, '--r': Math.random() }} />
        ))}
      </div>

      <ScreenSaver />
      <AIChatPopup />
      <MusicControl />
      {/* VoiceListener 已弃用，改为后端本地 Whisper 采集；保留组件文件以备调试 */}
      {/* <VoiceListener /> */}

      <form className="dev-input" onSubmit={sendDev}>
        <input
          value={devText}
          onChange={(e) => setDevText(e.target.value)}
          placeholder="DEV: 输入提问 (前加唤醒词由代码自动补)"
        />
        <button className="btn-neon" type="submit">发送</button>
      </form>
    </div>
  );
}
