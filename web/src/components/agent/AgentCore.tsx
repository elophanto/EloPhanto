import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useActivityStore } from "@/stores/activity";
import { useConnectionStore } from "@/stores/connection";
import { useDataStore } from "@/stores/data";

// How recently an activity event counts as "live" → working/thinking.
const ACTIVE_WINDOW_MS = 8000;

type CoreState =
  | "asleep"
  | "resting"
  | "awake"
  | "thinking"
  | "working";

interface StateStyle {
  /** Glow + sphere hue. */
  color: string;
  /** Bright inner highlight. */
  light: string;
  /** Breathing period (s) — faster when busier. */
  breath: number;
  /** Show orbiting particles. */
  particles: boolean;
  label: string;
}

const STATES: Record<CoreState, StateStyle> = {
  working: { color: "#5eead4", light: "#d9fff7", breath: 2.0, particles: true, label: "working" },
  thinking: { color: "#a78bfa", light: "#ece4ff", breath: 2.8, particles: true, label: "thinking" },
  awake: { color: "#7dd3fc", light: "#e3f4ff", breath: 4.5, particles: false, label: "awake" },
  resting: { color: "#94a3b8", light: "#e2e8f0", breath: 7.0, particles: false, label: "resting" },
  asleep: { color: "#5b6472", light: "#9aa3b2", breath: 9.0, particles: false, label: "offline" },
};

function useCoreState(): CoreState {
  const status = useConnectionStore((s) => s.status);
  const latest = useActivityStore((s) => s.latest);
  const mind = useDataStore((s) => s.dashboard?.mind ?? null);

  // 1s tick so "active → idle" decays without a new event.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (status !== "connected") return "asleep";
  if (latest && now - latest.at < ACTIVE_WINDOW_MS) {
    return latest.kind === "mind" ? "thinking" : "working";
  }
  if (mind?.paused) return "resting";
  if (mind?.running) return "awake";
  return "awake";
}

/**
 * The agent's living "core" — a Tau-style luminous orb whose color,
 * glow, breathing speed, and orbiting particles reflect live state
 * (working / thinking / awake / resting / offline). Pure CSS; reads
 * the activity + connection + mind stores.
 */
export function AgentCore({
  size = 96,
  showLabel = false,
  className,
}: {
  size?: number;
  showLabel?: boolean;
  className?: string;
}) {
  const state = useCoreState();
  const s = STATES[state];
  const particleCount = 5;

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <div
        className="relative"
        style={{ width: size, height: size }}
        title={`Agent: ${s.label}`}
      >
        {/* Outer glow halo */}
        <div
          className="absolute inset-0 rounded-full blur-2xl"
          style={{
            background: s.color,
            animation: `core-glow ${s.breath * 1.3}s ease-in-out infinite`,
          }}
        />

        {/* Concentric rings */}
        <div
          className="absolute inset-[6%] rounded-full border"
          style={{
            borderColor: s.color,
            animation: `core-ring ${s.breath * 1.1}s ease-in-out infinite`,
          }}
        />
        <div
          className="absolute inset-[18%] rounded-full border"
          style={{
            borderColor: s.color,
            opacity: 0.5,
            animation: `core-ring ${s.breath}s ease-in-out infinite reverse`,
          }}
        />

        {/* Orbiting particles (active states only) */}
        {s.particles && (
          <div
            className="absolute inset-0"
            style={{ animation: "core-orbit 7s linear infinite" }}
          >
            {Array.from({ length: particleCount }).map((_, i) => {
              const angle = (i / particleCount) * 360;
              return (
                <span
                  key={i}
                  className="absolute left-1/2 top-1/2 rounded-full"
                  style={{
                    width: Math.max(2, size * 0.03),
                    height: Math.max(2, size * 0.03),
                    background: s.light,
                    boxShadow: `0 0 ${size * 0.06}px ${s.color}`,
                    transform: `rotate(${angle}deg) translateX(${size * 0.42}px)`,
                  }}
                />
              );
            })}
          </div>
        )}

        {/* The core sphere */}
        <div
          className="absolute inset-[26%] rounded-full"
          style={{
            background: `radial-gradient(circle at 34% 28%, ${s.light}, ${s.color} 52%, ${s.color}99 100%)`,
            boxShadow: `0 0 ${size * 0.28}px ${s.color}, inset 0 0 ${size * 0.08}px ${s.light}`,
            animation: `core-breathe ${s.breath}s ease-in-out infinite`,
          }}
        />
      </div>

      {showLabel && (
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          {s.label}
        </span>
      )}
    </div>
  );
}
