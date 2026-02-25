import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Search,
  CheckCircle2,
  XCircle,
  AlertCircle,
  GitBranch,
  ChevronDown,
  ChevronRight,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useDataStore,
  type TaskMemory,
  type EvolutionEntry,
} from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

type Tab = "tasks" | "evolution";

const outcomeConfig: Record<
  string,
  { icon: typeof CheckCircle2; color: string; label: string }
> = {
  completed: {
    icon: CheckCircle2,
    color: "text-emerald-500",
    label: "Completed",
  },
  failed: { icon: XCircle, color: "text-red-500", label: "Failed" },
  partial: { icon: AlertCircle, color: "text-amber-500", label: "Partial" },
};

function formatTimestamp(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso.slice(0, 16);
  }
}

export function HistoryPage() {
  const { history, historyLoading, fetchHistory } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [tab, setTab] = useState<Tab>("tasks");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (status === "connected") {
      fetchHistory();
    }
  }, [status, fetchHistory]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              History
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {history
                ? `${history.tasks.length} tasks · ${history.evolution.length} evolutions`
                : "Past activity"}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchHistory}
              disabled={historyLoading}
              className="rounded-md px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
            >
              {historyLoading ? "Loading..." : "Refresh"}
            </button>
            <div className="relative w-72">
              <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search history..."
                className="h-8 pl-9 font-mono text-xs"
              />
            </div>
          </div>
        </div>

        {/* Tab toggle */}
        <div className="mt-3 flex gap-1.5">
          {(["tasks", "evolution"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                tab === t
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {historyLoading && !history ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading history...
              </span>
            </div>
          </div>
        ) : !history ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Connect to gateway to load history
            </span>
          </div>
        ) : tab === "tasks" ? (
          <TasksList tasks={history.tasks} search={search} />
        ) : (
          <EvolutionList evolution={history.evolution} search={search} />
        )}
      </div>
    </div>
  );
}

function TasksList({
  tasks,
  search,
}: {
  tasks: TaskMemory[];
  search: string;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const filtered = tasks.filter(
    (t) =>
      !search ||
      t.goal.toLowerCase().includes(search.toLowerCase()) ||
      t.summary.toLowerCase().includes(search.toLowerCase()) ||
      t.tools_used.some((tool) =>
        tool.toLowerCase().includes(search.toLowerCase())
      )
  );

  if (filtered.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {tasks.length === 0
            ? "No task memories yet"
            : "No tasks match your search"}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {filtered.map((task, i) => {
        const outcome = outcomeConfig[task.outcome] ?? {
          icon: CheckCircle2,
          color: "text-emerald-500",
          label: "Completed",
        };
        const OutcomeIcon = outcome.icon;
        const expanded = expandedIdx === i;

        return (
          <div
            key={`${task.created_at}-${i}`}
            className={cn(
              "rounded-md border border-transparent transition-colors",
              expanded && "border-border/50 bg-card"
            )}
          >
            {/* Collapsed row */}
            <button
              onClick={() => setExpandedIdx(expanded ? null : i)}
              className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-foreground/[3%]"
            >
              {expanded ? (
                <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
              )}
              <OutcomeIcon
                className={cn("size-3.5 shrink-0", outcome.color)}
              />
              <span className="min-w-0 flex-1 truncate font-mono text-xs">
                {task.goal}
              </span>
              {task.tools_used.length > 0 && (
                <Badge
                  variant="outline"
                  className="shrink-0 font-mono text-[7px] uppercase"
                >
                  {task.tools_used.length} tool
                  {task.tools_used.length !== 1 ? "s" : ""}
                </Badge>
              )}
              <Badge
                variant="outline"
                className={cn(
                  "shrink-0 font-mono text-[7px] uppercase",
                  outcome.color
                )}
              >
                {outcome.label}
              </Badge>
              {task.created_at && (
                <span className="shrink-0 font-mono text-[9px] text-muted-foreground/40">
                  {formatTimestamp(task.created_at)}
                </span>
              )}
            </button>

            {/* Expanded detail */}
            {expanded && (
              <div className="border-t border-border/30 px-3 py-3">
                {/* Goal */}
                <div className="mb-3">
                  <h4 className="mb-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                    Goal
                  </h4>
                  <p className="text-xs leading-relaxed">{task.goal}</p>
                </div>

                {/* Summary with markdown */}
                {task.summary && (
                  <div className="mb-3">
                    <h4 className="mb-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                      Summary
                    </h4>
                    <div className="markdown-content rounded-md bg-foreground/[2%] px-3 py-2 text-xs leading-relaxed text-muted-foreground/80">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {task.summary}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}

                {/* Tools used */}
                {task.tools_used.length > 0 && (
                  <div className="mb-3">
                    <h4 className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                      Tools Used
                    </h4>
                    <div className="flex flex-wrap gap-1">
                      {task.tools_used.map((tool) => (
                        <Badge
                          key={tool}
                          variant="outline"
                          className="font-mono text-[8px] uppercase"
                        >
                          {tool}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Timestamp */}
                {task.created_at && (
                  <div className="flex items-center gap-1.5">
                    <Clock className="size-3 text-muted-foreground/40" />
                    <span className="font-mono text-[9px] text-muted-foreground/40">
                      {task.created_at}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EvolutionList({
  evolution,
  search,
}: {
  evolution: EvolutionEntry[];
  search: string;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const filtered = evolution.filter(
    (e) =>
      !search ||
      e.field.toLowerCase().includes(search.toLowerCase()) ||
      e.reason.toLowerCase().includes(search.toLowerCase()) ||
      e.new_value.toLowerCase().includes(search.toLowerCase())
  );

  if (filtered.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {evolution.length === 0
            ? "No identity evolution yet"
            : "No entries match your search"}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {filtered.map((entry, i) => {
        const expanded = expandedIdx === i;

        return (
          <div
            key={`${entry.created_at}-${i}`}
            className={cn(
              "rounded-md border border-transparent transition-colors",
              expanded && "border-border/50 bg-card"
            )}
          >
            {/* Collapsed row */}
            <button
              onClick={() => setExpandedIdx(expanded ? null : i)}
              className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-foreground/[3%]"
            >
              {expanded ? (
                <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
              )}
              <GitBranch className="size-3.5 shrink-0 text-purple-500" />
              <span className="min-w-0 flex-1 truncate font-mono text-xs">
                {entry.field}
              </span>
              <Badge
                variant="outline"
                className="shrink-0 font-mono text-[7px] uppercase text-muted-foreground/60"
              >
                {entry.trigger}
              </Badge>
              {entry.created_at && (
                <span className="shrink-0 font-mono text-[9px] text-muted-foreground/40">
                  {formatTimestamp(entry.created_at)}
                </span>
              )}
            </button>

            {/* Expanded detail */}
            {expanded && (
              <div className="border-t border-border/30 px-3 py-3">
                {entry.reason && (
                  <div className="mb-3">
                    <h4 className="mb-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                      Reason
                    </h4>
                    <p className="text-xs leading-relaxed text-muted-foreground/80">
                      {entry.reason}
                    </p>
                  </div>
                )}

                <div className="space-y-2 rounded-md bg-foreground/[2%] px-3 py-2">
                  {entry.old_value && (
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 font-mono text-xs font-bold text-red-400">
                        −
                      </span>
                      <span className="text-xs leading-relaxed text-muted-foreground/50 line-through">
                        {entry.old_value}
                      </span>
                    </div>
                  )}
                  {entry.new_value && (
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 font-mono text-xs font-bold text-emerald-400">
                        +
                      </span>
                      <span className="text-xs leading-relaxed">
                        {entry.new_value}
                      </span>
                    </div>
                  )}
                </div>

                {entry.created_at && (
                  <div className="mt-2 flex items-center gap-1.5">
                    <Clock className="size-3 text-muted-foreground/40" />
                    <span className="font-mono text-[9px] text-muted-foreground/40">
                      {entry.created_at}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
