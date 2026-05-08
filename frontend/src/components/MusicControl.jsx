/**
 * MusicControl.jsx
 * 底部音乐控制条：显示当前歌曲 + 播放/暂停/下一首按钮。
 * 通过 <audio> 元素播放网易云音乐 API 返回的直链 URL。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import wsService, { useWebSocket } from './WebSocketService.js';

// 全局音频解锁：浏览器自动播放策略要求至少一次用户手势
let audioUnlocked = false;
const unlockAudio = () => {
  if (audioUnlocked) return;
  audioUnlocked = true;
  // 用一个静默播放来解锁 AudioContext
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  ctx.resume().then(() => ctx.close());
};
// 任何交互都解锁
['click', 'touchstart', 'keydown'].forEach(e =>
  document.addEventListener(e, unlockAudio, { once: true })
);

export default function MusicControl() {
  const audioRef = useRef(null);
  const [track, setTrack] = useState({
    title: '', artist: '', url: '', cover: '', playing: false,
  });
  const [blocked, setBlocked] = useState(false);

  useWebSocket('music_state', useCallback((d) => {
    setTrack((t) => ({ ...t, ...d }));
  }, []));

  useWebSocket('music_control', useCallback((d) => {
    setTrack((t) => ({ ...t, ...d, playing: d.action === 'play' ? true : d.action === 'pause' ? false : t.playing }));
  }, []));

  // 切歌时强制加载新音频
  const lastUrlRef = useRef('');
  const retryTimer = useRef(null);

  // 网易云返回 http 链接，浏览器混合内容可能阻止，转 https
  const fixUrl = (url) => url ? url.replace(/^http:\/\//, 'https://') : '';

  const tryPlay = useCallback(() => {
    const a = audioRef.current;
    if (!a || !a.src) return;
    const p = a.play();
    if (p && p.catch) {
      p.catch((err) => {
        console.warn('play blocked:', err.name, err.message);
        if (err.name === 'NotAllowedError') {
          setBlocked(true);
          clearTimeout(retryTimer.current);
          retryTimer.current = setTimeout(() => {
            if (audioUnlocked) tryPlay();
          }, 1000);
        }
      });
      p.then(() => setBlocked(false)).catch(() => {});
    }
  }, []);

  // 监听 audio 错误和加载完成
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onError = () => {
      const e = a.error;
      console.error('audio error:', e?.code, e?.message, 'src:', a.src?.slice(0, 80));
    };
    const onCanPlay = () => {
      console.log('audio canplay, playing:', track.playing);
      if (track.playing) tryPlay();
    };
    a.addEventListener('error', onError);
    a.addEventListener('canplay', onCanPlay);
    return () => {
      a.removeEventListener('error', onError);
      a.removeEventListener('canplay', onCanPlay);
    };
  }, [track.playing, tryPlay]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const url = fixUrl(track.url);
    if (url && url !== lastUrlRef.current) {
      lastUrlRef.current = url;
      a.src = url;
      a.load();
      setBlocked(false);
      // 不在这里 play，等 canplay 事件触发后再播放
    } else if (!url) {
      lastUrlRef.current = '';
      a.pause();
      a.removeAttribute('src');
      setBlocked(false);
    } else if (track.playing) {
      tryPlay();
    } else {
      a.pause();
    }
  }, [track.url, track.playing, tryPlay]);

  const toggle = () => {
    // 用户点击 = 手势解锁
    unlockAudio();
    if (blocked) {
      // 直接播放（此时有用户手势）
      const a = audioRef.current;
      if (a && a.src) {
        a.play().then(() => setBlocked(false)).catch(() => {});
      }
      return;
    }
    wsService.send({ type: 'music_control', action: track.playing ? 'pause' : 'play' });
  };
  const next = () => wsService.send({ type: 'music_control', action: 'next' });

  const hasTrack = Boolean(track.title || track.url);

  return (
    <div className={`music-bar glass ${hasTrack ? '' : 'dim'}`}>
      <audio ref={audioRef} preload="auto" />
      <div className="cover">
        {track.cover ? <img src={track.cover} alt="" /> : <div className="cover-ph" />}
      </div>
      <div className="info">
        <div className="title neon-text-soft">{track.title || '未在播放'}</div>
        <div className="artist">{track.artist || '—'}</div>
      </div>
      <div className="controls">
        <button className="btn-neon" onClick={toggle} disabled={!hasTrack}>
          {blocked ? '▶ 点击播放' : track.playing ? '❚❚' : '▶'}
        </button>
        <button className="btn-neon" onClick={next} disabled={!hasTrack}>⏭</button>
      </div>
    </div>
  );
}
