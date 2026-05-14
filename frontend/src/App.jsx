/**
 * App.jsx
 * 顶层：连接 WebSocket，渲染屏保 + AI 弹窗 + 音乐控件 + 背景粒子。
 * 提供一个开发用输入框方便手动触发 AI（生产可移除）。
 */
import React, { useEffect, useState, useCallback } from 'react';
import ScreenSaver from './components/ScreenSaver.jsx';
import AIChatPopup from './components/AIChatPopup.jsx';
import MusicControl from './components/MusicControl.jsx';
import VoiceListener from './components/VoiceListener.jsx';
import wsService from './components/WebSocketService.js';
import { useWebSocket } from './components/WebSocketService.js';

export default function App() {
  const [devText, setDevText] = useState('');

  useEffect(() => {
    wsService.connect();
    // 调试：打印所有收到的 WS 消息
    const unsub = wsService.on('*', (data) => {
      console.log('[WS MSG]', data.type, data);
    });
    return unsub;
  }, []);

  // TTS: 通过 Web Speech API 朗读后端发来的文本
  useWebSocket('tts_speak', useCallback((d) => {
    if (!window.speechSynthesis) {
      console.warn('[TTS] Web Speech API not supported');
      return;
    }
    const utterance = new SpeechSynthesisUtterance(d.text);
    utterance.lang = 'zh-CN';
    const voices = speechSynthesis.getVoices();
    const zhVoice = voices.find(v => v.lang.startsWith('zh'));
    if (zhVoice) utterance.voice = zhVoice;
    speechSynthesis.speak(utterance);
  }, []));

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
