import { useEffect } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Shell } from "@/components/layout/Shell";
import { ChatPage } from "@/components/chat/ChatPage";
import { ToolsPage } from "@/components/tools/ToolsPage";
import { SkillsPage } from "@/components/skills/SkillsPage";
import { DashboardPage } from "@/components/dashboard/DashboardPage";
import { KnowledgePage } from "@/components/knowledge/KnowledgePage";
import { SchedulePage } from "@/components/schedule/SchedulePage";
import { ChannelsPage } from "@/components/channels/ChannelsPage";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { HistoryPage } from "@/components/history/HistoryPage";
import { MindPage } from "@/components/mind/MindPage";
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

        // Check if this is a structured command response (JSON)
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
            if (parsed.dashboard != null) {
              dataStore.setDashboard(
                parsed.dashboard as ReturnType<
                  typeof useDataStore.getState
                >["dashboard"] &
                  object
              );
              return;
            }
            if (parsed.knowledge != null) {
              dataStore.setKnowledge(
                parsed.knowledge as ReturnType<
                  typeof useDataStore.getState
                >["knowledge"] &
                  object
              );
              return;
            }
            if (Array.isArray(parsed.schedules)) {
              dataStore.setSchedules(
                parsed.schedules as ReturnType<
                  typeof useDataStore.getState
                >["schedules"]
              );
              return;
            }
            if (parsed.channels != null) {
              dataStore.setChannels(
                parsed.channels as ReturnType<
                  typeof useDataStore.getState
                >["channels"] &
                  object
              );
              return;
            }
            if (parsed.config != null) {
              dataStore.setConfig(
                parsed.config as ReturnType<
                  typeof useDataStore.getState
                >["config"] &
                  object
              );
              return;
            }
            if (parsed.knowledge_detail != null) {
              dataStore.setKnowledgeDetail(
                parsed.knowledge_detail as ReturnType<
                  typeof useDataStore.getState
                >["knowledgeDetail"] &
                  object
              );
              return;
            }
            if (parsed.mind_status != null) {
              dataStore.setMind(
                parsed.mind_status as ReturnType<
                  typeof useDataStore.getState
                >["mind"] &
                  object
              );
              return;
            }
            if (parsed.mind_control != null) {
              // After a control action, refresh mind status
              setTimeout(() => dataStore.fetchMind(), 300);
              return;
            }
            if (parsed.history != null) {
              dataStore.setHistory(
                parsed.history as ReturnType<
                  typeof useDataStore.getState
                >["history"] &
                  object
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
        } else if (event.startsWith("mind_")) {
          useDataStore.getState().addMindEvent({
            type: event,
            data: msg.data as Record<string, unknown>,
            timestamp: Date.now(),
          });
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
    case "dashboard":
      return <DashboardPage />;
    case "tools":
      return <ToolsPage />;
    case "skills":
      return <SkillsPage />;
    case "knowledge":
      return <KnowledgePage />;
    case "schedule":
      return <SchedulePage />;
    case "channels":
      return <ChannelsPage />;
    case "settings":
      return <SettingsPage />;
    case "mind":
      return <MindPage />;
    case "history":
      return <HistoryPage />;
    case "chat":
      return <ChatPage />;
    default:
      return <DashboardPage />;
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
