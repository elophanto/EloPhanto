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
  sessionId: string | null;
  isAgentTyping: boolean;
  historyLoaded: boolean;

  // Conversations
  conversations: Conversation[];
  currentConversationId: string | null;
  conversationsLoaded: boolean;

  sendMessage: (content: string) => void;
  appendAgentChunk: (replyTo: string, content: string, done: boolean) => void;
  addApprovalRequest: (req: ApprovalRequest) => void;
  respondToApproval: (requestId: string, approved: boolean) => void;
  addToolStep: (step: ToolStep) => void;
  clearToolSteps: () => void;
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
    }));
  },

  appendAgentChunk: (replyTo, content, done) => {
    set((s) => {
      const hasPlaceholder = s.messages.some(
        (m) => m.replyTo === replyTo && m.type === "agent"
      );

      if (hasPlaceholder) {
        return {
          messages: s.messages.map((m) =>
            m.replyTo === replyTo && m.type === "agent"
              ? { ...m, content, isStreaming: !done }
              : m
          ),
          isAgentTyping: !done,
        };
      }

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
