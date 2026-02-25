import { useEffect } from "react";
import {
  Brain,
  Target,
  Calendar,
  Radio,
  Wrench,
  Sparkles,
  BookOpen,
  Users,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";

export function DashboardPage() {
  const { dashboard, dashboardLoading, fetchDashboard } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchDashboard();
    }
  }, [status, fetchDashboard]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              {dashboard?.identity?.display_name || "Dashboard"}
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {dashboard?.identity?.purpose || "Agent overview"}
            </p>
          </div>
          <button
            onClick={fetchDashboard}
            disabled={dashboardLoading}
            className="rounded-md px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
          >
            {dashboardLoading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {dashboardLoading && !dashboard ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading dashboard...
              </span>
            </div>
          </div>
        ) : !dashboard ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Connect to gateway to load dashboard
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
            <MindCard mind={dashboard.mind} />
            <GoalsCard goals={dashboard.goals} />
            <StatsCard stats={dashboard.stats} />
            <ScheduleCard schedules={dashboard.schedules} />
            <ChannelsCard channels={dashboard.channels} />
            <SwarmCard swarm={dashboard.swarm} />
            {dashboard.identity?.capabilities &&
              dashboard.identity.capabilities.length > 0 && (
                <CapabilitiesCard
                  capabilities={dashboard.identity.capabilities}
                />
              )}
          </div>
        )}
      </div>
    </div>
  );
}

function MindCard({
  mind,
}: {
  mind: NonNullable<ReturnType<typeof useDataStore.getState>["dashboard"]>["mind"];
}) {
  if (!mind) {
    return (
      <DashboardCard icon={Brain} title="Mind" subtitle="Not enabled">
        <p className="text-xs text-muted-foreground/60">
          Enable autonomous_mind in config.yaml
        </p>
      </DashboardCard>
    );
  }

  const state = mind.paused ? "paused" : mind.running ? "active" : "stopped";
  const stateColor =
    state === "active"
      ? "text-emerald-500"
      : state === "paused"
        ? "text-amber-500"
        : "text-muted-foreground/50";
  const budgetPct =
    mind.budget_total > 0
      ? Math.round((mind.budget_spent / mind.budget_total) * 100)
      : 0;

  return (
    <DashboardCard icon={Brain} title="Mind" subtitle={state}>
      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            State
          </span>
          <span className={cn("font-mono text-xs font-medium", stateColor)}>
            {state}
          </span>
        </div>

        {/* Budget bar */}
        <div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Budget
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">
              ${mind.budget_spent.toFixed(4)} / ${mind.budget_total.toFixed(2)}
            </span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-foreground/5">
            <div
              className="h-full rounded-full bg-foreground/20 transition-all"
              style={{ width: `${Math.min(budgetPct, 100)}%` }}
            />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Cycles
          </span>
          <span className="font-mono text-xs">{mind.cycle_count}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Next wakeup
          </span>
          <span className="font-mono text-xs">
            {mind.next_wakeup_sec > 0
              ? `${Math.round(mind.next_wakeup_sec)}s`
              : "—"}
          </span>
        </div>

        {mind.last_action && (
          <div className="border-t border-border/30 pt-2">
            <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Last action
            </span>
            <p className="mt-0.5 text-xs text-muted-foreground/80">
              {mind.last_action.slice(0, 100)}
            </p>
          </div>
        )}
      </div>
    </DashboardCard>
  );
}

function GoalsCard({
  goals,
}: {
  goals: NonNullable<
    ReturnType<typeof useDataStore.getState>["dashboard"]
  >["goals"];
}) {
  const activeGoals = goals.filter(
    (g) => g.status === "active" || g.status === "planning"
  );

  return (
    <DashboardCard
      icon={Target}
      title="Goals"
      subtitle={`${activeGoals.length} active`}
    >
      {goals.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">No goals created yet</p>
      ) : (
        <div className="space-y-2">
          {goals.slice(0, 5).map((g) => (
            <div key={g.goal_id} className="space-y-1">
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs leading-tight">
                  {g.goal.slice(0, 60)}
                  {g.goal.length > 60 ? "..." : ""}
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    "shrink-0 font-mono text-[7px] uppercase",
                    g.status === "active" && "border-emerald-500/30 text-emerald-500",
                    g.status === "completed" && "border-blue-500/30 text-blue-500",
                    g.status === "failed" && "border-red-500/30 text-red-500",
                    g.status === "paused" && "border-amber-500/30 text-amber-500"
                  )}
                >
                  {g.status}
                </Badge>
              </div>
              {g.total_checkpoints > 0 && (
                <div className="h-1 overflow-hidden rounded-full bg-foreground/5">
                  <div
                    className="h-full rounded-full bg-foreground/20 transition-all"
                    style={{
                      width: `${Math.round((g.current_checkpoint / g.total_checkpoints) * 100)}%`,
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </DashboardCard>
  );
}

function StatsCard({
  stats,
}: {
  stats: NonNullable<
    ReturnType<typeof useDataStore.getState>["dashboard"]
  >["stats"];
}) {
  return (
    <DashboardCard icon={Activity} title="Stats" subtitle="System overview">
      <div className="space-y-2">
        <StatRow icon={Wrench} label="Tools" value={stats.tools_count} />
        <StatRow icon={Sparkles} label="Skills" value={stats.skills_count} />
        <StatRow
          icon={BookOpen}
          label="Knowledge chunks"
          value={stats.knowledge_chunks}
        />
      </div>
    </DashboardCard>
  );
}

function ScheduleCard({
  schedules,
}: {
  schedules: NonNullable<
    ReturnType<typeof useDataStore.getState>["dashboard"]
  >["schedules"];
}) {
  return (
    <DashboardCard
      icon={Calendar}
      title="Schedules"
      subtitle={`${schedules.enabled} enabled`}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Total
          </span>
          <span className="font-mono text-xs">{schedules.total}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Enabled
          </span>
          <span className="font-mono text-xs">{schedules.enabled}</span>
        </div>
        {schedules.next_run && (
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Next run
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">
              {schedules.next_run}
            </span>
          </div>
        )}
      </div>
    </DashboardCard>
  );
}

function ChannelsCard({
  channels,
}: {
  channels: NonNullable<
    ReturnType<typeof useDataStore.getState>["dashboard"]
  >["channels"];
}) {
  // Group by channel type for a compact view
  const grouped: Record<string, number> = {};
  for (const c of channels) {
    const key = c.channel || "web";
    grouped[key] = (grouped[key] ?? 0) + 1;
  }

  return (
    <DashboardCard
      icon={Radio}
      title="Channels"
      subtitle={`${channels.length} connected`}
    >
      {channels.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">No clients connected</p>
      ) : (
        <div className="space-y-1.5">
          {Object.entries(grouped).map(([channel, count]) => (
            <div key={channel} className="flex items-center gap-2">
              <span className="status-dot status-connected shrink-0" />
              <span className="font-mono text-xs">{channel}</span>
              {count > 1 && (
                <span className="font-mono text-[10px] text-muted-foreground/50">
                  ×{count}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </DashboardCard>
  );
}

function SwarmCard({
  swarm,
}: {
  swarm: NonNullable<
    ReturnType<typeof useDataStore.getState>["dashboard"]
  >["swarm"];
}) {
  const running = swarm.filter(
    (a) => a.status === "running"
  );

  return (
    <DashboardCard
      icon={Users}
      title="Swarm"
      subtitle={`${running.length} running`}
    >
      {swarm.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">No agents spawned</p>
      ) : (
        <div className="space-y-1.5">
          {swarm.slice(0, 5).map((a) => (
            <div key={a.agent_id} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "status-dot shrink-0",
                    a.status === "running"
                      ? "status-connected"
                      : "status-disconnected"
                  )}
                />
                <span className="font-mono text-xs">
                  {a.task?.slice(0, 40) || a.profile}
                </span>
              </div>
              <Badge
                variant="outline"
                className="font-mono text-[7px] uppercase"
              >
                {a.status}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </DashboardCard>
  );
}

function CapabilitiesCard({ capabilities }: { capabilities: string[] }) {
  return (
    <DashboardCard
      icon={Sparkles}
      title="Capabilities"
      subtitle={`${capabilities.length} learned`}
    >
      <div className="flex flex-wrap gap-1">
        {capabilities.map((cap) => (
          <Badge
            key={cap}
            variant="outline"
            className="font-mono text-[8px] uppercase"
          >
            {cap}
          </Badge>
        ))}
      </div>
    </DashboardCard>
  );
}

// --- Shared sub-components ---

function DashboardCard({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: typeof Brain;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="crop-marks overflow-hidden rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          {title}
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {subtitle}
        </span>
      </div>
      {children}
    </div>
  );
}

function StatRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Wrench;
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Icon className="size-3 text-muted-foreground/50" />
        <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </span>
      </div>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}
