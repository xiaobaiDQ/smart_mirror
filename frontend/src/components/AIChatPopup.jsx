/**
 * AIChatPopup.jsx
 * AI 问答弹窗 — 始终可见，状态实时切换：
 *  idle → listening → recognizing → thinking → answer
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useWebSocket } from './WebSocketService.js';

const STEP_LABEL = {
  idle:        { icon: '💤', text: '待命中，说"小镜小镜"唤醒' },
  listening:   { icon: '🎤', text: '我在听，请说' },
  recognizing: { icon: '📝', text: '语音识别中' },
  correcting:  { icon: '🔄', text: '语义纠错中' },
  thinking:    { icon: '🤔', text: 'AI 正在思考' },
};

export default function AIChatPopup() {
  // 'idle' | 'listening' | 'recognizing' | 'correcting' | 'thinking' | 'answer'
  const [state, setState] = useState('idle');
  const [question, setQuestion] = useState('');
  const [rawText, setRawText] = useState('');
  const [reply, setReply] = useState('');
  const [wakeFlash, setWakeFlash] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastWsMsg, setLastWsMsg] = useState('');

  const stateRef = useRef('idle');
  useEffect(() => { stateRef.current = state; }, [state]);

  const stuckTimer = useRef(null);
  const idleTimer = useRef(null);

  // 回到 idle 的定时器（回答后 15 秒回到待命）
  const scheduleIdle = useCallback(() => {
    clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => {
      setState('idle');
      setQuestion('');
      setReply('');
    }, 15000);
  }, []);

  // WebSocket 连接状态
  useWebSocket('open', useCallback(() => { setWsConnected(true); setLastWsMsg('WS connected'); }, []));
  useWebSocket('close', useCallback(() => { setWsConnected(false); setLastWsMsg('WS disconnected'); }, []));
  useWebSocket('hello', useCallback((d) => { setLastWsMsg('hello: ' + d.msg); }, []));
  useWebSocket('*', useCallback((d) => { setLastWsMsg(d.type + ': ' + JSON.stringify(d).slice(0, 80)); }, []));

  // ★ 管道步骤广播
  useWebSocket('asr_step', useCallback((d) => {
    const step = d.step;
    if (stateRef.current === 'thinking') return;
    if (step === 'recognizing') {
      setState('recognizing');
      clearTimeout(idleTimer.current);
      clearTimeout(stuckTimer.current);
      stuckTimer.current = setTimeout(() => {
        if (stateRef.current === 'recognizing') {
          setState('listening');
        }
      }, 10000);
    } else if (step === 'correcting') {
      setRawText(d.raw || '');
      setState('correcting');
      clearTimeout(idleTimer.current);
      clearTimeout(stuckTimer.current);
      stuckTimer.current = setTimeout(() => {
        if (stateRef.current === 'correcting') {
          setState('listening');
        }
      }, 10000);
    } else if (step === 'corrected') {
      clearTimeout(stuckTimer.current);
    } else if (step === 'idle') {
      setState('listening');
    }
  }, []));

  useWebSocket('wake', useCallback(() => {
    console.log('[AIChatPopup] WAKE received!');
    setWakeFlash(true);
    setTimeout(() => setWakeFlash(false), 1500);
    if (stateRef.current === 'thinking') return;
    clearTimeout(idleTimer.current);
    setQuestion('');
    setReply('');
    setRawText('');
    setState('listening');
  }, []));

  useWebSocket('ai_thinking', useCallback((d) => {
    clearTimeout(idleTimer.current);
    clearTimeout(stuckTimer.current);
    setQuestion(d.question || '');
    setReply('');
    setState('thinking');
  }, []));

  useWebSocket('ai_reply', useCallback((d) => {
    clearTimeout(stuckTimer.current);
    setQuestion(d.question || '');
    setReply(d.reply || '');
    setState('answer');
    scheduleIdle();
  }, [scheduleIdle]));

  // dismiss：用户说了关闭/再见
  useWebSocket('dismiss', useCallback(() => {
    clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => {
      setState('idle');
      setQuestion('');
      setReply('');
    }, 3000);
  }, []));

  useEffect(() => () => {
    clearTimeout(idleTimer.current);
    clearTimeout(stuckTimer.current);
  }, []);

  const step = STEP_LABEL[state];

  return (
    <>
      {wakeFlash && <div className="wake-flash neon-text">● 已唤醒</div>}

      {/* 弹窗始终可见 */}
      <div className="ai-popup show">
        <div className="ai-popup-inner glass">
          <div className="ai-head">
            <span className={`ai-dot ${wsConnected ? '' : 'disconnected'}`} />
            <span className="ai-title neon-text-soft">AI ASSISTANT</span>
            <span className="ai-status-badge">{state === 'idle' ? '待命' : state === 'listening' ? '聆听中' : state === 'answer' ? '已回答' : '处理中'}</span>
          </div>

          {/* 管道状态指示器（非 idle 和非 answer 时显示） */}
          {state !== 'idle' && state !== 'answer' && (
            <div className="ai-pipeline">
              {['listening', 'recognizing', 'correcting', 'thinking'].map((s, i) => (
                <span key={s} className={`pipe-step ${state === s ? 'active' : ''} ${
                  ['listening','recognizing','correcting','thinking'].indexOf(state) > i ? 'done' : ''
                }`}>
                  {STEP_LABEL[s].icon}
                </span>
              ))}
            </div>
          )}

          {/* 纠错中：显示原始文本 */}
          {state === 'correcting' && rawText && (
            <div className="ai-q ai-raw">原始识别：「{rawText}」</div>
          )}

          {/* 问题文本 */}
          {question && (state === 'thinking' || state === 'answer') && (
            <div className="ai-q">「{question}」</div>
          )}

          {/* 状态文本或回答 */}
          {state === 'answer' ? (
            <div className="ai-answer">{reply}</div>
          ) : (
            <div className="ai-thinking">
              <span className="thinking-text neon-text">{step?.text || ''}</span>
              {state !== 'idle' && <span className="dots"><i/><i/><i/></span>}
            </div>
          )}

          {/* 调试信息 */}
          <div style={{fontSize: '10px', color: '#666', marginTop: '8px', wordBreak: 'break-all'}}>
            WS: {wsConnected ? '✅' : '❌'} | State: {state} | Last: {lastWsMsg}
          </div>
        </div>
      </div>
    </>
  );
}
