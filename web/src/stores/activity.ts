import { create } from "zustand";

// A tiny, always-on slice that captures the agent's most recent
// activity line — fed from the gateway EVENT stream (step_progress
// tool narration + mind_* cycle events). Powers the persistent
// activity ticker in the Shell so "what's it doing right now" is
// ambient on every page, not buried in the Mind page.

export interface ActivityItem {
  /** Short label — tool name or mind event type. */
  label: string;
  /** Optional one-line detail (the agent's thought / event summary). */
  detail: string;
  /** epoch ms. */
  at: number;
  /** "tool" (live task step) | "mind" (autonomous cycle). */
  kind: "tool" | "mind";
}

interface ActivityState {
  latest: ActivityItem | null;
  /** Rolling buffer for a future expanded view (capped). */
  recent: ActivityItem[];
  push: (item: Omit<ActivityItem, "at">) => void;
  clear: () => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  latest: null,
  recent: [],
  push: (item) =>
    set((s) => {
      const full: ActivityItem = { ...item, at: Date.now() };
      return {
        latest: full,
        recent: [...s.recent.slice(-49), full],
      };
    }),
  clear: () => set({ latest: null }),
}));
