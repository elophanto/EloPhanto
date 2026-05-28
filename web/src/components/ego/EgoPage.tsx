import { useEffect } from "react";
import { Quote, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";

function relTime(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Confidence → color ramp (red low → amber mid → green high).
function confColor(c: number): string {
  if (c >= 0.75) return "#16a34a";
  if (c >= 0.55) return "#65a30d";
  if (c >= 0.4) return "#d97706";
  return "#dc2626";
}

export function EgoPage() {
  const { ego, egoLoading, fetchEgo } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchEgo();
      const id = setInterval(fetchEgo, 20000);
      return () => clearInterval(id);
    }
  }, [status, fetchEgo]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Ego</h1>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          Self-model — Higgins actual / ideal / ought, measured confidence
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {egoLoading && !ego ? (
          <Empty text="Loading ego..." />
        ) : !ego ? (
          <Empty text="Ego not available." />
        ) : (
          <div className="mx-auto max-w-4xl space-y-6">
            {/* Coherence + confidence headline */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <CoherenceCard coherence={ego.coherence} />
              <Stat
                label="Avg confidence"
                value={ego.confidence_avg.toFixed(2)}
                hint={`spread ${ego.confidence_min.toFixed(2)}–${ego.confidence_max.toFixed(2)}`}
              />
              <Stat
                label="Humbling events"
                value={String(ego.humbling_count)}
                hint="logged corrections / failures"
              />
            </div>

            {/* Self-image — the first-person inner monologue */}
            {ego.self_image && (
              <SelfBlock
                icon={Quote}
                title="How I see myself (actual)"
                body={ego.self_image}
                accent
              />
            )}

            {/* The three selves */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {ego.ideal_self && (
                <SelfBlock
                  title="Ideal self"
                  subtitle="who I hope to be — the gap voices dejection"
                  body={ego.ideal_self}
                />
              )}
              {ego.ought_self && (
                <SelfBlock
                  title="Ought self"
                  subtitle="who I should be — the gap voices agitation"
                  body={ego.ought_self}
                />
              )}
            </div>

            {ego.self_critique && (
              <SelfBlock title="Self-critique" body={ego.self_critique} />
            )}

            {/* Per-capability confidence */}
            <div className="space-y-3">
              <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                Capability confidence ({ego.capabilities.length})
              </h2>
              {ego.capabilities.length === 0 ? (
                <Muted text="No measured capabilities yet — confidence forms as the agent works." />
              ) : (
                <div className="space-y-1.5">
                  {ego.capabilities.map((c) => (
                    <div key={c.name} className="flex items-center gap-3">
                      <span className="w-44 shrink-0 truncate font-mono text-[11px] text-foreground/80">
                        {c.name}
                      </span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-foreground/[6%]">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.round(c.confidence * 100)}%`,
                            background: confColor(c.confidence),
                          }}
                        />
                      </div>
                      <span
                        className="w-10 shrink-0 text-right font-mono text-[10px]"
                        style={{ color: confColor(c.confidence) }}
                      >
                        {c.confidence.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Humbling events — the evidence that moved confidence */}
            {ego.humbling_events.length > 0 && (
              <div className="space-y-2">
                <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  Recent humbling events
                </h2>
                <div className="space-y-1.5">
                  {ego.humbling_events.map((h, i) => (
                    <div
                      key={`${h.created_at}-${i}`}
                      className="rounded-md border border-border/40 px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <TrendingDown className="size-3 text-red-500" />
                        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-foreground/80">
                          {h.capability}
                        </span>
                        <span className="ml-auto font-mono text-[9px] text-muted-foreground/40">
                          {relTime(h.created_at)}
                        </span>
                      </div>
                      {(h.claimed || h.actual) && (
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                          claimed <span className="text-foreground/70">{h.claimed || "—"}</span>
                          {" · "}got <span className="text-red-500/80">{h.actual || "—"}</span>
                        </p>
                      )}
                      {h.task_goal && (
                        <p className="mt-0.5 truncate text-[10px] text-muted-foreground/50">
                          {h.task_goal}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CoherenceCard({ coherence }: { coherence: number }) {
  const pct = Math.round(coherence * 100);
  const color =
    coherence >= 0.8 ? "#16a34a" : coherence >= 0.55 ? "#d97706" : "#dc2626";
  return (
    <div className="rounded-lg border border-border/50 p-4">
      <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
        Coherence
      </p>
      <p className="mt-1 font-mono text-2xl" style={{ color }}>
        {coherence.toFixed(2)}
      </p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-foreground/[6%]">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <p className="mt-1.5 font-mono text-[9px] text-muted-foreground/50">
        alignment of claims vs measured behavior
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border/50 p-4">
      <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
        {label}
      </p>
      <p className="mt-1 font-mono text-2xl">{value}</p>
      {hint && (
        <p className="mt-1.5 font-mono text-[9px] text-muted-foreground/50">{hint}</p>
      )}
    </div>
  );
}

function SelfBlock({
  icon: Icon,
  title,
  subtitle,
  body,
  accent,
}: {
  icon?: typeof Quote;
  title: string;
  subtitle?: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        accent ? "border-primary/30 bg-primary/[3%]" : "border-border/50",
      )}
    >
      <div className="flex items-center gap-2">
        {Icon && <Icon className="size-3.5 text-muted-foreground" />}
        <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
          {title}
        </h2>
      </div>
      {subtitle && (
        <p className="mt-0.5 font-mono text-[9px] text-muted-foreground/50">
          {subtitle}
        </p>
      )}
      <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90">
        {body}
      </p>
    </div>
  );
}

function Muted({ text }: { text: string }) {
  return <p className="font-mono text-[11px] text-muted-foreground/60">{text}</p>;
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {text}
      </span>
    </div>
  );
}
