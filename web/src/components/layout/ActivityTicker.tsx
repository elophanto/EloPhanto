import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useActivityStore } from "@/stores/activity";
import { useConnectionStore } from "@/stores/connection";

// Window (ms) after the last activity within which the agent is
// considered "actively working" → pulsing dot. After this it's idle.
const ACTIVE_WINDOW_MS = 8000;

function relTime(at: number, now: number): string {
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 2) return "now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

/**
 * Persistent, always-visible activity strip at the bottom of the main
 * area. Mirrors the terminal dashboard's live feed: a status dot + the
 * agent's most recent action, on every page — so "is it alive right
 * now?" is ambient rather than buried on the Mind page.
 */
export function ActivityTicker() {
  const latest = useActivityStore((s) => s.latest);
  const status = useConnectionStore((s) => s.status);

  // Tick once a second so the relative time + active/idle state stay
  // fresh without a new event.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const active = latest != null && now - latest.at < ACTIVE_WINDOW_MS;

  let dotClass = "bg-muted-foreground/40";
  let statusLabel = "idle";
  if (status !== "connected") {
    dotClass = "bg-red-500";
    statusLabel = status;
  } else if (active) {
    dotClass = "bg-emerald-500 animate-pulse";
    statusLabel = latest!.kind === "mind" ? "thinking" : "working";
  }

  return (
    <div className="flex h-7 shrink-0 items-center gap-2.5 border-t border-border/50 bg-card/40 px-4">
      <span className={cn("size-1.5 shrink-0 rounded-full", dotClass)} />
      <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
        {statusLabel}
      </span>
      {latest ? (
        <>
          <span className="shrink-0 font-mono text-[10px] text-foreground/80">
            {latest.label || "—"}
          </span>
          {latest.detail && (
            <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground/70">
              {latest.detail}
            </span>
          )}
          <span className="ml-auto shrink-0 font-mono text-[9px] text-muted-foreground/40">
            {relTime(latest.at, now)}
          </span>
        </>
      ) : (
        <span className="font-mono text-[10px] text-muted-foreground/40">
          {status === "connected"
            ? "waiting for activity…"
            : "not connected"}
        </span>
      )}
    </div>
  );
}
