/**
 * ScreenSaver.jsx
 * 屏保：大字号时间 + 日期 + 天气信息。
 * 科幻风：深色背景、霓虹边框、扫描线、粒子。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useWebSocket } from './WebSocketService.js';

const weekMap = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

export default function ScreenSaver() {
  const [now, setNow] = useState(new Date());
  const [weather, setWeather] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // 首次加载主动拉一次，避免错过 WebSocket 周期广播
  useEffect(() => {
    fetch('/api/weather')
      .then((r) => r.json())
      .then((d) => setWeather(d))
      .catch(() => {});
  }, []);

  useWebSocket('weather', useCallback((d) => setWeather(d), []));

  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${weekMap[now.getDay()]}`;

  return (
    <div className="screensaver">
      <div className="scanline" />
      <div className="hud-corner tl" />
      <div className="hud-corner tr" />
      <div className="hud-corner bl" />
      <div className="hud-corner br" />

      <div className="clock neon-text">
        <span>{hh}</span>
        <span className="colon">:</span>
        <span>{mm}</span>
        <span className="seconds">{ss}</span>
      </div>
      <div className="date neon-text-soft">{dateStr}</div>

      <div className="weather-card glass">
        {weather ? (
          <>
            <div className="w-city">{weather.city || '—'}</div>
            <div className="w-main">
              <span className="w-temp">{weather.temperature || '--'}°</span>
              <span className="w-desc">{weather.weather || '—'}</span>
            </div>
            <div className="w-sub">
              湿度 {weather.humidity || '-'}% · 风 {weather.winddirection || '-'} {weather.windpower || '-'}
            </div>
          </>
        ) : (
          <div className="w-loading">Loading weather…</div>
        )}
      </div>
    </div>
  );
}
