import { useState } from "react";
import { Sidebar } from "./Sidebar";
import { ActivityTicker } from "./ActivityTicker";

export function Shell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
      />
      <main className="flex flex-1 flex-col overflow-hidden">
        <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
        <ActivityTicker />
      </main>
    </div>
  );
}
