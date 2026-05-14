/**
 * WebSocketService.js
 * -------------------
 * 单例封装前端与 FastAPI 的 WebSocket 连接。
 */
import { useEffect } from 'react';

class WSService {
  constructor() {
    this.ws = null;
    this.listeners = new Map();
    this.retry = 0;
    this.url = '';
    this.queue = [];
    this._connectTime = 0;
    this._heartbeatId = null;
  }

  _buildUrl() {
    if (typeof window === 'undefined') return '';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.hostname || 'localhost';
    return `${proto}://${host}:8002/ws`;
  }

  connect() {
    // 每次 connect 时重新构建 URL（防止模块初始化时 window 未就绪）
    this.url = this._buildUrl();
    if (!this.url) {
      console.warn('[WS] no URL, skipping connect');
      return;
    }

    console.log('[WS] attempting connect to', this.url);

    // 清理旧连接
    if (this.ws) {
      if (this.ws.readyState === 1) {
        console.log('[WS] already connected');
        return;
      }
      if (this.ws.readyState === 0) {
        if (this._connectTime && Date.now() - this._connectTime < 5000) return;
        try { this.ws.close(); } catch {}
      }
    }

    this._connectTime = Date.now();
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      console.error('[WS] new WebSocket failed:', e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.retry = 0;
      console.log('[WS] ✅ connected to', this.url);
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
      console.log('[WS] closed');
      this._emit('close', {});
      this._scheduleReconnect();
    };

    this.ws.onerror = (e) => {
      console.error('[WS] error:', e);
      try { this.ws.close(); } catch {}
    };

    // 启动心跳（只启动一次）
    if (!this._heartbeatId) {
      this._heartbeatId = setInterval(() => {
        if (!this.ws || this.ws.readyState > 1) {
          this.retry = 0;
          this.connect();
        }
      }, 10000);
    }
  }

  _scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this.retry++, 10000);
    console.log(`[WS] reconnecting in ${delay}ms (attempt ${this.retry})`);
    setTimeout(() => this.connect(), delay);
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
      try { h(data); } catch (e) { console.error('[WS] handler error:', e); }
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
