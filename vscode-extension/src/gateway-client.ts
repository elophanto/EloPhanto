/**
 * WebSocket client for the EloPhanto gateway.
 * Mirrors web/src/lib/gateway.ts but uses Node.js WebSocket (ws package).
 */

import WebSocket from "ws";
import {
  type GatewayMessage,
  MessageType,
  createStatusMessage,
} from "./protocol";

type MessageHandler = (msg: GatewayMessage) => void;

export class GatewayClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers = new Map<string, MessageHandler[]>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 20;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private outboundQueue: string[] = [];
  private _connected = false;
  private _disposed = false;

  constructor(url: string) {
    this.url = url;
  }

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    if (this._disposed) return;
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.on("open", () => {
        this._connected = true;
        this.reconnectAttempts = 0;
        this.startHeartbeat();
        this.flushQueue();
        this.dispatch({
          type: MessageType.STATUS,
          id: "",
          session_id: "",
          channel: "",
          user_id: "",
          data: { status: "connected" },
        });
      });

      this.ws.on("message", (raw: WebSocket.Data) => {
        try {
          const msg = JSON.parse(raw.toString()) as GatewayMessage;
          this.dispatch(msg);
        } catch {
          // Ignore malformed
        }
      });

      this.ws.on("close", () => {
        this._connected = false;
        this.stopHeartbeat();
        this.dispatch({
          type: MessageType.STATUS,
          id: "",
          session_id: "",
          channel: "",
          user_id: "",
          data: { status: "disconnected" },
        });
        if (!this._disposed) {
          this.scheduleReconnect();
        }
      });

      this.ws.on("error", () => {
        // onclose fires after this
      });
    } catch {
      if (!this._disposed) {
        this.scheduleReconnect();
      }
    }
  }

  disconnect(): void {
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.removeAllListeners();
      this.ws.close();
      this.ws = null;
    }
    this._connected = false;
    this.reconnectAttempts = 0;
  }

  dispose(): void {
    this._disposed = true;
    this.disconnect();
    this.handlers.clear();
  }

  on(type: string, handler: MessageHandler): () => void {
    const list = this.handlers.get(type) ?? [];
    list.push(handler);
    this.handlers.set(type, list);
    return () => {
      const idx = list.indexOf(handler);
      if (idx >= 0) list.splice(idx, 1);
    };
  }

  send(msg: GatewayMessage): void {
    const raw = JSON.stringify(msg);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(raw);
    } else {
      this.outboundQueue.push(raw);
    }
  }

  private dispatch(msg: GatewayMessage): void {
    const handlers = this.handlers.get(msg.type);
    if (handlers) {
      for (const h of handlers) {
        try {
          h(msg);
        } catch {
          // Don't break dispatch
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

    this.reconnectAttempts++;
    const delay = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts - 1),
      30000
    );
    const jitter = Math.random() * 500;

    this.dispatch({
      type: MessageType.STATUS,
      id: "",
      session_id: "",
      channel: "",
      user_id: "",
      data: { status: "reconnecting" },
    });

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay + jitter);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(createStatusMessage()));
      }
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private flushQueue(): void {
    while (this.outboundQueue.length > 0) {
      const raw = this.outboundQueue.shift()!;
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(raw);
      }
    }
  }
}
