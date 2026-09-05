import { useEffect, useState } from "react";

export const departments = [
  {
    id: "headquarters",
    name: "Headquarters",
    short: "HQ",
    color: "#aa7156",
    description:
      "Where plans take shape. Reasoning, delegation, and the next move.",
  },
  {
    id: "research",
    name: "Research",
    short: "Research",
    color: "#5c8c97",
    description:
      "An observatory for the outside world. Browsing, search, and discovery.",
  },
  {
    id: "engineering",
    name: "Engineering",
    short: "Engineering",
    color: "#4f8973",
    description:
      "The workshop. Code, files, shell commands, and things that work.",
  },
  {
    id: "communications",
    name: "Communications",
    short: "Comms",
    color: "#b58f40",
    description:
      "Connections beyond the campus. Messages, channels, and outreach.",
  },
  {
    id: "knowledge",
    name: "Knowledge",
    short: "Knowledge",
    color: "#b77883",
    description:
      "The living library. Memory, skills, and everything learned along the way.",
  },
  {
    id: "operations",
    name: "Operations",
    short: "Operations",
    color: "#8583a4",
    description:
      "Keeping the society moving. Scheduling, resources, and coordination.",
  },
] as const;
export type Department = (typeof departments)[number]["id"];
export type Resident = {
  id: string;
  name: string;
  kind: string;
  parent_id?: string;
  department: string;
  status: string;
  tool: string;
  updated_at: number;
};
export type SocietyEvent = {
  id: number | string;
  agent_id: string;
  kind: string;
  department: string;
  status: string;
  tool: string;
  timestamp: number;
};
export type Snapshot = {
  version: number;
  sequence: number;
  started_at: number;
  updated_at: number;
  agents: Resident[];
  events: SocietyEvent[];
  stats: { active: number; total: number; completed: number; errors: number };
};
export const emptySnapshot: Snapshot = {
  version: 1,
  sequence: 0,
  started_at: 0,
  updated_at: 0,
  agents: [],
  events: [],
  stats: { active: 0, total: 0, completed: 0, errors: 0 },
};
export function departmentOf(id: string) {
  return departments.find((d) => d.id === id) ?? departments[0];
}
export function prettyTool(tool: string) {
  return tool.replace(/_/g, " ");
}
export function statusLabel(status: string) {
  return (
    (
      {
        idle: "At ease",
        thinking: "Thinking",
        working: "Working",
        waiting: "Waiting",
        error: "Needs attention",
        offline: "Offline",
        completed: "Finished",
      } as Record<string, string>
    )[status] ?? status
  );
}
const demoPeople = [
  ["elo", "Elo", "main"],
  ["atlas", "Atlas", "swarm"],
  ["nova", "Nova", "swarm"],
  ["sage", "Sage", "kid"],
  ["echo", "Echo", "kid"],
  ["pip", "Pip", "swarm"],
  ["lumi", "Lumi", "kid"],
  ["milo", "Milo", "swarm"],
];
const demoTools = [
  "plan",
  "browser_search",
  "shell_execute",
  "email_search",
  "knowledge_search",
  "schedule_list",
];
function demoSnapshot(tick: number, started: number): Snapshot {
  const now = Date.now() / 1000;
  const agents = demoPeople.map(([id, name, kind], i): Resident => {
    const index = (i + Math.floor(tick / 2)) % departments.length;
    return {
      id: id!,
      name: name!,
      kind: kind!,
      department: departments[index]!.id,
      status: i === 0 ? "thinking" : i === 6 ? "idle" : "working",
      tool: i === 6 ? "" : demoTools[index]!,
      updated_at: now,
    };
  });
  return {
    version: 1,
    sequence: tick,
    started_at: started,
    updated_at: now,
    agents,
    events: Array.from({ length: Math.min(tick + 4, 20) }, (_, i) => {
      const who = agents[(tick + 20 - i) % agents.length]!;
      return {
        id: tick - i,
        agent_id: who.id,
        kind: "tool_started",
        department: who.department,
        status: who.status,
        tool: who.tool,
        timestamp: now - i * 14,
      };
    }),
    stats: { active: 7, total: 8, completed: 24 + tick, errors: 0 },
  };
}
export function useSociety(demo: boolean) {
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [connection, setConnection] = useState<
    "connecting" | "live" | "offline" | "demo"
  >("connecting");
  useEffect(() => {
    if (demo) {
      let tick = 0;
      const started = Date.now() / 1000;
      setConnection("demo");
      setSnapshot(demoSnapshot(tick, started));
      const timer = setInterval(
        () => setSnapshot(demoSnapshot(++tick, started)),
        7000,
      );
      return () => clearInterval(timer);
    }
    setSnapshot(emptySnapshot);
    setConnection("connecting");
    const source = new EventSource("/api/society/events");
    let timeout = window.setTimeout(() => setConnection("offline"), 6000);
    const update = (event: MessageEvent) => {
      try {
        const data: unknown = JSON.parse(event.data);
        if (
          !data ||
          typeof data !== "object" ||
          !("version" in data) ||
          data.version !== 1 ||
          !("agents" in data) ||
          !Array.isArray(data.agents)
        )
          return;
        const state = data as Snapshot;
        if (!Array.isArray(state.events) || !state.stats) return;
        setSnapshot(state);
        setConnection("live");
        clearTimeout(timeout);
      } catch {
        /* A damaged message must not take down the campus. */
      }
    };
    source.addEventListener("state", update as EventListener);
    source.onerror = () => {
      clearTimeout(timeout);
      setConnection("offline");
    };
    return () => {
      clearTimeout(timeout);
      source.close();
    };
  }, [demo]);
  return { snapshot, connection };
}
