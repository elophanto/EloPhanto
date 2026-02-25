import { useEffect } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Shell } from "@/components/layout/Shell";
import { ChatPage } from "@/components/chat/ChatPage";
import { ToolsPage } from "@/components/tools/ToolsPage";
import { SkillsPage } from "@/components/skills/SkillsPage";
import { gateway } from "@/lib/gateway";
import { MessageType, type ResponseData, generateId } from "@/lib/protocol";
import { useConnectionStore } from "@/stores/connection";
import { useChatStore } from "@/stores/chat";
import { useDataStore } from "@/stores/data";
import { useNavigationStore } from "@/stores/navigation";

function GatewayWiring() {
  useEffect(() => {
    const unsubs = [
      gateway.on(MessageType.STATUS, (msg) => {
        const status = msg.data.status as string;
        const store = useConnectionStore.getState();

        if (status === "connected") {
          store._setStatus("connected");
          if (msg.data.client_id) {
            store._setClientId(msg.data.client_id as string);
          }
        } else if (status === "disconnected") {
          store._setStatus("disconnected");
        } else if (status === "reconnecting") {
          store._setStatus("reconnecting");
        }
      }),

      gateway.on(MessageType.RESPONSE, (msg) => {
        const data = msg.data as unknown as ResponseData;
        const content = data.content ?? "";

        // Check if this is a structured command response (tools/skills JSON)
        if (content.startsWith("{")) {
          try {
            const parsed = JSON.parse(content) as Record<string, unknown>;
            const dataStore = useDataStore.getState();

            if (Array.isArray(parsed.tools)) {
              dataStore.setTools(
                parsed.tools as ReturnType<
                  typeof useDataStore.getState
                >["tools"]
              );
              return;
            }
            if (Array.isArray(parsed.skills)) {
              dataStore.setSkills(
                parsed.skills as ReturnType<
                  typeof useDataStore.getState
                >["skills"]
              );
              return;
            }
          } catch {
            // Not JSON — fall through to chat handling
          }
        }

        // Regular chat response
        const chat = useChatStore.getState();
        chat.appendAgentChunk(data.reply_to, content, data.done);

        if (msg.session_id && !chat.sessionId) {
          chat.setSessionId(msg.session_id);
        }
      }),

      gateway.on(MessageType.APPROVAL_REQUEST, (msg) => {
        useChatStore.getState().addApprovalRequest({
          id: msg.id,
          toolName: msg.data.tool_name as string,
          description: msg.data.description as string,
          params: (msg.data.params as Record<string, unknown>) ?? {},
          status: "pending",
          timestamp: Date.now(),
        });
      }),

      gateway.on(MessageType.EVENT, (msg) => {
        const event = msg.data.event as string;
        const chat = useChatStore.getState();

        if (event === "step_progress") {
          chat.addToolStep({
            id: generateId(),
            step: (msg.data.step as number) ?? 0,
            toolName: (msg.data.tool_name as string) ?? "",
            thought: (msg.data.thought as string) ?? "",
            timestamp: Date.now(),
          });
        } else if (event === "task_complete") {
          chat.clearToolSteps();
        } else if (event === "session_created") {
          if (msg.session_id) {
            chat.setSessionId(msg.session_id);
          }
        }
      }),

      gateway.on(MessageType.ERROR, (msg) => {
        const detail = (msg.data.detail as string) ?? "Unknown error";
        useChatStore.getState().addSystemMessage(`Error: ${detail}`);
        useConnectionStore.getState()._setError(detail);
      }),
    ];

    // Connect to gateway
    useConnectionStore.getState().connect();

    return () => {
      unsubs.forEach((u) => u());
      useConnectionStore.getState().disconnect();
    };
  }, []);

  return null;
}

function PageRouter() {
  const activePage = useNavigationStore((s) => s.activePage);

  switch (activePage) {
    case "tools":
      return <ToolsPage />;
    case "skills":
      return <SkillsPage />;
    default:
      return <ChatPage />;
  }
}

export function App() {
  return (
    <ThemeProvider>
      <GatewayWiring />
      <Shell>
        <PageRouter />
      </Shell>
    </ThemeProvider>
  );
}
