import { useEffect, useState } from "react";
import {
  Search,
  Calendar,
  Clock,
  CheckCircle2,
  XCircle,
  MinusCircle,
  Play,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type ScheduleInfo } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const statusConfig: Record<
  string,
  { icon: typeof CheckCircle2; color: string; label: string }
> = {
  success: { icon: CheckCircle2, color: "text-emerald-500", label: "Success" },
  failed: { icon: XCircle, color: "text-red-500", label: "Failed" },
  never_run: { icon: MinusCircle, color: "text-muted-foreground/50", label: "Never run" },
  running: { icon: Play, color: "text-blue-500", label: "Running" },
};

type FilterStatus = "all" | "enabled" | "disabled";

export function SchedulePage() {
  const { schedules, schedulesLoading, fetchSchedules } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<FilterStatus>("all");
  const [expandedSchedule, setExpandedSchedule] = useState<string | null>(null);

  useEffect(() => {
    if (status === "connected") {
      fetchSchedules();
    }
  }, [status, fetchSchedules]);

  const filtered = schedules.filter((s) => {
    const matchesSearch =
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.task_goal.toLowerCase().includes(search.toLowerCase());
    const matchesFilter =
      filterStatus === "all" ||
      (filterStatus === "enabled" && s.enabled) ||
      (filterStatus === "disabled" && !s.enabled);
    return matchesSearch && matchesFilter;
  });

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Schedules
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {schedules.length} scheduled task
              {schedules.length !== 1 ? "s" : ""}
            </p>
          </div>

          <div className="relative w-72">
            <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search schedules..."
              className="h-8 pl-9 font-mono text-xs"
            />
          </div>
        </div>

        {/* Status filters */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(["all", "enabled", "disabled"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilterStatus(f)}
              className={cn(
                "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                filterStatus === f
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Schedule list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {schedulesLoading ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading schedules...
              </span>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {schedules.length === 0
                ? "No scheduled tasks yet"
                : "No schedules match your search"}
            </span>
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map((schedule) => (
              <ScheduleRow
                key={schedule.id}
                schedule={schedule}
                expanded={expandedSchedule === schedule.id}
                onToggle={() =>
                  setExpandedSchedule(
                    expandedSchedule === schedule.id ? null : schedule.id
                  )
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ScheduleRow({
  schedule,
  expanded,
  onToggle,
}: {
  schedule: ScheduleInfo;
  expanded: boolean;
  onToggle: () => void;
}) {
  const statusCfg = statusConfig[schedule.last_status] ?? { icon: MinusCircle, color: "text-muted-foreground/50", label: "Unknown" };
  const StatusIcon = statusCfg.icon;

  return (
    <div
      className={cn(
        "rounded-md border border-transparent transition-colors",
        expanded && "border-border/50 bg-card"
      )}
    >
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-foreground/[3%]"
      >
        <StatusIcon className={cn("size-3.5 shrink-0", statusCfg.color)} />
        <span className="min-w-0 flex-1">
          <span className="font-mono text-xs">{schedule.name}</span>
          <span className="ml-2 text-xs text-muted-foreground/60">
            {schedule.cron_expression}
          </span>
        </span>
        <Badge
          variant="outline"
          className={cn(
            "shrink-0 font-mono text-[7px] uppercase",
            schedule.enabled
              ? "border-emerald-500/30 text-emerald-500"
              : "border-muted-foreground/30 text-muted-foreground/50"
          )}
        >
          {schedule.enabled ? "enabled" : "disabled"}
        </Badge>
      </button>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-3">
          <div className="space-y-2">
            {schedule.description && (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {schedule.description}
              </p>
            )}

            <div>
              <h4 className="mb-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                Task Goal
              </h4>
              <p className="text-xs text-muted-foreground/80">
                {schedule.task_goal}
              </p>
            </div>

            <div className="flex flex-wrap gap-4">
              <div className="flex items-center gap-1.5">
                <Calendar className="size-3 text-muted-foreground/50" />
                <span className="font-mono text-[10px] text-muted-foreground">
                  Cron: {schedule.cron_expression}
                </span>
              </div>

              {schedule.next_run_at && (
                <div className="flex items-center gap-1.5">
                  <Clock className="size-3 text-muted-foreground/50" />
                  <span className="font-mono text-[10px] text-muted-foreground">
                    Next: {schedule.next_run_at}
                  </span>
                </div>
              )}

              {schedule.last_run_at && (
                <div className="flex items-center gap-1.5">
                  <StatusIcon
                    className={cn("size-3", statusCfg.color)}
                  />
                  <span className="font-mono text-[10px] text-muted-foreground">
                    Last: {schedule.last_run_at}
                  </span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[9px] text-muted-foreground/40">
                Created: {schedule.created_at}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
