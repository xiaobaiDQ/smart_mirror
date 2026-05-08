/**
 * VoiceListener.jsx
 * -----------------
 * 浏览器端语音监听（Web Speech API）。
 *
 * 工作流:
 *  - 点击🎤按钮 → 申请麦克风权限 → 持续识别中文
 *  - 每段识别结果通过 POST /api/asr/text 发到后端
 *  - 后端 asr_handler 判断唤醒词、转发 AI
 *  - Chrome / Edge 才支持 webkitSpeechRecognition；不支持时按钮禁用
 */
import React, { useEffect, useRef, useState } from 'react';

const SR =
  typeof window !== 'undefined'
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

export default function VoiceListener() {
  const [supported] = useState(Boolean(SR));
  const [listening, setListening] = useState(false);
  const [lastText, setLastText] = useState('');
  const [interim, setInterim] = useState('');
  const [error, setError] = useState('');
  const recRef = useRef(null);
  const wantRef = useRef(false); // 用户是否希望持续监听

  useEffect(() => {
    if (!supported) return;
    const rec = new SR();
    rec.lang = 'zh-CN';
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (ev) => {
      let interimText = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        const text = (res[0].transcript || '').trim();
        if (!text) continue;
        if (res.isFinal) {
          console.log('[VoiceListener] final:', text);
          setLastText(text);
          setInterim('');
          fetch('/api/asr/text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
          }).catch(() => {});
        } else {
          interimText += text;
        }
      }
      if (interimText) setInterim(interimText);
    };
    rec.onerror = (e) => {
      console.warn('[VoiceListener] error:', e.error);
      setError(e.error || 'unknown');
    };
    rec.onend = () => {
      console.log('[VoiceListener] onend, want=', wantRef.current);
      if (wantRef.current) {
        // 延迟一点点再重启，避免 Chrome 状态混乱
        setTimeout(() => {
          try { rec.start(); } catch (err) {
            console.warn('restart failed', err);
            setListening(false);
            wantRef.current = false;
          }
        }, 200);
      } else {
        setListening(false);
      }
    };

    recRef.current = rec;
    return () => {
      wantRef.current = false;
      try { rec.stop(); } catch (_) {}
    };
  }, [supported]);

  const toggle = () => {
    const rec = recRef.current;
    if (!rec) return;
    if (listening) {
      wantRef.current = false;
      try { rec.stop(); } catch (_) {}
      setListening(false);
    } else {
      setError('');
      wantRef.current = true;
      try { rec.start(); setListening(true); }
      catch (e) { setError(String(e)); }
    }
  };

  return (
    <div className={`voice-listener ${listening ? 'on' : ''}`}>
      <button
        className="btn-neon mic-btn"
        onClick={toggle}
        disabled={!supported}
        title={supported ? (listening ? '点击停止监听' : '点击开始监听') : '当前浏览器不支持 Web Speech API'}
      >
        {listening ? '🎤 LISTENING' : supported ? '🎤 START' : '🎤 N/A'}
      </button>
      {interim && <div className="voice-interim">… {interim}</div>}
      {lastText && <div className="voice-last">「{lastText}」</div>}
      {error && <div className="voice-err">{error}</div>}
    </div>
  );
}
