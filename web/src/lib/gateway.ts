/**
 * WebSocket connection manager — singleton.
 * Follows the same connect/dispatch/send pattern as channels/base.py ChannelAdapter.
 */

import {
  type GatewayMessage,
  MessageType,
  createChatMessage,
  createApprovalResponse,
  createCommandMessage,
  createStatusMessage,
} from "./protocol";

type MessageHandler = (msg: GatewayMessage) => void;

class GatewayConnection {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers = new Map<string, MessageHandler[]>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 20;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private outboundQueue: string[] = [];

  constructor(url: string = "ws://127.0.0.1:18789") {
    this.url = url;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => this.onOpen();
      this.ws.onmessage = (e) => this.onMessage(e);
      this.ws.onclose = (e) => this.onClose(e);
      this.ws.onerror = () => this.onError();
    } catch {
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.reconnectAttempts = 0;
  }

  /** Register a handler for a message type. Returns unsubscribe function. */
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

  sendChat(content: string, sessionId: string = ""): string {
    const msg = createChatMessage(content, sessionId);
    this.send(msg);
    return msg.id;
  }

  sendApproval(requestId: string, approved: boolean): void {
    this.send(createApprovalResponse(requestId, approved));
  }

  sendCommand(command: string, args?: Record<string, unknown>): void {
    this.send(createCommandMessage(command, args));
  }

  // ── Internal ──

  private onOpen(): void {
    this.reconnectAttempts = 0;
    this.startHeartbeat();
    this.flushQueue();
  }

  private onMessage(event: MessageEvent): void {
    try {
      const msg = JSON.parse(event.data as string) as GatewayMessage;
      this.dispatch(msg);
    } catch {
      // Ignore malformed messages
    }
  }

  private onClose(_event: CloseEvent): void {
    this.stopHeartbeat();
    this.dispatch({
      type: MessageType.STATUS,
      id: "",
      session_id: "",
      channel: "",
      user_id: "",
      data: { status: "disconnected" },
    });
    this.scheduleReconnect();
  }

  private onError(): void {
    // onClose will fire after this
  }

  private dispatch(msg: GatewayMessage): void {
    const handlers = this.handlers.get(msg.type);
    if (handlers) {
      for (const h of handlers) {
        try {
          h(msg);
        } catch {
          // Don't let handler errors break dispatch
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);
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

export const gateway = new GatewayConnection();
