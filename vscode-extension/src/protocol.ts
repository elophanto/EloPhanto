/** Gateway protocol types — mirrors core/protocol.py exactly. */

import { randomUUID } from "crypto";

export const MessageType = {
  CHAT: "chat",
  RESPONSE: "response",
  APPROVAL_REQUEST: "approval_request",
  APPROVAL_RESPONSE: "approval_response",
  EVENT: "event",
  COMMAND: "command",
  STATUS: "status",
  ERROR: "error",
} as const;

export type MessageTypeValue = (typeof MessageType)[keyof typeof MessageType];

export const EventType = {
  TASK_COMPLETE: "task_complete",
  TASK_ERROR: "task_error",
  STEP_PROGRESS: "step_progress",
  NOTIFICATION: "notification",
  GOAL_STARTED: "goal_started",
  GOAL_COMPLETED: "goal_completed",
  GOAL_FAILED: "goal_failed",
  MIND_WAKEUP: "mind_wakeup",
  MIND_ACTION: "mind_action",
  MIND_TOOL_USE: "mind_tool_use",
  MIND_SLEEP: "mind_sleep",
  MIND_PAUSED: "mind_paused",
  MIND_RESUMED: "mind_resumed",
  MIND_ERROR: "mind_error",
  AGENT_SPAWNED: "agent_spawned",
  AGENT_COMPLETED: "agent_completed",
  AGENT_FAILED: "agent_failed",
  SHUTDOWN: "shutdown",
} as const;

export interface GatewayMessage {
  type: MessageTypeValue;
  id: string;
  session_id: string;
  channel: string;
  user_id: string;
  data: Record<string, unknown>;
}

export interface IdeContext {
  active_file?: string;
  selection?: {
    text: string;
    start_line: number;
    end_line: number;
  };
  workspace_root?: string;
  open_files?: string[];
  language?: string;
  diagnostics?: Array<{
    file: string;
    line: number;
    severity: string;
    message: string;
  }>;
}

export function createChatMessage(
  content: string,
  ideContext?: IdeContext,
  sessionId: string = ""
): GatewayMessage {
  const data: Record<string, unknown> = { content };
  if (ideContext) {
    data.ide_context = ideContext;
  }
  return {
    type: MessageType.CHAT,
    id: randomUUID(),
    session_id: sessionId,
    channel: "vscode",
    user_id: "vscode-user",
    data,
  };
}

export function createApprovalResponse(
  requestId: string,
  approved: boolean
): GatewayMessage {
  return {
    type: MessageType.APPROVAL_RESPONSE,
    id: requestId,
    session_id: "",
    channel: "vscode",
    user_id: "vscode-user",
    data: { approved },
  };
}

export function createCommandMessage(
  command: string,
  args: Record<string, unknown> = {}
): GatewayMessage {
  return {
    type: MessageType.COMMAND,
    id: randomUUID(),
    session_id: "",
    channel: "vscode",
    user_id: "vscode-user",
    data: { command, args },
  };
}

export function createStatusMessage(): GatewayMessage {
  return {
    type: MessageType.STATUS,
    id: randomUUID(),
    session_id: "",
    channel: "vscode",
    user_id: "",
    data: { status: "ping" },
  };
}
