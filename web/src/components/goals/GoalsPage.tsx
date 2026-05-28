import { useEffect, useState } from "react";
import { Target, ArrowLeft, CheckCircle2, Circle, XCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { PaginationBar } from "@/components/ui/pagination";
import { usePagination } from "@/hooks/use-pagination";

const STATUS_COLOR: Record<string, string> = {
  planning: "text-amber-500",
  active: "text-emerald-500",
  paused: "text-amber-500",
  completed: "text-blue-500",
  failed: "text-red-500",
  cancelled: "text-muted-foreground/50",
};

const FILTERS = ["all", "active", "paused", "completed", "failed", "cancelled"] as const;

export function GoalsPage() {
  const {
    goalsList,
    goalsListLoading,
    fetchGoals,
    goalDetail,
    goalDetailLoading,
    fetchGoalDetail,
    clearGoalDetail,
  } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");

  useEffect(() => {
    if (status === "connected") fetchGoals();
  }, [status, fetchGoals]);

  if (goalDetail || goalDetailLoading) {
    return <GoalDetailView loading={goalDetailLoading} onBack={clearGoalDetail} />;
  }

  const filtered =
    filter === "all" ? goalsList : goalsList.filter((g) => g.status === filter);
  const pag = usePagination(filtered, 25);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Goals</h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {goalsList.length} goal{goalsList.length !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                  filter === f
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {goalsListLoading && goalsList.length === 0 ? (
          <Empty text="Loading goals..." />
        ) : filtered.length === 0 ? (
          <Empty text="No goals. The agent creates them via `goal_create` — say 'set a goal to ...' in chat." />
        ) : (
          <div className="space-y-2">
            {pag.pageItems.map((g) => (
              <button
                key={g.goal_id}
                onClick={() => fetchGoalDetail(g.goal_id)}
                className="flex w-full items-center gap-3 rounded-lg border border-border/50 px-4 py-3 text-left transition-colors hover:border-border hover:bg-foreground/[2%]"
              >
                <Target className={cn("size-3.5 shrink-0", STATUS_COLOR[g.status])} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs">{g.goal}</p>
                  <p className="font-mono text-[9px] text-muted-foreground/50">
                    {g.goal_id}
                    {g.role ? ` · ${g.role}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3 font-mono text-[10px]">
                  <span className="text-muted-foreground/60">
                    {g.total_checkpoints
                      ? `${g.current_checkpoint}/${g.total_checkpoints}`
                      : "—"}
                  </span>
                  <span className="text-muted-foreground/60">
                    ${g.cost_usd.toFixed(2)}
                  </span>
                  <Badge variant="outline" className={cn("text-[8px]", STATUS_COLOR[g.status])}>
                    {g.status}
                  </Badge>
                </div>
              </button>
            ))}
            <PaginationBar {...pag} noun="goal" />
          </div>
        )}
      </div>
    </div>
  );
}

function GoalDetailView({ loading, onBack }: { loading: boolean; onBack: () => void }) {
  const detail = useDataStore((s) => s.goalDetail);
  const cpIcon = (s: string) =>
    s === "completed" ? CheckCircle2 : s === "failed" ? XCircle : s === "active" ? Loader2 : Circle;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border/50 px-6 py-4">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Goals
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
        {loading || !detail ? (
          <Empty text="Loading goal..." />
        ) : (
          <>
            <div>
              <p className="text-sm">{detail.goal}</p>
              <div className="mt-2 flex flex-wrap gap-3 font-mono text-[10px] text-muted-foreground/70">
                <span className={STATUS_COLOR[detail.status]}>{detail.status}</span>
                <span>
                  {detail.current_checkpoint}/{detail.total_checkpoints} checkpoints
                </span>
                <span>{detail.llm_calls} LLM calls</span>
                <span>${detail.cost_usd.toFixed(4)}</span>
                {detail.role && <span>role: {detail.role}</span>}
                {detail.mission_id && <span>mission: {detail.mission_id}</span>}
              </div>
            </div>

            {detail.checkpoints.length > 0 && (
              <div className="space-y-1.5">
                <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  Checkpoints
                </h2>
                {detail.checkpoints.map((c) => {
                  const Icon = cpIcon(c.status);
                  return (
                    <div key={c.order} className="flex gap-2.5 rounded border border-border/40 px-3 py-2">
                      <Icon
                        className={cn(
                          "mt-0.5 size-3.5 shrink-0",
                          c.status === "completed" && "text-emerald-500",
                          c.status === "failed" && "text-red-500",
                          c.status === "active" && "text-blue-500 animate-spin",
                          c.status === "pending" && "text-muted-foreground/40",
                        )}
                      />
                      <div className="min-w-0">
                        <p className="text-[11px]">
                          {c.order}. {c.title}
                        </p>
                        {c.success_criteria && (
                          <p className="font-mono text-[10px] text-muted-foreground/50">
                            {c.success_criteria}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {detail.context_summary && (
              <div className="space-y-2">
                <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  Context summary
                </h2>
                <p className="text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap">
                  {detail.context_summary}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center px-8 text-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {text}
      </span>
    </div>
  );
}
