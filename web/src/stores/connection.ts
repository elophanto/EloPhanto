import { create } from "zustand";
import { gateway } from "@/lib/gateway";

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

interface ConnectionStore {
  status: ConnectionStatus;
  clientId: string | null;
  error: string | null;

  connect: () => void;
  disconnect: () => void;

  _setStatus: (s: ConnectionStatus) => void;
  _setClientId: (id: string) => void;
  _setError: (err: string | null) => void;
}

export const useConnectionStore = create<ConnectionStore>((set) => ({
  status: "disconnected",
  clientId: null,
  error: null,

  connect: () => {
    set({ status: "connecting", error: null });
    gateway.connect();
  },

  disconnect: () => {
    gateway.disconnect();
    set({ status: "disconnected", clientId: null });
  },

  _setStatus: (status) => set({ status }),
  _setClientId: (clientId) => set({ clientId }),
  _setError: (error) => set({ error }),
}));
