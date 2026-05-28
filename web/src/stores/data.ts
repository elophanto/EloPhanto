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

// --- ABE: companies / roles ---

export interface CompanyRow {
  slug: string;
  name: string;
  status: string;
  active: boolean;
  trust: string;
  has_product: boolean;
  voice: string;
  strategy: string;
  blockers: number;
  net_7d: number;
}

export interface CompanyVoice {
  persona: string;
  tone: string[];
  length_target: string;
  cta_style: string;
  banned_phrases: string[];
  allowed_hooks: string[];
}

export interface CompanyStrategy {
  name: string;
  tagline: string;
  overview: string;
  core_message: string;
  tactics: number;
  quick_wins: string[];
  metrics: string[];
}

export interface CompanyBlocker {
  id: string;
  type: string;
  description: string;
  proposal: string;
  resolved: boolean;
}

export interface CompanyDraft {
  id: string;
  kind: string;
  preview: string;
}

export interface CompanyLedger {
  revenue: number;
  spend: number;
  tokens: number;
  recent: Record<string, unknown>[];
}

export interface CompanyDetail {
  slug: string;
  name?: string;
  status?: string;
  trust?: string;
  product?: Record<string, unknown> | null;
  voice: CompanyVoice | null;
  strategy: CompanyStrategy | null;
  blockers: CompanyBlocker[];
  drafts: CompanyDraft[];
  ledger: CompanyLedger;
}

export interface RoleRow {
  name: string;
  description: string;
  allowed_tool_groups: string[];
  kpi: Record<string, unknown>;
  last_active_at: string | null;
}

// --- Goals (full queue, beyond dashboard's active few) ---

export interface GoalRow {
  goal_id: string;
  goal: string;
  status: string;
  current_checkpoint: number;
  total_checkpoints: number;
  llm_calls: number;
  cost_usd: number;
  mission_id: string | null;
  role: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalCheckpoint {
  order: number;
  title: string;
  status: string;
  success_criteria: string;
}

export interface GoalDetail extends GoalRow {
  context_summary: string;
  checkpoints: GoalCheckpoint[];
}

// --- Affect ---

export interface AffectData {
  pleasure: number;
  arousal: number;
  dominance: number;
  label: string;
  description: string;
  magnitude: number;
  updated_at: string;
  recent_events: Record<string, unknown>[];
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
  deleteSchedule: (id: string) => void;
  toggleSchedule: (id: string, enabled: boolean) => void;

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

  // ABE: companies
  companies: CompanyRow[];
  companiesLoading: boolean;
  fetchCompanies: () => void;
  setCompanies: (data: CompanyRow[]) => void;
  companyDetail: CompanyDetail | null;
  companyDetailLoading: boolean;
  fetchCompanyDetail: (slug: string) => void;
  setCompanyDetail: (data: CompanyDetail | null) => void;
  clearCompanyDetail: () => void;

  // ABE: roles
  roles: RoleRow[];
  rolesLoading: boolean;
  fetchRoles: () => void;
  setRoles: (data: RoleRow[]) => void;

  // Goals (full queue)
  goalsList: GoalRow[];
  goalsListLoading: boolean;
  fetchGoals: (status?: string) => void;
  setGoals: (data: GoalRow[]) => void;
  goalDetail: GoalDetail | null;
  goalDetailLoading: boolean;
  fetchGoalDetail: (goalId: string) => void;
  setGoalDetail: (data: GoalDetail | null) => void;
  clearGoalDetail: () => void;

  // Affect
  affect: AffectData | null;
  affectLoading: boolean;
  fetchAffect: () => void;
  setAffect: (data: AffectData | null) => void;
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
  deleteSchedule: (id: string) => {
    // Optimistic remove; gateway responds with the authoritative list.
    set({ schedules: get().schedules.filter((s) => s.id !== id) });
    gateway.sendCommand("schedule_delete", { schedule_id: id });
  },
  toggleSchedule: (id: string, enabled: boolean) => {
    set({
      schedules: get().schedules.map((s) =>
        s.id === id ? { ...s, enabled } : s,
      ),
    });
    gateway.sendCommand("schedule_toggle", { schedule_id: id, enabled });
  },

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

  // ABE: companies — always refetch (live status)
  companies: [],
  companiesLoading: false,
  fetchCompanies: () => {
    set({ companiesLoading: true });
    gateway.sendCommand("companies");
  },
  setCompanies: (data) => set({ companies: data, companiesLoading: false }),
  companyDetail: null,
  companyDetailLoading: false,
  fetchCompanyDetail: (slug: string) => {
    set({ companyDetailLoading: true, companyDetail: null });
    gateway.sendCommand("company_detail", { slug });
  },
  setCompanyDetail: (data) =>
    set({ companyDetail: data, companyDetailLoading: false }),
  clearCompanyDetail: () =>
    set({ companyDetail: null, companyDetailLoading: false }),

  // ABE: roles
  roles: [],
  rolesLoading: false,
  fetchRoles: () => {
    set({ rolesLoading: true });
    gateway.sendCommand("roles");
  },
  setRoles: (data) => set({ roles: data, rolesLoading: false }),

  // Goals (full queue)
  goalsList: [],
  goalsListLoading: false,
  fetchGoals: (status?: string) => {
    set({ goalsListLoading: true });
    // Pull a generous window so client-side pagination is meaningful;
    // the dashboard isn't a place to scroll 1000s of goals.
    gateway.sendCommand("goals", { limit: 500, ...(status ? { status } : {}) });
  },
  setGoals: (data) => set({ goalsList: data, goalsListLoading: false }),
  goalDetail: null,
  goalDetailLoading: false,
  fetchGoalDetail: (goalId: string) => {
    set({ goalDetailLoading: true, goalDetail: null });
    gateway.sendCommand("goal_detail", { goal_id: goalId });
  },
  setGoalDetail: (data) =>
    set({ goalDetail: data, goalDetailLoading: false }),
  clearGoalDetail: () =>
    set({ goalDetail: null, goalDetailLoading: false }),

  // Affect
  affect: null,
  affectLoading: false,
  fetchAffect: () => {
    set({ affectLoading: true });
    gateway.sendCommand("affect");
  },
  setAffect: (data) => set({ affect: data, affectLoading: false }),
}));
