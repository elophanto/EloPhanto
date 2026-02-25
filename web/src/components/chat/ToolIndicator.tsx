import type { ToolStep } from "@/stores/chat";

interface ToolIndicatorProps {
  steps: ToolStep[];
}

export function ToolIndicator({ steps }: ToolIndicatorProps) {
  if (steps.length === 0) return null;

  return (
    <div className="message-enter space-y-1.5 py-2 pl-1">
      {steps.map((step) => (
        <div
          key={step.id}
          className="flex items-center gap-2.5 text-muted-foreground"
        >
          <div className="tool-spinner shrink-0" />
          <span className="font-mono text-[10px] uppercase tracking-[0.1em]">
            {step.toolName}
          </span>
          {step.thought && (
            <span className="truncate text-[11px] text-muted-foreground/50">
              {step.thought}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
