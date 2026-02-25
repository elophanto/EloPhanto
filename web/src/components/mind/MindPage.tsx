import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Brain,
  Play,
  Square,
  Clock,
  Zap,
  StickyNote,
  Activity,
  AlertTriangle,
  Settings2,
  Pause,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type MindEvent } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";

export function MindPage() {
  const {
    mind,
    mindLoading,
    fetchMind,
    mindEvents,
    sendMindControl,
  } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchMind();
    }
  }, [status, fetchMind]);

  // Auto-refresh every 15s when the mind is running
  useEffect(() => {
    if (status !== "connected" || !mind?.running) return;
    const interval = setInterval(fetchMind, 15000);
    return () => clearInterval(interval);
  }, [status, mind?.running, fetchMind]);

  const state = !mind || mind.enabled === false
    ? "disabled"
    : mind.paused
      ? "paused"
      : mind.running
        ? "active"
        : "stopped";

  const stateColor =
    state === "active"
      ? "text-emerald-500"
      : state === "paused"
        ? "text-amber-500"
        : state === "disabled"
          ? "text-muted-foreground/40"
          : "text-red-400";

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
                Autonomous Mind
              </h1>
              <Badge
                variant="outline"
                className={cn(
                  "font-mono text-[8px] uppercase",
                  stateColor
                )}
              >
                {state}
              </Badge>
            </div>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {mind?.enabled !== false && mind?.cycle_count != null
                ? `${mind.cycle_count} cycles · $${(mind.budget_spent ?? 0).toFixed(4)} spent`
                : "Background autonomous operations"}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {mind?.enabled !== false && (
              <>
                {mind?.running ? (
                  <button
                    onClick={() => sendMindControl("stop")}
                    className="flex items-center gap-1.5 rounded-md border border-red-500/20 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-red-400 transition-colors hover:bg-red-500/10"
                  >
                    <Square className="size-3" />
                    Stop
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      sendMindControl("start");
                      setTimeout(fetchMind, 500);
                    }}
                    className="flex items-center gap-1.5 rounded-md border border-emerald-500/20 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-emerald-500 transition-colors hover:bg-emerald-500/10"
                  >
                    <Play className="size-3" />
                    Start
                  </button>
                )}
              </>
            )}
            <button
              onClick={fetchMind}
              disabled={mindLoading}
              className="rounded-md px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
            >
              {mindLoading ? "Loading..." : "Refresh"}
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {mindLoading && !mind ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading mind status...
              </span>
            </div>
          </div>
        ) : !mind || mind.enabled === false ? (
          <div className="flex h-32 items-center justify-center">
            <div className="text-center">
              <Brain className="mx-auto mb-2 size-6 text-muted-foreground/30" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Autonomous mind is not enabled
              </span>
              <p className="mt-1 font-mono text-[9px] text-muted-foreground/50">
                Set autonomous_mind.enabled: true in config.yaml
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Top row: Status + Budget + Config */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <StatusCard mind={mind} state={state} stateColor={stateColor} />
              <BudgetCard mind={mind} />
              <ConfigCard mind={mind} />
            </div>

            {/* Scratchpad */}
            {mind.scratchpad && (
              <ScratchpadCard scratchpad={mind.scratchpad} />
            )}

            {/* Bottom row: Recent Actions + Live Events */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <ActionsCard actions={mind.recent_actions ?? []} />
              <EventsCard events={mindEvents} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Cards ---

function StatusCard({
  mind,
  state,
  stateColor,
}: {
  mind: NonNullable<ReturnType<typeof useDataStore.getState>["mind"]>;
  state: string;
  stateColor: string;
}) {
  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Brain className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Status
        </h3>
      </div>
      <div className="space-y-2.5">
        <Row label="State">
          <span className={cn("font-mono text-xs font-medium", stateColor)}>
            {state}
          </span>
        </Row>
        <Row label="Cycles">
          <span className="font-mono text-xs">{mind.cycle_count ?? 0}</span>
        </Row>
        <Row label="Last wakeup">
          <span className="font-mono text-xs">
            {mind.last_wakeup || "—"}
          </span>
        </Row>
        <Row label="Next wakeup">
          <span className="font-mono text-xs">
            {mind.next_wakeup_sec != null && mind.next_wakeup_sec > 0
              ? `${Math.round(mind.next_wakeup_sec)}s`
              : "—"}
          </span>
        </Row>
        <Row label="Pending events">
          <span className="font-mono text-xs">
            {mind.pending_events ?? 0}
          </span>
        </Row>
        {mind.last_action && (
          <div className="border-t border-border/30 pt-2">
            <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Last action
            </span>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground/80">
              {mind.last_action}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function BudgetCard({
  mind,
}: {
  mind: NonNullable<ReturnType<typeof useDataStore.getState>["mind"]>;
}) {
  const spent = mind.budget_spent ?? 0;
  const total = mind.budget_total ?? 0;
  const remaining = mind.budget_remaining ?? 0;
  const pct = total > 0 ? Math.round((spent / total) * 100) : 0;
  const barColor =
    pct > 80
      ? "bg-red-500/40"
      : pct > 50
        ? "bg-amber-500/30"
        : "bg-foreground/20";

  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Activity className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Budget
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {pct}% used
        </span>
      </div>
      <div className="space-y-2.5">
        {/* Budget bar */}
        <div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs">${spent.toFixed(4)}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              / ${total.toFixed(2)}
            </span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-foreground/5">
            <div
              className={cn("h-full rounded-full transition-all", barColor)}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
        </div>
        <Row label="Remaining">
          <span className="font-mono text-xs">${remaining.toFixed(4)}</span>
        </Row>
        <Row label="Allocation">
          <span className="font-mono text-xs">
            {mind.config?.budget_pct ?? "—"}% of daily budget
          </span>
        </Row>
      </div>
    </div>
  );
}

function ConfigCard({
  mind,
}: {
  mind: NonNullable<ReturnType<typeof useDataStore.getState>["mind"]>;
}) {
  const cfg = mind.config;

  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Settings2 className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Config
        </h3>
      </div>
      {cfg ? (
        <div className="space-y-2.5">
          <Row label="Wakeup interval">
            <span className="font-mono text-xs">{cfg.wakeup_seconds}s</span>
          </Row>
          <Row label="Min / Max">
            <span className="font-mono text-xs">
              {cfg.min_wakeup_seconds}s – {cfg.max_wakeup_seconds}s
            </span>
          </Row>
          <Row label="Max rounds">
            <span className="font-mono text-xs">
              {cfg.max_rounds_per_wakeup} per cycle
            </span>
          </Row>
          <Row label="Verbosity">
            <Badge
              variant="outline"
              className="font-mono text-[7px] uppercase"
            >
              {cfg.verbosity}
            </Badge>
          </Row>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/60">
          Config not available
        </p>
      )}
    </div>
  );
}

function ScratchpadCard({ scratchpad }: { scratchpad: string }) {
  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <StickyNote className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Scratchpad
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          Working memory
        </span>
      </div>
      <div className="markdown-content max-h-64 overflow-y-auto rounded-md bg-foreground/[2%] px-3 py-2 text-xs leading-relaxed text-muted-foreground/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {scratchpad}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function ActionsCard({
  actions,
}: {
  actions: { ts: string; summary: string }[];
}) {
  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Clock className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Recent Actions
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {actions.length}
        </span>
      </div>
      {actions.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          No actions recorded yet
        </p>
      ) : (
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {[...actions].reverse().map((a, i) => (
            <div
              key={`${a.ts}-${i}`}
              className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-foreground/[3%]"
            >
              <span className="shrink-0 font-mono text-[9px] text-muted-foreground/40">
                {a.ts}
              </span>
              <span className="text-xs leading-relaxed text-muted-foreground/80">
                {a.summary}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EventsCard({ events }: { events: MindEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  const eventConfig: Record<
    string,
    { icon: typeof Zap; color: string; label: string }
  > = {
    mind_wakeup: { icon: Zap, color: "text-blue-400", label: "Wakeup" },
    mind_action: { icon: Activity, color: "text-emerald-400", label: "Action" },
    mind_sleep: { icon: Pause, color: "text-muted-foreground", label: "Sleep" },
    mind_paused: {
      icon: Pause,
      color: "text-amber-400",
      label: "Paused",
    },
    mind_resumed: { icon: Play, color: "text-emerald-400", label: "Resumed" },
    mind_error: {
      icon: AlertTriangle,
      color: "text-red-400",
      label: "Error",
    },
    mind_tool_use: { icon: Zap, color: "text-purple-400", label: "Tool" },
  };

  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Zap className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Live Events
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {events.length}
        </span>
      </div>
      {events.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          Events will appear here in real-time
        </p>
      ) : (
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {events.map((e, i) => {
            const cfg = eventConfig[e.type] ?? {
              icon: Zap,
              color: "text-muted-foreground",
              label: e.type,
            };
            const Icon = cfg.icon;
            const time = new Date(e.timestamp).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
              hour12: false,
            });

            // Extract a summary from event data
            const summary =
              (e.data.summary as string) ||
              (e.data.tool as string) ||
              (e.data.error as string) ||
              (e.data.last_action as string) ||
              "";

            return (
              <div
                key={`${e.timestamp}-${i}`}
                className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-foreground/[3%]"
              >
                <Icon className={cn("mt-0.5 size-3 shrink-0", cfg.color)} />
                <Badge
                  variant="outline"
                  className={cn(
                    "shrink-0 font-mono text-[7px] uppercase",
                    cfg.color
                  )}
                >
                  {cfg.label}
                </Badge>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground/80">
                  {summary}
                </span>
                <span className="shrink-0 font-mono text-[9px] text-muted-foreground/40">
                  {time}
                </span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

// --- Shared ---

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}
