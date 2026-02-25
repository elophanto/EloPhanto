/** Gateway protocol types — mirrors core/protocol.py exactly. */

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
  SESSION_CREATED: "session_created",
  NOTIFICATION: "notification",
  GOAL_STARTED: "goal_started",
  GOAL_COMPLETED: "goal_completed",
  GOAL_FAILED: "goal_failed",
  AGENT_SPAWNED: "agent_spawned",
  AGENT_COMPLETED: "agent_completed",
  AGENT_FAILED: "agent_failed",
  MIND_WAKEUP: "mind_wakeup",
  MIND_ACTION: "mind_action",
  MIND_SLEEP: "mind_sleep",
} as const;

export interface GatewayMessage {
  type: MessageTypeValue;
  id: string;
  session_id: string;
  channel: string;
  user_id: string;
  data: Record<string, unknown>;
}

export interface ResponseData {
  content: string;
  done: boolean;
  reply_to: string;
}

export interface ApprovalRequestData {
  tool_name: string;
  description: string;
  params: Record<string, unknown>;
}

export interface EventData {
  event: string;
  [key: string]: unknown;
}

export interface StepProgressData {
  event: "step_progress";
  step: number;
  tool_name: string;
  thought: string;
}

export interface StatusData {
  status: string;
  client_id?: string;
}

export interface ErrorData {
  detail: string;
  reply_to?: string;
}

export function generateId(): string {
  return crypto.randomUUID();
}

export function createChatMessage(
  content: string,
  sessionId: string = ""
): GatewayMessage {
  return {
    type: MessageType.CHAT,
    id: generateId(),
    session_id: sessionId,
    channel: "web",
    user_id: getUserId(),
    data: { content },
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
    channel: "web",
    user_id: getUserId(),
    data: { approved },
  };
}

export function createCommandMessage(
  command: string,
  args: Record<string, unknown> = {}
): GatewayMessage {
  return {
    type: MessageType.COMMAND,
    id: generateId(),
    session_id: "",
    channel: "web",
    user_id: getUserId(),
    data: { command, args },
  };
}

export function createStatusMessage(): GatewayMessage {
  return {
    type: MessageType.STATUS,
    id: generateId(),
    session_id: "",
    channel: "web",
    user_id: "",
    data: { status: "ping" },
  };
}

function getUserId(): string {
  let id = localStorage.getItem("elophanto-user-id");
  if (!id) {
    id = `web-${generateId().slice(0, 8)}`;
    localStorage.setItem("elophanto-user-id", id);
  }
  return id;
}
