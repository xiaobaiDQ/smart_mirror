/**
 * WebSocketService.js
 * -------------------
 * 单例封装前端与 FastAPI 的 WebSocket 连接。
 *
 * 功能：
 *  - 自动重连（指数退避）
 *  - 基于消息 type 的订阅分发
 *  - React 组件通过 useWebSocket(type, handler) hook 订阅
 */
import { useEffect } from 'react';

class WSService {
  constructor() {
    this.ws = null;
    this.listeners = new Map(); // type -> Set<handler>
    this.retry = 0;
    this.url = this._buildUrl();
    this.queue = [];
    this._connectTime = 0;
    this._startHeartbeat();
  }

  _buildUrl() {
    if (typeof window === 'undefined') return '';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    // 直连后端 WS，避免 Vite 代理在后端重载时报 socket ended 错误
    const host = window.location.hostname;
    return `${proto}://${host}:8002/ws`;
  }

  connect() {
    // 清理僵死连接
    if (this.ws) {
      if (this.ws.readyState === 1) return; // OPEN - 已连接
      if (this.ws.readyState === 0) {
        // CONNECTING 超过 5 秒视为僵死
        if (this._connectTime && Date.now() - this._connectTime < 5000) return;
        try { this.ws.close(); } catch {}
      }
    }
    this._connectTime = Date.now();
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retry = 0;
      console.log('[WS] connected to', this.url);
      // flush queue
      while (this.queue.length) this.ws.send(this.queue.shift());
      this._emit('open', {});
    };
    this.ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      const t = data.type || 'message';
      this._emit(t, data);
      this._emit('*', data);
    };
    this.ws.onclose = () => {
      this._emit('close', {});
      this._scheduleReconnect();
    };
    this.ws.onerror = () => { try { this.ws.close(); } catch {} };
  }

  _scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this.retry++, 10000);
    console.log(`[WS] reconnecting in ${delay}ms (attempt ${this.retry})`);
    setTimeout(() => this.connect(), delay);
  }

  // 每 20 秒检查连接状态，断了就重连
  _startHeartbeat() {
    setInterval(() => {
      if (!this.ws || this.ws.readyState > 1) {
        this.retry = 0;
        this.connect();
      }
    }, 20000);
  }

  send(obj) {
    const data = JSON.stringify(obj);
    if (this.ws && this.ws.readyState === 1) this.ws.send(data);
    else this.queue.push(data);
  }

  on(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(handler);
    return () => this.off(type, handler);
  }

  off(type, handler) {
    this.listeners.get(type)?.delete(handler);
  }

  _emit(type, data) {
    this.listeners.get(type)?.forEach((h) => {
      try { h(data); } catch (e) { console.error(e); }
    });
  }
}

const wsService = new WSService();
export default wsService;

/** React hook：订阅某类消息 */
export function useWebSocket(type, handler) {
  useEffect(() => {
    const unsub = wsService.on(type, handler);
    return unsub;
  }, [type, handler]);
}
