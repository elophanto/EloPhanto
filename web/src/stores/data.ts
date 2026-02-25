import { create } from "zustand";
import { gateway } from "@/lib/gateway";

// --- Tool types ---

export interface ToolInfo {
  name: string;
  description: string;
  permission: string;
  parameters: Record<string, { type?: string; description?: string }>;
  required: string[];
}

// --- Skill types ---

export interface SkillInfo {
  name: string;
  description: string;
  triggers: string[];
  source: string;
}

// --- Dashboard types ---

export interface DashboardIdentity {
  display_name: string;
  purpose: string;
  capabilities: string[];
}

export interface DashboardMind {
  running: boolean;
  paused: boolean;
  cycle_count: number;
  next_wakeup_sec: number;
  last_wakeup: string;
  last_action: string;
  budget_spent: number;
  budget_total: number;
  budget_remaining: number;
  recent_actions: { ts: string; summary: string }[];
  pending_events: number;
  scratchpad: string;
}

export interface DashboardGoal {
  goal_id: string;
  goal: string;
  status: string;
  current_checkpoint: number;
  total_checkpoints: number;
  cost_usd: number;
  created_at: string;
}

export interface DashboardSchedules {
  total: number;
  enabled: number;
  next_run: string | null;
}

export interface DashboardChannel {
  client_id: string;
  channel: string;
  user_id: string;
}

export interface DashboardSwarmAgent {
  agent_id: string;
  profile: string;
  task: string;
  branch: string;
  status: string;
  tmux_alive: boolean;
  pr_url: string | null;
  ci_status: string | null;
  spawned_at: string;
}

export interface DashboardStats {
  tools_count: number;
  skills_count: number;
  knowledge_chunks: number;
}

export interface DashboardData {
  identity: DashboardIdentity | null;
  mind: DashboardMind | null;
  goals: DashboardGoal[];
  schedules: DashboardSchedules;
  swarm: DashboardSwarmAgent[];
  channels: DashboardChannel[];
  stats: DashboardStats;
}

// --- Knowledge types ---

export interface KnowledgeFile {
  path: string;
  scope: string;
  chunks: number;
  tags: string[];
  updated_at: string;
}

export interface KnowledgeStats {
  chunks: number;
  embeddings: number;
  files: number;
  scopes: Record<string, number>;
}

export interface KnowledgeData {
  stats: KnowledgeStats;
  files: KnowledgeFile[];
}

export interface KnowledgeChunk {
  heading: string;
  content: string;
  scope: string;
  tags: string;
  tokens: number;
}

export interface KnowledgeDetail {
  file_path: string;
  chunks: KnowledgeChunk[];
}

// --- Mind types ---

export interface MindConfig {
  wakeup_seconds: number;
  min_wakeup_seconds: number;
  max_wakeup_seconds: number;
  budget_pct: number;
  max_rounds_per_wakeup: number;
  verbosity: string;
}

export interface MindEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface MindData {
  enabled: boolean;
  running?: boolean;
  paused?: boolean;
  cycle_count?: number;
  next_wakeup_sec?: number;
  last_wakeup?: string;
  last_action?: string;
  budget_spent?: number;
  budget_total?: number;
  budget_remaining?: number;
  recent_actions?: { ts: string; summary: string }[];
  pending_events?: number;
  scratchpad?: string;
  config?: MindConfig;
  error?: string;
}

// --- Schedule types ---

export interface ScheduleInfo {
  id: string;
  name: string;
  description: string;
  cron_expression: string;
  task_goal: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string;
  created_at: string;
}

// --- Channels types ---

export interface ClientInfo {
  client_id: string;
  channel: string;
  user_id: string;
  session_id: string;
}

export interface ChannelsData {
  clients: ClientInfo[];
  sessions: { active: number; unified_mode: boolean };
  gateway: { host: string; port: number };
}

// --- Config types ---

export type ConfigData = Record<string, unknown>;

// --- History types ---

export interface TaskMemory {
  goal: string;
  summary: string;
  outcome: string;
  tools_used: string[];
  created_at: string;
}

export interface EvolutionEntry {
  trigger: string;
  field: string;
  old_value: string;
  new_value: string;
  reason: string;
  created_at: string;
}

export interface HistoryData {
  tasks: TaskMemory[];
  evolution: EvolutionEntry[];
}

// --- Store ---

interface DataState {
  // Tools
  tools: ToolInfo[];
  toolsLoading: boolean;
  toolsLoaded: boolean;
  fetchTools: () => void;
  setTools: (tools: ToolInfo[]) => void;

  // Skills
  skills: SkillInfo[];
  skillsLoading: boolean;
  skillsLoaded: boolean;
  fetchSkills: () => void;
  setSkills: (skills: SkillInfo[]) => void;

  // Dashboard
  dashboard: DashboardData | null;
  dashboardLoading: boolean;
  fetchDashboard: () => void;
  setDashboard: (data: DashboardData) => void;

  // Knowledge
  knowledge: KnowledgeData | null;
  knowledgeLoading: boolean;
  fetchKnowledge: () => void;
  setKnowledge: (data: KnowledgeData) => void;

  // Knowledge detail (file chunks)
  knowledgeDetail: KnowledgeDetail | null;
  knowledgeDetailLoading: boolean;
  fetchKnowledgeDetail: (filePath: string) => void;
  setKnowledgeDetail: (data: KnowledgeDetail) => void;
  clearKnowledgeDetail: () => void;

  // Schedules
  schedules: ScheduleInfo[];
  schedulesLoading: boolean;
  schedulesLoaded: boolean;
  fetchSchedules: () => void;
  setSchedules: (data: ScheduleInfo[]) => void;

  // Channels
  channels: ChannelsData | null;
  channelsLoading: boolean;
  fetchChannels: () => void;
  setChannels: (data: ChannelsData) => void;

  // Config
  config: ConfigData | null;
  configLoading: boolean;
  configLoaded: boolean;
  fetchConfig: () => void;
  setConfig: (data: ConfigData) => void;

  // Mind
  mind: MindData | null;
  mindLoading: boolean;
  mindEvents: MindEvent[];
  fetchMind: () => void;
  setMind: (data: MindData) => void;
  addMindEvent: (event: MindEvent) => void;
  sendMindControl: (action: string) => void;

  // History
  history: HistoryData | null;
  historyLoading: boolean;
  fetchHistory: () => void;
  setHistory: (data: HistoryData) => void;
}

export const useDataStore = create<DataState>((set, get) => ({
  // Tools
  tools: [],
  toolsLoading: false,
  toolsLoaded: false,
  fetchTools: () => {
    if (get().toolsLoaded || get().toolsLoading) return;
    set({ toolsLoading: true });
    gateway.sendCommand("tools");
  },
  setTools: (tools) => set({ tools, toolsLoading: false, toolsLoaded: true }),

  // Skills
  skills: [],
  skillsLoading: false,
  skillsLoaded: false,
  fetchSkills: () => {
    if (get().skillsLoaded || get().skillsLoading) return;
    set({ skillsLoading: true });
    gateway.sendCommand("skills");
  },
  setSkills: (skills) =>
    set({ skills, skillsLoading: false, skillsLoaded: true }),

  // Dashboard — always refetch (live data)
  dashboard: null,
  dashboardLoading: false,
  fetchDashboard: () => {
    set({ dashboardLoading: true });
    gateway.sendCommand("dashboard");
  },
  setDashboard: (data) => set({ dashboard: data, dashboardLoading: false }),

  // Knowledge — always refetch
  knowledge: null,
  knowledgeLoading: false,
  fetchKnowledge: () => {
    set({ knowledgeLoading: true });
    gateway.sendCommand("knowledge");
  },
  setKnowledge: (data) => set({ knowledge: data, knowledgeLoading: false }),

  // Knowledge detail
  knowledgeDetail: null,
  knowledgeDetailLoading: false,
  fetchKnowledgeDetail: (filePath: string) => {
    set({ knowledgeDetailLoading: true, knowledgeDetail: null });
    gateway.sendCommand("knowledge_detail", { file_path: filePath });
  },
  setKnowledgeDetail: (data) =>
    set({ knowledgeDetail: data, knowledgeDetailLoading: false }),
  clearKnowledgeDetail: () =>
    set({ knowledgeDetail: null, knowledgeDetailLoading: false }),

  // Schedules
  schedules: [],
  schedulesLoading: false,
  schedulesLoaded: false,
  fetchSchedules: () => {
    if (get().schedulesLoaded || get().schedulesLoading) return;
    set({ schedulesLoading: true });
    gateway.sendCommand("schedules");
  },
  setSchedules: (data) =>
    set({ schedules: data, schedulesLoading: false, schedulesLoaded: true }),

  // Channels — always refetch (live data)
  channels: null,
  channelsLoading: false,
  fetchChannels: () => {
    set({ channelsLoading: true });
    gateway.sendCommand("channels");
  },
  setChannels: (data) => set({ channels: data, channelsLoading: false }),

  // Config — fetch once
  config: null,
  configLoading: false,
  configLoaded: false,
  fetchConfig: () => {
    if (get().configLoaded || get().configLoading) return;
    set({ configLoading: true });
    gateway.sendCommand("config");
  },
  setConfig: (data) =>
    set({ config: data, configLoading: false, configLoaded: true }),

  // Mind — always refetch (live data)
  mind: null,
  mindLoading: false,
  mindEvents: [],
  fetchMind: () => {
    set({ mindLoading: true });
    gateway.sendCommand("mind_status");
  },
  setMind: (data) => set({ mind: data, mindLoading: false }),
  addMindEvent: (event) =>
    set((state) => ({
      mindEvents: [...state.mindEvents.slice(-99), event],
    })),
  sendMindControl: (action) => {
    gateway.sendCommand("mind_control", { action });
  },

  // History — always refetch
  history: null,
  historyLoading: false,
  fetchHistory: () => {
    set({ historyLoading: true });
    gateway.sendCommand("history");
  },
  setHistory: (data) => set({ history: data, historyLoading: false }),
}));
