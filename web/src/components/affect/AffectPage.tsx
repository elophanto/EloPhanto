import { useEffect } from "react";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";

// PAD channels run roughly -1..+1; render as a centered bar.
function PadBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(-1, Math.min(1, value));
  const widthPct = Math.abs(pct) * 50;
  const positive = pct >= 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between font-mono text-[10px]">
        <span className="uppercase tracking-[0.1em] text-muted-foreground">{label}</span>
        <span className={positive ? "text-emerald-500" : "text-red-500"}>
          {pct >= 0 ? "+" : ""}
          {pct.toFixed(2)}
        </span>
      </div>
      <div className="relative h-1.5 rounded-full bg-foreground/[6%]">
        <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
        <div
          className={cn(
            "absolute top-0 h-full rounded-full",
            positive ? "bg-emerald-500/60" : "bg-red-500/60",
          )}
          style={{
            left: positive ? "50%" : `${50 - widthPct}%`,
            width: `${widthPct}%`,
          }}
        />
      </div>
    </div>
  );
}

export function AffectPage() {
  const { affect, affectLoading, fetchAffect } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchAffect();
      const id = setInterval(fetchAffect, 15000);
      return () => clearInterval(id);
    }
  }, [status, fetchAffect]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Affect</h1>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          State-level emotion — PAD model, decays over minutes-to-hours
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {affectLoading && !affect ? (
          <Empty text="Loading affect..." />
        ) : !affect ? (
          <Empty text="Affect not available." />
        ) : (
          <>
            <div className="rounded-lg border border-border/50 p-5">
              <div className="flex items-center gap-2">
                <Activity className="size-4 text-primary" />
                <span className="font-mono text-lg uppercase tracking-[0.1em]">
                  {affect.label || "equanimity"}
                </span>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground/60">
                  mag {Number(affect.magnitude).toFixed?.(2) ?? affect.magnitude}
                </span>
              </div>
              {affect.description && (
                <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                  {affect.description}
                </p>
              )}
            </div>

            <div className="space-y-3 rounded-lg border border-border/50 p-5">
              <PadBar label="Pleasure" value={affect.pleasure} />
              <PadBar label="Arousal" value={affect.arousal} />
              <PadBar label="Dominance" value={affect.dominance} />
            </div>

            {affect.recent_events.length > 0 && (
              <div className="space-y-2">
                <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  Recent events
                </h2>
                <div className="space-y-1.5">
                  {affect.recent_events
                    .slice()
                    .reverse()
                    .map((e, i) => {
                      const ev = e as Record<string, unknown>;
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 rounded border border-border/40 px-3 py-1.5 font-mono text-[10px]"
                        >
                          <span className="text-foreground/90">
                            {String(ev.label ?? ev.kind ?? "event")}
                          </span>
                          {ev.source != null && (
                            <span className="text-muted-foreground/60">
                              {String(ev.source)}
                            </span>
                          )}
                          {ev.at != null && (
                            <span className="ml-auto text-muted-foreground/40">
                              {String(ev.at)}
                            </span>
                          )}
                        </div>
                      );
                    })}
                </div>
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
    <div className="flex h-40 items-center justify-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {text}
      </span>
    </div>
  );
}
