/**
 * MindFeed — chat-styled live stream of autonomous-mode activity.
 *
 * Two variants share the same renderer:
 *   <MindFeed />          — full-height, dominant chat surface. Used as
 *                           the Mind page's primary content.
 *   <MindFeedCompact />   — last 5 events, slim card with a "view live"
 *                           CTA. Used on the Dashboard so autonomous
 *                           activity is the first thing visible.
 *
 * Why a chat shape (vs the old indented list):
 * - Autonomous cycles ARE a conversation the agent is having with
 *   itself (wakeup → think → act → reflect → sleep). Bubbles per
 *   event with timestamps make the cadence legible at a glance.
 * - Auto-scroll + "jump to live" lets you stay in real-time or scroll
 *   back without losing position when new events land.
 * - Per-event color/icon means glance-readable: green = action,
 *   purple = tool call, amber = paused, red = error.
 */
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  Brain,
  Pause,
  Play,
  Wrench,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type MindEvent } from "@/stores/data";
import { useNavigationStore } from "@/stores/navigation";

interface EventStyle {
  icon: typeof Zap;
  color: string; // foreground color (text-...)
  rail: string; // left-rail accent color (border-...)
  label: string;
}

const STYLE_FALLBACK: EventStyle = {
  icon: Activity,
  color: "text-muted-foreground",
  rail: "border-muted-foreground/30",
  label: "event",
};

const EVENT_STYLES: Record<string, EventStyle> = {
  mind_wakeup: {
    icon: Zap,
    color: "text-sky-400",
    rail: "border-sky-400/40",
    label: "wakeup",
  },
  mind_action: {
    icon: Activity,
    color: "text-emerald-400",
    rail: "border-emerald-400/40",
    label: "action",
  },
  mind_tool_use: {
    icon: Wrench,
    color: "text-purple-400",
    rail: "border-purple-400/40",
    label: "tool",
  },
  mind_sleep: {
    icon: Pause,
    color: "text-muted-foreground",
    rail: "border-muted-foreground/30",
    label: "sleep",
  },
  mind_paused: {
    icon: Pause,
    color: "text-amber-400",
    rail: "border-amber-400/40",
    label: "paused",
  },
  mind_resumed: {
    icon: Play,
    color: "text-emerald-400",
    rail: "border-emerald-400/40",
    label: "resumed",
  },
  mind_error: {
    icon: AlertTriangle,
    color: "text-red-400",
    rail: "border-red-400/40",
    label: "error",
  },
};

function styleFor(eventType: string): EventStyle {
  return EVENT_STYLES[eventType] ?? { ...STYLE_FALLBACK, label: eventType };
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** Pull the most informative text out of a heterogeneous event payload. */
function summarizeEvent(e: MindEvent): { title: string; detail?: string } {
  const d = e.data;
  // Tool calls — show tool name + a short param snippet
  if (e.type === "mind_tool_use") {
    const tool = (d.tool as string) || "unknown_tool";
    const thought = (d.thought as string) || "";
    return { title: tool, detail: thought ? thought.slice(0, 240) : undefined };
  }
  // Wakeup — show the cycle's reason or last_action
  if (e.type === "mind_wakeup") {
    const reason =
      (d.reason as string) ||
      (d.trigger as string) ||
      (d.last_action as string) ||
      "cycle start";
    return { title: reason };
  }
  // Actions — show the action verb + summary
  if (e.type === "mind_action") {
    const action = (d.action as string) || (d.summary as string) || "action";
    const summary = (d.summary as string) || "";
    return { title: action, detail: summary !== action ? summary : undefined };
  }
  // Errors — surface the message
  if (e.type === "mind_error") {
    const error = (d.error as string) || "error";
    return { title: error };
  }
  // Generic fallback — pick the most useful string field
  const title =
    (d.summary as string) ||
    (d.label as string) ||
    (d.message as string) ||
    (d.tool as string) ||
    e.type;
  return { title };
}

/** ─────────────────────────── Full feed ─────────────────────────── */

interface MindFeedProps {
  className?: string;
}

export function MindFeed({ className }: MindFeedProps) {
  const events = useDataStore((s) => s.mindEvents);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [isLive, setIsLive] = useState(true);

  // Auto-scroll on new events ONLY when user is already at the bottom.
  // Scrolling up to read history without being yanked back is a critical
  // UX expectation for any chat-shape feed.
  useEffect(() => {
    if (isLive) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, isLive]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setIsLive(atBottom);
  }

  function jumpToLive() {
    setIsLive(true);
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <div
      className={cn(
        "crop-marks relative flex h-full flex-col overflow-hidden rounded-lg border border-border/50 bg-card/30",
        className,
      )}
    >
      {/* Header strip */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-4 py-2.5">
        <Brain className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Live Activity
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {events.length}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <span
            className={cn(
              "size-1.5 rounded-full",
              isLive ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground/40",
            )}
          />
          <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
            {isLive ? "live" : "paused"}
          </span>
        </div>
      </div>

      {/* Feed */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3"
      >
        {events.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Brain className="size-6 text-muted-foreground/20" />
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/50">
              Waiting for autonomous activity…
            </span>
            <span className="font-mono text-[9px] text-muted-foreground/40">
              Each cycle (wakeup → think → act → reflect) streams here.
            </span>
          </div>
        ) : (
          <div className="space-y-2.5">
            {events.map((e, i) => (
              <FeedBubble key={`${e.timestamp}-${i}`} event={e} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* "Jump to live" — only visible when user has scrolled up */}
      {!isLive && events.length > 0 && (
        <button
          onClick={jumpToLive}
          className="absolute bottom-3 right-4 flex items-center gap-1.5 rounded-full border border-border/60 bg-card/90 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground shadow-lg transition-colors hover:text-foreground"
        >
          <ArrowDown className="size-3" />
          Jump to live
        </button>
      )}
    </div>
  );
}

function FeedBubble({ event }: { event: MindEvent }) {
  const style = styleFor(event.type);
  const Icon = style.icon;
  const { title, detail } = summarizeEvent(event);

  return (
    <div
      className={cn(
        "group relative rounded-md border-l-2 bg-card/40 px-3 py-2 transition-colors hover:bg-card/70",
        style.rail,
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className={cn("size-3 shrink-0", style.color)} />
        <span
          className={cn(
            "font-mono text-[9px] uppercase tracking-[0.1em]",
            style.color,
          )}
        >
          {style.label}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-foreground/90">
          {title}
        </span>
        <span className="shrink-0 font-mono text-[9px] text-muted-foreground/50">
          {fmtTime(event.timestamp)}
        </span>
      </div>
      {detail && (
        <p className="mt-1 ml-5 line-clamp-3 whitespace-pre-wrap text-[10.5px] leading-relaxed text-muted-foreground/80">
          {detail}
        </p>
      )}
    </div>
  );
}

/** ───────────────────────── Compact (dashboard) ───────────────────────── */

interface MindFeedCompactProps {
  className?: string;
  /** Max events to show. Default 5 — slim card. */
  limit?: number;
}

/**
 * Slim dashboard variant — last N events + "View live →" CTA opening the
 * full Mind page. Designed to live at the TOP of the dashboard so the
 * agent's autonomous activity is impossible to miss.
 */
export function MindFeedCompact({
  className,
  limit = 5,
}: MindFeedCompactProps) {
  const events = useDataStore((s) => s.mindEvents);
  const navigate = useNavigationStore((s) => s.navigate);
  // Last N events, newest at the bottom so the eye lands on "right now"
  const tail = events.slice(-limit);

  return (
    <div
      className={cn(
        "crop-marks rounded-lg border border-border/60 bg-card/30 p-4",
        className,
      )}
    >
      <div className="mb-2.5 flex items-center gap-2">
        <Brain className="size-3.5 text-muted-foreground" />
        <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
          Autonomous Activity
        </h3>
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {events.length}
        </span>
        <button
          onClick={() => navigate("mind")}
          className="ml-auto font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:text-foreground"
        >
          View live →
        </button>
      </div>

      {tail.length === 0 ? (
        <p className="py-2 text-center font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/50">
          Waiting for autonomous activity…
        </p>
      ) : (
        <div className="space-y-1.5">
          {tail.map((e, i) => {
            const style = styleFor(e.type);
            const Icon = style.icon;
            const { title } = summarizeEvent(e);
            return (
              <div
                key={`${e.timestamp}-${i}`}
                className={cn(
                  "flex items-center gap-2 rounded-md border-l-2 bg-card/30 px-2.5 py-1.5",
                  style.rail,
                )}
              >
                <Icon className={cn("size-3 shrink-0", style.color)} />
                <span
                  className={cn(
                    "shrink-0 font-mono text-[8.5px] uppercase tracking-[0.1em]",
                    style.color,
                  )}
                >
                  {style.label}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-foreground/80">
                  {title}
                </span>
                <span className="shrink-0 font-mono text-[8.5px] text-muted-foreground/50">
                  {fmtTime(e.timestamp)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
