import { create } from "zustand";

export type Page =
  | "dashboard"
  | "chat"
  | "companies"
  | "goals"
  | "roles"
  | "affect"
  | "ego"
  | "tools"
  | "skills"
  | "knowledge"
  | "mind"
  | "schedule"
  | "channels"
  | "settings"
  | "history";

interface NavigationState {
  activePage: Page;
  navigate: (page: Page) => void;
}

export const useNavigationStore = create<NavigationState>((set) => ({
  activePage: "dashboard",
  navigate: (page) => set({ activePage: page }),
}));
