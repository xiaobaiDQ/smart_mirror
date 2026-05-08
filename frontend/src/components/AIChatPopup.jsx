/**
 * AIChatPopup.jsx
 * AI 问答弹窗 — 全流程状态展示：
 *  listening → recognizing → correcting → thinking → answer
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useWebSocket } from './WebSocketService.js';

const AUTO_CLOSE_MS = 25000;

const STEP_LABEL = {
  listening:   { icon: '🎤', text: '我在听，请说' },
  recognizing: { icon: '📝', text: '语音识别中' },
  correcting:  { icon: '🔄', text: '语义纠错中' },
  thinking:    { icon: '🤔', text: 'AI 正在思考' },
};

export default function AIChatPopup() {
  const [visible, setVisible] = useState(false);
  // 'listening' | 'recognizing' | 'correcting' | 'thinking' | 'answer'
  const [state, setState] = useState('idle');
  const [question, setQuestion] = useState('');
  const [rawText, setRawText] = useState('');
  const [reply, setReply] = useState('');
  const [wakeFlash, setWakeFlash] = useState(false);
  const closeTimer = useRef(null);

  const scheduleClose = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setVisible(false), AUTO_CLOSE_MS);
  }, []);

  const stateRef = useRef('idle');
  useEffect(() => { stateRef.current = state; }, [state]);

  const stuckTimer = useRef(null);

  // ★ 管道步骤广播
  useWebSocket('asr_step', useCallback((d) => {
    const step = d.step;
    // 思考中不打断
    if (stateRef.current === 'thinking') return;
    if (step === 'recognizing') {
      setState('recognizing');
      setVisible(true);
      clearTimeout(closeTimer.current);
      // 10秒兜底：识别超时自动恢复
      clearTimeout(stuckTimer.current);
      stuckTimer.current = setTimeout(() => {
        if (stateRef.current === 'recognizing') {
          setState('listening');
          scheduleClose();
        }
      }, 10000);
    } else if (step === 'correcting') {
      setRawText(d.raw || '');
      setState('correcting');
      setVisible(true);
      clearTimeout(closeTimer.current);
      // 10秒兜底：纠错超时自动恢复
      clearTimeout(stuckTimer.current);
      stuckTimer.current = setTimeout(() => {
        if (stateRef.current === 'correcting') {
          setState('listening');
          scheduleClose();
        }
      }, 10000);
    } else if (step === 'corrected') {
      clearTimeout(stuckTimer.current);
    } else if (step === 'idle') {
      // Whisper 没识别出文本，恢复空闲
      setState('listening');
      scheduleClose();
    }
  }, [scheduleClose]));

  useWebSocket('wake', useCallback(() => {
    setWakeFlash(true);
    setTimeout(() => setWakeFlash(false), 1500);
    if (stateRef.current === 'thinking') return;
    clearTimeout(closeTimer.current);
    setQuestion('');
    setReply('');
    setRawText('');
    setState('listening');
    setVisible(true);
    scheduleClose();
  }, [scheduleClose]));

  useWebSocket('ai_thinking', useCallback((d) => {
    clearTimeout(closeTimer.current);
    clearTimeout(stuckTimer.current);
    setQuestion(d.question || '');
    setReply('');
    setState('thinking');
    setVisible(true);
  }, []));

  useWebSocket('ai_reply', useCallback((d) => {
    clearTimeout(stuckTimer.current);
    setQuestion(d.question || '');
    setReply(d.reply || '');
    setState('answer');
    setVisible(true);
    scheduleClose();
  }, [scheduleClose]));

  // dismiss：用户说了关闭/再见，短暂展示告别语后关闭
  useWebSocket('dismiss', useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      setVisible(false);
      setState('idle');
    }, 3000);
  }, []));

  useEffect(() => () => { clearTimeout(closeTimer.current); clearTimeout(stuckTimer.current); }, []);

  const step = STEP_LABEL[state];

  return (
    <>
      {wakeFlash && <div className="wake-flash neon-text">● 已唤醒</div>}

      <div className={`ai-popup ${visible ? 'show' : ''}`}>
        <div className="ai-popup-inner glass">
          <div className="ai-particles">
            {Array.from({ length: 18 }).map((_, i) => (
              <span key={i} style={{ '--i': i }} />
            ))}
          </div>

          <div className="ai-head">
            <span className="ai-dot" />
            <span className="ai-title neon-text-soft">AI ASSISTANT</span>
          </div>

          {/* 管道状态指示器 */}
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

          {/* 问题文本（纠正后 / AI thinking 阶段） */}
          {question && (state === 'thinking' || state === 'answer') && (
            <div className="ai-q">「{question}」</div>
          )}

          {step ? (
            <div className="ai-thinking">
              <span className="thinking-text neon-text">{step.text}</span>
              <span className="dots"><i/><i/><i/></span>
            </div>
          ) : (
            <div className="ai-answer">{reply}</div>
          )}
        </div>
      </div>
    </>
  );
}
