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

interface ChatStore {
  messages: Message[];
  approvalRequests: ApprovalRequest[];
  activeToolSteps: ToolStep[];
  sessionId: string | null;
  isAgentTyping: boolean;

  sendMessage: (content: string) => void;
  appendAgentChunk: (replyTo: string, content: string, done: boolean) => void;
  addApprovalRequest: (req: ApprovalRequest) => void;
  respondToApproval: (requestId: string, approved: boolean) => void;
  addToolStep: (step: ToolStep) => void;
  clearToolSteps: () => void;
  addSystemMessage: (content: string) => void;
  clearMessages: () => void;
  setSessionId: (id: string) => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  approvalRequests: [],
  activeToolSteps: [],
  sessionId: null,
  isAgentTyping: false,

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
      // Find existing placeholder by replyTo
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

      // No placeholder found — create a new agent message
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
    }),

  setSessionId: (id) => set({ sessionId: id }),
}));
