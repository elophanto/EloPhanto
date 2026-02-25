import { create } from "zustand";

export type Page =
  | "chat"
  | "tools"
  | "skills"
  | "knowledge"
  | "schedule"
  | "channels"
  | "settings"
  | "history";

interface NavigationState {
  activePage: Page;
  navigate: (page: Page) => void;
}

export const useNavigationStore = create<NavigationState>((set) => ({
  activePage: "chat",
  navigate: (page) => set({ activePage: page }),
}));
