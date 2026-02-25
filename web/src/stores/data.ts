import { create } from "zustand";
import { gateway } from "@/lib/gateway";

export interface ToolInfo {
  name: string;
  description: string;
  permission: string;
  parameters: Record<string, { type?: string; description?: string }>;
  required: string[];
}

export interface SkillInfo {
  name: string;
  description: string;
  triggers: string[];
  source: string;
}

interface DataState {
  tools: ToolInfo[];
  skills: SkillInfo[];
  toolsLoading: boolean;
  skillsLoading: boolean;
  toolsLoaded: boolean;
  skillsLoaded: boolean;

  fetchTools: () => void;
  fetchSkills: () => void;
  setTools: (tools: ToolInfo[]) => void;
  setSkills: (skills: SkillInfo[]) => void;
}

export const useDataStore = create<DataState>((set, get) => ({
  tools: [],
  skills: [],
  toolsLoading: false,
  skillsLoading: false,
  toolsLoaded: false,
  skillsLoaded: false,

  fetchTools: () => {
    if (get().toolsLoaded || get().toolsLoading) return;
    set({ toolsLoading: true });
    gateway.sendCommand("tools");
  },

  fetchSkills: () => {
    if (get().skillsLoaded || get().skillsLoading) return;
    set({ skillsLoading: true });
    gateway.sendCommand("skills");
  },

  setTools: (tools) => set({ tools, toolsLoading: false, toolsLoaded: true }),
  setSkills: (skills) =>
    set({ skills, skillsLoading: false, skillsLoaded: true }),
}));
