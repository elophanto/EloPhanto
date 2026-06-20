import { create } from "zustand";
import { gateway } from "@/lib/gateway";
import { generateId } from "@/lib/protocol";

export interface Message {
  id: string;
  type: "user" | "agent" | "error" | "system";
  content: string;
  timestamp: number;
  isStreaming: boolean;
  replyTo?: string;
  // ABE role visibility (docs/76 §Phase 2) — the org-role the agent operated
  // as, titled to business reality. Set on the final response of an agent turn.
  roleTitle?: string;
  roleEmoji?: string;
}

export interface ApprovalRequest {
  id: string;
  toolName: string;
  description: string;
  params: Record<string, unknown>;
  status: "pending" | "approved" | "denied";
  timestamp: number;
}

export interface ToolStep {
  id: string;
  step: number;
  toolName: string;
  thought: string;
  timestamp: number;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  msgCount: number;
}

interface HistoryMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
}

interface ChatStore {
  messages: Message[];
  approvalRequests: ApprovalRequest[];
  activeToolSteps: ToolStep[];
  /** Live chain-of-thought for the current turn (agent_thought chunks). */
  reasoning: string;
  sessionId: string | null;
  isAgentTyping: boolean;
  historyLoaded: boolean;

  // Conversations
  conversations: Conversation[];
  currentConversationId: string | null;
  conversationsLoaded: boolean;

  sendMessage: (content: string) => void;
  appendAgentChunk: (
    replyTo: string,
    content: string,
    done: boolean,
    roleTitle?: string,
    roleEmoji?: string
  ) => void;
  addApprovalRequest: (req: ApprovalRequest) => void;
  respondToApproval: (requestId: string, approved: boolean) => void;
  addToolStep: (step: ToolStep) => void;
  clearToolSteps: () => void;
  appendReasoning: (chunk: string) => void;
  clearReasoning: () => void;
  addSystemMessage: (content: string) => void;
  clearMessages: () => void;
  setSessionId: (id: string) => void;
  loadHistory: (data: {
    messages: HistoryMessage[];
    conversation_id?: string;
  }) => void;
  setConversations: (
    convs: Conversation[],
    currentId?: string | null
  ) => void;
  switchConversation: (id: string) => void;
  removeConversation: (id: string) => void;
  startNewChat: () => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  approvalRequests: [],
  activeToolSteps: [],
  reasoning: "",
  sessionId: null,
  isAgentTyping: false,
  historyLoaded: false,
  conversations: [],
  currentConversationId: null,
  conversationsLoaded: false,

  sendMessage: (content: string) => {
    const userMsg: Message = {
      id: generateId(),
      type: "user",
      content,
      timestamp: Date.now(),
      isStreaming: false,
    };

    const msgId = gateway.sendChat(content, get().sessionId ?? "");

    const agentMsg: Message = {
      id: generateId(),
      type: "agent",
      content: "",
      timestamp: Date.now(),
      isStreaming: true,
      replyTo: msgId,
    };

    set((s) => ({
      messages: [...s.messages, userMsg, agentMsg],
      isAgentTyping: true,
      activeToolSteps: [],
      reasoning: "", // fresh chain-of-thought for the new turn
    }));
  },

  appendAgentChunk: (replyTo, content, done, roleTitle, roleEmoji) => {
    set((s) => {
      // 1) Exact-match by replyTo — the happy path.
      const exactIdx = s.messages.findIndex(
        (m) => m.type === "agent" && m.replyTo === replyTo && !!replyTo
      );

      // 2) Fallback: most-recent agent placeholder that is still streaming.
      //    Production bug: some response paths arrive with an empty or
      //    stale `reply_to`, which used to leave the user's placeholder
      //    stuck as an empty bubble while a NEW message rendered with
      //    the actual content (visible only after refresh once history
      //    reordered things). Matching the live placeholder by streaming
      //    state recovers the chat regardless of what the wire sent.
      let targetIdx = exactIdx;
      if (targetIdx < 0) {
        for (let i = s.messages.length - 1; i >= 0; i--) {
          const m = s.messages[i];
          if (m && m.type === "agent" && m.isStreaming) {
            targetIdx = i;
            break;
          }
        }
      }

      const target = targetIdx >= 0 ? s.messages[targetIdx] : undefined;
      if (target) {
        const updated = s.messages.slice();
        updated[targetIdx] = {
          ...target,
          content,
          isStreaming: !done,
          // Capture the wire reply_to even when we matched by fallback,
          // so subsequent chunks for the same turn hit the exact path.
          replyTo: replyTo || target.replyTo,
          // Role badge arrives on the final response; keep any prior value
          // so a late empty chunk can't blank it.
          roleTitle: roleTitle || target.roleTitle,
          roleEmoji: roleEmoji || target.roleEmoji,
        };
        return { messages: updated, isAgentTyping: !done };
      }

      // No placeholder at all — server raced sendMessage(). Append a new
      // bubble so the response is at least visible to the user.
      return {
        messages: [
          ...s.messages,
          {
            id: generateId(),
            type: "agent" as const,
            content,
            timestamp: Date.now(),
            isStreaming: !done,
            replyTo,
            roleTitle,
            roleEmoji,
          },
        ],
        isAgentTyping: !done,
      };
    });
  },

  addApprovalRequest: (req) => {
    set((s) => ({
      approvalRequests: [...s.approvalRequests, req],
    }));
  },

  respondToApproval: (requestId, approved) => {
    gateway.sendApproval(requestId, approved);
    set((s) => ({
      approvalRequests: s.approvalRequests.map((r) =>
        r.id === requestId
          ? { ...r, status: approved ? ("approved" as const) : ("denied" as const) }
          : r
      ),
    }));
  },

  addToolStep: (step) => {
    set((s) => ({
      activeToolSteps: [...s.activeToolSteps, step],
    }));
  },

  clearToolSteps: () => set({ activeToolSteps: [] }),

  appendReasoning: (chunk) =>
    set((s) => ({
      // Cap to keep the buffer bounded on very long turns.
      reasoning: (s.reasoning + chunk).slice(-12000),
    })),
  clearReasoning: () => set({ reasoning: "" }),

  addSystemMessage: (content) => {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: generateId(),
          type: "system" as const,
          content,
          timestamp: Date.now(),
          isStreaming: false,
        },
      ],
    }));
  },

  clearMessages: () =>
    set({
      messages: [],
      approvalRequests: [],
      activeToolSteps: [],
      historyLoaded: false,
      currentConversationId: null,
    }),

  setSessionId: (id) => set({ sessionId: id }),

  loadHistory: (data) => {
    const loaded: Message[] = data.messages.map((m) => ({
      id: m.id,
      type: m.role === "user" ? ("user" as const) : ("agent" as const),
      content: m.content,
      timestamp: new Date(m.timestamp).getTime(),
      isStreaming: false,
    }));
    set({
      messages: loaded,
      currentConversationId: data.conversation_id ?? null,
      historyLoaded: true,
    });
  },

  setConversations: (convs, currentId) => {
    set((s) => ({
      conversations: convs,
      conversationsLoaded: true,
      currentConversationId: currentId ?? s.currentConversationId,
    }));
  },

  switchConversation: (id) => {
    set({
      messages: [],
      historyLoaded: false,
      currentConversationId: id,
      approvalRequests: [],
      activeToolSteps: [],
    });
    gateway.sendCommand("chat_history", { conversation_id: id });
  },

  removeConversation: (id) => {
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
    }));
  },

  startNewChat: () => {
    gateway.sendCommand("clear");
    set({
      messages: [],
      approvalRequests: [],
      activeToolSteps: [],
      historyLoaded: false,
      currentConversationId: null,
    });
  },
}));
