/**
 * Chat sidebar webview provider — renders the chat panel in the activity bar.
 */

import * as vscode from "vscode";
import type { GatewayClient } from "./gateway-client";
import {
  type GatewayMessage,
  MessageType,
  EventType,
  createChatMessage,
  createCommandMessage,
} from "./protocol";
import { collectIdeContext } from "./context";

export class ChatProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "elophanto.chat";
  private view?: vscode.WebviewView;
  private client: GatewayClient;
  private config: vscode.WorkspaceConfiguration;

  constructor(
    private readonly extensionUri: vscode.Uri,
    client: GatewayClient
  ) {
    this.client = client;
    this.config = vscode.workspace.getConfiguration("elophanto");
    this.setupGatewayHandlers();
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtml();

    webviewView.webview.onDidReceiveMessage((msg) => {
      switch (msg.type) {
        case "send":
          this.sendMessage(msg.content);
          break;
        case "stop":
          this.client.send(createCommandMessage("stop"));
          break;
        case "new-chat":
          // UI-only clear — does NOT wipe agent memory
          break;
        case "load-conversations":
          this.client.send(createCommandMessage("conversations"));
          break;
        case "switch-conversation":
          this.client.send(
            createCommandMessage("chat_history", {
              conversation_id: msg.conversationId,
            })
          );
          break;
        case "close-panel":
          vscode.commands.executeCommand("workbench.action.closeSidebar");
          break;
      }
    });

    // Send initial connection status
    this.postToWebview({
      type: "status",
      connected: this.client.connected,
    });
  }

  sendMessage(content: string, showInChat = false): void {
    const ideContext = collectIdeContext();
    const msg = createChatMessage(content, ideContext);
    this.client.send(msg);
    // Only post user-message for external triggers (sendSelection, explain, fix)
    // The chat input renders immediately in the webview's send() function
    if (showInChat) {
      this.postToWebview({ type: "user-message", content, id: msg.id });
    }
  }

  newChat(): void {
    this.postToWebview({ type: "new-chat" });
  }

  private setupGatewayHandlers(): void {
    // Agent responses (may also be command results like conversations list)
    this.client.on(MessageType.RESPONSE, (msg: GatewayMessage) => {
      // Command responses come as JSON strings in content — try to detect them
      const content = msg.data.content as string;
      if (content && msg.data.done) {
        try {
          const parsed = JSON.parse(content);
          if (parsed.conversations) {
            this.postToWebview({
              type: "conversations",
              conversations: parsed.conversations,
            });
            return;
          }
          if (parsed.chat_history) {
            this.postToWebview({
              type: "chat-history",
              messages: parsed.chat_history.messages,
            });
            return;
          }
        } catch {
          // Not JSON — regular text response, fall through
        }
      }
      this.postToWebview({
        type: "response",
        content,
        done: msg.data.done as boolean,
        replyTo: msg.data.reply_to as string,
      });
    });

    // Events
    this.client.on(MessageType.EVENT, (msg: GatewayMessage) => {
      const event = msg.data.event as string;
      const showMind = this.config.get<boolean>("showMindEvents", true);
      const showTools = this.config.get<boolean>("showToolSteps", true);

      if (event === EventType.STEP_PROGRESS && showTools) {
        this.postToWebview({
          type: "tool-step",
          step: msg.data.step,
          toolName: msg.data.tool_name,
          thought: msg.data.thought,
        });
      } else if (event.startsWith("mind_") && showMind) {
        this.postToWebview({
          type: "mind-event",
          event,
          data: msg.data,
        });
      } else if (
        event === EventType.GOAL_STARTED ||
        event === EventType.GOAL_COMPLETED
      ) {
        this.postToWebview({
          type: "goal-event",
          event,
          data: msg.data,
        });
      }
    });

    // Connection status
    this.client.on(MessageType.STATUS, (msg: GatewayMessage) => {
      const status = msg.data.status as string;
      if (
        status === "connected" ||
        status === "disconnected" ||
        status === "reconnecting"
      ) {
        this.postToWebview({
          type: "status",
          connected: status === "connected",
          reconnecting: status === "reconnecting",
        });
      }
    });

    // Errors
    this.client.on(MessageType.ERROR, (msg: GatewayMessage) => {
      this.postToWebview({
        type: "error",
        detail: msg.data.detail as string,
      });
    });
  }

  private postToWebview(msg: Record<string, unknown>): void {
    this.view?.webview.postMessage(msg);
  }

  private getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  :root {
    --mono: var(--vscode-editor-font-family, 'SF Mono', 'Fira Code', 'Consolas', monospace);
    --radius: 4px;
    --border: var(--vscode-widget-border, var(--vscode-editorWidget-border, rgba(128,128,128,0.15)));
    --muted: var(--vscode-descriptionForeground);
    --surface: var(--vscode-editor-background);
    --sidebar-bg: var(--vscode-sideBar-background);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--vscode-font-family);
    font-size: 13px;
    color: var(--vscode-foreground);
    background: var(--sidebar-bg);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* ── Toolbar ── */
  #toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    flex-shrink: 0;
  }
  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .toolbar-btn {
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    padding: 3px;
    border-radius: 3px;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.6;
    transition: opacity 0.15s, background 0.15s;
  }
  .toolbar-btn:hover {
    opacity: 1;
    background: rgba(128,128,128,0.15);
  }
  .toolbar-btn svg {
    width: 14px; height: 14px;
    fill: currentColor;
  }
  #stop-btn { color: var(--vscode-errorForeground, #f85149); }
  #stop-btn:hover { opacity: 1; }

  #toolbar .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--muted);
    flex-shrink: 0;
  }
  #toolbar.connected .dot {
    background: #3fb950;
    box-shadow: 0 0 6px rgba(63,185,80,0.4);
    animation: pulse-dot 2s ease-in-out infinite;
  }
  #toolbar.disconnected .dot {
    background: #d29922;
    animation: pulse-dot 1s ease-in-out infinite;
  }

  /* ── Conversation list ── */
  #conversation-list {
    display: none;
    flex-direction: column;
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    gap: 2px;
  }
  #conversation-list.active { display: flex; }
  .conv-item {
    padding: 8px 10px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 12px;
    line-height: 1.4;
    color: var(--vscode-foreground);
    transition: background 0.1s;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .conv-item:hover { background: rgba(128,128,128,0.1); }
  .conv-item .conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conv-item .conv-meta {
    font-family: var(--mono);
    font-size: 9px;
    color: var(--muted);
    opacity: 0.5;
    flex-shrink: 0;
    margin-left: 8px;
  }

  /* ── Messages ── */
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    scroll-behavior: smooth;
  }

  .msg-wrapper {
    display: flex;
    flex-direction: column;
    gap: 3px;
    animation: msg-enter 0.2s ease-out;
  }
  .msg-wrapper.right { align-items: flex-end; }
  .msg-wrapper.left { align-items: flex-start; }
  .msg-wrapper.center { align-items: center; }

  @keyframes msg-enter {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .msg-label {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    opacity: 0.6;
    padding: 0 4px;
  }

  .msg {
    padding: 10px 14px;
    border-radius: var(--radius);
    max-width: 90%;
    word-wrap: break-word;
    white-space: pre-wrap;
    line-height: 1.6;
    font-size: 13px;
    position: relative;
  }

  .msg.user {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border-radius: var(--radius) var(--radius) 1px var(--radius);
  }

  .msg.agent {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius) var(--radius) var(--radius) 1px;
  }
  .msg.agent.complete::before,
  .msg.agent.complete::after {
    content: '';
    position: absolute;
    width: 8px; height: 8px;
    opacity: 0.2;
  }
  .msg.agent.complete::before {
    top: -1px; left: -1px;
    border-top: 1.5px solid var(--vscode-foreground);
    border-left: 1.5px solid var(--vscode-foreground);
  }
  .msg.agent.complete::after {
    bottom: -1px; right: -1px;
    border-bottom: 1.5px solid var(--vscode-foreground);
    border-right: 1.5px solid var(--vscode-foreground);
  }

  .msg.agent.streaming::after {
    content: '';
    display: inline-block;
    width: 2px; height: 14px;
    background: var(--vscode-foreground);
    margin-left: 2px;
    vertical-align: text-bottom;
    animation: blink-cursor 0.8s step-end infinite;
    position: static;
    border: none;
    opacity: 1;
  }

  @keyframes blink-cursor {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }

  .msg.system {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    color: var(--muted);
    opacity: 0.7;
    padding: 4px 8px;
    background: none;
    border: none;
  }

  .msg.error {
    background: rgba(200,50,50,0.08);
    border: 1px solid rgba(200,50,50,0.3);
    border-radius: var(--radius);
    color: var(--vscode-errorForeground, #f85149);
    font-size: 12px;
  }

  /* ── Tool steps ── */
  .tool-step {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    padding: 3px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    animation: msg-enter 0.15s ease-out;
  }
  .tool-step .spinner {
    width: 10px; height: 10px;
    border: 1.5px solid transparent;
    border-top-color: var(--vscode-textLink-foreground);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    flex-shrink: 0;
  }
  .tool-step .tool-name {
    color: var(--vscode-textLink-foreground);
    font-weight: 600;
    letter-spacing: 0.04em;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Thinking ── */
  .thinking {
    display: none;
    padding: 6px 14px;
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    color: var(--muted);
    opacity: 0.6;
    align-items: center;
    gap: 8px;
  }
  .thinking.active {
    display: flex;
    animation: msg-enter 0.2s ease-out;
  }
  .thinking .dots::after {
    content: '';
    animation: thinking-dots 1.4s steps(4, end) infinite;
  }
  @keyframes thinking-dots {
    0% { content: ''; }
    25% { content: '.'; }
    50% { content: '..'; }
    75% { content: '...'; }
  }

  /* ── Input area ── */
  #input-area {
    border-top: 1px solid var(--border);
    padding: 10px 12px;
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--sidebar-bg);
    transition: border-color 0.2s;
  }
  #input-area.focused { border-top-color: var(--vscode-focusBorder); }

  #input {
    flex: 1;
    background: var(--surface);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
    font-family: var(--vscode-font-family);
    font-size: 13px;
    line-height: 1.5;
    resize: none;
    min-height: 38px;
    max-height: 140px;
    outline: none;
    transition: border-color 0.2s;
  }
  #input:focus { border-color: var(--vscode-focusBorder); }
  #input::placeholder { color: var(--muted); opacity: 0.5; }
  #input:disabled { opacity: 0.4; }

  #send-btn {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: var(--radius);
    width: 32px; height: 32px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: background 0.15s, opacity 0.15s;
  }
  #send-btn:hover { background: var(--vscode-button-hoverBackground); }
  #send-btn:disabled { opacity: 0.3; cursor: not-allowed; }
  #send-btn svg { width: 16px; height: 16px; fill: currentColor; }

  /* ── Empty state ── */
  .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    opacity: 0.3;
    padding: 24px;
  }
  .empty-state .logo { font-size: 28px; margin-bottom: 4px; }
  .empty-state .label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }

  /* ── Scrollbar ── */
  #messages::-webkit-scrollbar, #conversation-list::-webkit-scrollbar { width: 4px; }
  #messages::-webkit-scrollbar-track, #conversation-list::-webkit-scrollbar-track { background: transparent; }
  #messages::-webkit-scrollbar-thumb, #conversation-list::-webkit-scrollbar-thumb {
    background: var(--vscode-scrollbarSlider-background);
    border-radius: 2px;
  }

  /* ── Markdown ── */
  .msg code {
    background: var(--vscode-textCodeBlock-background);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: var(--mono);
    font-size: 0.92em;
  }
  .msg pre {
    background: var(--vscode-textCodeBlock-background);
    padding: 10px 12px;
    border-radius: var(--radius);
    overflow-x: auto;
    margin: 6px 0;
    border: 1px solid var(--border);
  }
  .msg pre code { background: none; padding: 0; font-size: 12px; line-height: 1.5; }
</style>
</head>
<body>

<div id="toolbar">
  <div class="toolbar-left">
    <span class="dot"></span>
    <span id="status-text">Disconnected</span>
  </div>
  <div class="toolbar-right">
    <button class="toolbar-btn" id="stop-btn" title="Stop current task" style="display:none;">
      <svg viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>
    </button>
    <button class="toolbar-btn" id="history-btn" title="Chat history">
      <svg viewBox="0 0 16 16"><path d="M1.5 2A1.5 1.5 0 0 0 0 3.5v9A1.5 1.5 0 0 0 1.5 14h13a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 14.5 2h-13zM1 3.5a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 .5.5v9a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5v-9zM3 5h10v1H3V5zm0 3h10v1H3V8zm0 3h7v1H3v-1z"/></svg>
    </button>
    <button class="toolbar-btn" id="new-chat-btn" title="New chat">
      <svg viewBox="0 0 16 16"><path d="M14.5 2H9l-.35.15-.65.64-.65-.64L7 2H1.5l-.5.5v10l.5.5h5.29l.86.85h.7l.86-.85H14.5l.5-.5v-10l-.5-.5zm-7 10.32l-.18-.17L7 12H2V3h4.79l.86.85h.7l.86-.85H14v9h-5l-.32.15-.18.17zM4 6h3v1H4V6zm0 2h3v1H4V8zm0 2h3v1H4v-1zm5-4h3v1H9V6zm0 2h3v1H9V8zm0 2h3v1H9v-1z"/></svg>
    </button>
    <button class="toolbar-btn" id="close-btn" title="Close panel">
      <svg viewBox="0 0 16 16"><path d="M8 8.707l3.646 3.647.708-.707L8.707 8l3.647-3.646-.707-.708L8 7.293 4.354 3.646l-.708.708L7.293 8l-3.647 3.646.708.708L8 8.707z"/></svg>
    </button>
  </div>
</div>

<div id="conversation-list"></div>

<div id="messages">
  <div class="empty-state" id="empty">
    <div class="logo">&#x1F47B;</div>
    <div class="label">EloPhanto</div>
  </div>
</div>

<div id="thinking" class="thinking">
  <span>Thinking</span><span class="dots"></span>
</div>

<div id="input-area">
  <textarea id="input" rows="1" placeholder="Message EloPhanto..." disabled></textarea>
  <button id="send-btn" title="Send message (Enter)" disabled>
    <svg viewBox="0 0 16 16"><path d="M1.724 1.053a.5.5 0 0 1 .545-.065l12 6a.5.5 0 0 1 0 .894l-12 6A.5.5 0 0 1 1.5 13.5v-4.379a.5.5 0 0 1 .453-.497L8.5 8l-6.547-.624A.5.5 0 0 1 1.5 6.879V2.5a.5.5 0 0 1 .224-.447z"/></svg>
  </button>
</div>

<script>
  const vscode = acquireVsCodeApi();
  const messagesEl = document.getElementById('messages');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send-btn');
  const toolbar = document.getElementById('toolbar');
  const statusText = document.getElementById('status-text');
  const thinkingEl = document.getElementById('thinking');
  const inputArea = document.getElementById('input-area');
  const stopBtn = document.getElementById('stop-btn');
  const newChatBtn = document.getElementById('new-chat-btn');
  const historyBtn = document.getElementById('history-btn');
  const closeBtn = document.getElementById('close-btn');
  const convList = document.getElementById('conversation-list');

  let connected = false;
  let currentAgentMsgEl = null;
  let agentBuffer = '';
  let hasMessages = false;
  let showingHistory = false;

  // Restore state
  const prev = vscode.getState();
  if (prev && prev.messages) {
    const emptyEl = document.getElementById('empty');
    if (emptyEl) emptyEl.remove();
    hasMessages = true;
    messagesEl.innerHTML = prev.messages;
  }

  // ── Input ──
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  });
  input.addEventListener('focus', () => inputArea.classList.add('focused'));
  input.addEventListener('blur', () => inputArea.classList.remove('focused'));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener('click', send);

  // ── Toolbar buttons ──
  stopBtn.addEventListener('click', () => vscode.postMessage({ type: 'stop' }));

  newChatBtn.addEventListener('click', () => {
    // Hide history if showing
    if (showingHistory) toggleHistory();
    // Clear UI only (does NOT wipe agent memory)
    messagesEl.innerHTML = '<div class="empty-state" id="empty"><div class="logo">&#x1F47B;</div><div class="label">EloPhanto</div></div>';
    hasMessages = false;
    currentAgentMsgEl = null;
    agentBuffer = '';
    vscode.setState({ messages: '' });
    vscode.postMessage({ type: 'new-chat' });
  });

  historyBtn.addEventListener('click', () => {
    toggleHistory();
  });

  closeBtn.addEventListener('click', () => {
    vscode.postMessage({ type: 'close-panel' });
  });

  function toggleHistory() {
    showingHistory = !showingHistory;
    convList.classList.toggle('active', showingHistory);
    messagesEl.style.display = showingHistory ? 'none' : '';
    thinkingEl.style.display = showingHistory ? 'none' : '';
    historyBtn.style.opacity = showingHistory ? '1' : '';
    historyBtn.style.background = showingHistory ? 'rgba(128,128,128,0.15)' : '';
    if (showingHistory) {
      convList.innerHTML = '<div style="padding:12px;text-align:center;color:var(--muted);font-family:var(--mono);font-size:10px;letter-spacing:0.08em;">LOADING...</div>';
      vscode.postMessage({ type: 'load-conversations' });
    }
  }

  // ── Core functions ──
  function send() {
    const content = input.value.trim();
    if (!content || !connected) return;
    // Render user message immediately (don't wait for round-trip)
    addMessage(content, 'user', 'You \\u00b7 ' + getTime());
    thinkingEl.classList.add('active');
    setWorking(true);
    currentAgentMsgEl = null;
    agentBuffer = '';
    saveState();
    // Send to extension → gateway
    vscode.postMessage({ type: 'send', content });
    input.value = '';
    input.style.height = 'auto';
    input.focus();
  }

  function hideEmpty() {
    if (!hasMessages) {
      const el = document.getElementById('empty');
      if (el) el.remove();
      hasMessages = true;
    }
  }

  function removeToolSteps() {
    const steps = messagesEl.querySelectorAll('.tool-step');
    steps.forEach(s => s.remove());
  }

  function addMessage(content, cls, label) {
    hideEmpty();
    const wrapper = document.createElement('div');
    const align = cls === 'user' ? 'right' : cls === 'system' ? 'center' : 'left';
    wrapper.className = 'msg-wrapper ' + align;
    if (label) {
      const labelEl = document.createElement('div');
      labelEl.className = 'msg-label';
      labelEl.textContent = label;
      wrapper.appendChild(labelEl);
    }
    const el = document.createElement('div');
    el.className = 'msg ' + cls;
    el.textContent = content;
    wrapper.appendChild(el);
    messagesEl.appendChild(wrapper);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function addToolStep(toolName, thought) {
    hideEmpty();
    const el = document.createElement('div');
    el.className = 'tool-step';
    el.innerHTML = '<span class="spinner"></span><span class="tool-name">' +
      escapeHtml(toolName) + '</span>' +
      (thought ? ' <span>' + escapeHtml(thought) + '</span>' : '');
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function getTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function saveState() {
    // Remove tool steps before saving (they're transient)
    const clone = messagesEl.cloneNode(true);
    clone.querySelectorAll('.tool-step').forEach(s => s.remove());
    vscode.setState({ messages: clone.innerHTML });
  }

  function setWorking(working) {
    stopBtn.style.display = working ? '' : 'none';
  }

  // ── Message handler ──
  window.addEventListener('message', (event) => {
    const msg = event.data;

    switch (msg.type) {
      case 'status':
        connected = msg.connected;
        input.disabled = !connected;
        sendBtn.disabled = !connected;
        if (msg.reconnecting) {
          statusText.textContent = 'Reconnecting';
          toolbar.className = 'disconnected';
        } else if (connected) {
          statusText.textContent = 'Connected';
          toolbar.className = 'connected';
        } else {
          statusText.textContent = 'Disconnected';
          toolbar.className = 'disconnected';
        }
        break;

      case 'user-message':
        // From external triggers (sendSelection, explain, fix commands)
        addMessage(msg.content, 'user', 'You \\u00b7 ' + getTime());
        thinkingEl.classList.add('active');
        setWorking(true);
        currentAgentMsgEl = null;
        agentBuffer = '';
        saveState();
        break;

      case 'response':
        thinkingEl.classList.remove('active');
        if (!currentAgentMsgEl) {
          // Remove tool steps when response starts
          removeToolSteps();
          currentAgentMsgEl = addMessage('', 'agent streaming', 'Agent \\u00b7 ' + getTime());
        }
        if (msg.content) {
          agentBuffer += msg.content;
          currentAgentMsgEl.textContent = agentBuffer;
        }
        if (msg.done) {
          removeToolSteps();
          currentAgentMsgEl.classList.remove('streaming');
          currentAgentMsgEl.classList.add('complete');
          currentAgentMsgEl = null;
          agentBuffer = '';
          setWorking(false);
          saveState();
        }
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;

      case 'tool-step':
        addToolStep(msg.toolName, msg.thought);
        break;

      case 'mind-event': {
        const name = msg.event.replace('mind_', '').toUpperCase();
        addMessage(name, 'system', 'Mind');
        break;
      }

      case 'goal-event': {
        const glabel = msg.event === 'goal_started' ? 'STARTED' : 'COMPLETED';
        const goal = msg.data.goal ? ' \\u2014 ' + msg.data.goal : '';
        addMessage(glabel + goal, 'system', 'Goal');
        break;
      }

      case 'error':
        thinkingEl.classList.remove('active');
        removeToolSteps();
        addMessage(msg.detail, 'error', 'Error');
        currentAgentMsgEl = null;
        agentBuffer = '';
        setWorking(false);
        break;

      case 'new-chat':
        // Already handled by newChatBtn click — this is for external triggers
        messagesEl.innerHTML = '<div class="empty-state"><div class="logo">&#x1F47B;</div><div class="label">EloPhanto</div></div>';
        hasMessages = false;
        currentAgentMsgEl = null;
        agentBuffer = '';
        vscode.setState({ messages: '' });
        break;

      case 'chat-history': {
        // Load a conversation's messages into the chat
        messagesEl.innerHTML = '';
        hasMessages = false;
        currentAgentMsgEl = null;
        agentBuffer = '';
        const msgs = msg.messages || [];
        msgs.forEach(m => {
          if (m.role === 'user') {
            addMessage(m.content, 'user', 'You \\u00b7 ' + (m.timestamp || '').slice(11, 16));
          } else if (m.role === 'assistant') {
            const el = addMessage(m.content, 'agent complete', 'Agent \\u00b7 ' + (m.timestamp || '').slice(11, 16));
          }
        });
        saveState();
        break;
      }

      case 'conversations': {
        // Populate conversation list from gateway response
        convList.innerHTML = '';
        const convs = msg.conversations || [];
        // Header with back button
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:var(--muted);';
        header.innerHTML = '<span>Chat History</span>';
        const backBtn = document.createElement('button');
        backBtn.className = 'toolbar-btn';
        backBtn.title = 'Back to chat';
        backBtn.innerHTML = '<svg viewBox="0 0 16 16" style="width:14px;height:14px;fill:currentColor;"><path d="M8 8.707l3.646 3.647.708-.707L8.707 8l3.647-3.646-.707-.708L8 7.293 4.354 3.646l-.708.708L7.293 8l-3.647 3.646.708.708L8 8.707z"/></svg>';
        backBtn.addEventListener('click', () => toggleHistory());
        header.appendChild(backBtn);
        convList.appendChild(header);
        if (convs.length === 0) {
          const empty = document.createElement('div');
          empty.style.cssText = 'padding:24px 12px;text-align:center;color:var(--muted);font-family:var(--mono);font-size:10px;letter-spacing:0.08em;opacity:0.5;';
          empty.textContent = 'No conversations yet';
          convList.appendChild(empty);
        } else {
          convs.forEach(c => {
            const item = document.createElement('div');
            item.className = 'conv-item';
            item.innerHTML = '<span class="conv-title">' + escapeHtml(c.title || 'Untitled') + '</span>'
              + '<span class="conv-meta">' + (c.msg_count || '') + '</span>';
            item.addEventListener('click', () => {
              toggleHistory();
              vscode.postMessage({ type: 'switch-conversation', conversationId: c.id });
            });
            convList.appendChild(item);
          });
        }
        break;
      }
    }
  });
</script>
</body>
</html>`;
  }
}
