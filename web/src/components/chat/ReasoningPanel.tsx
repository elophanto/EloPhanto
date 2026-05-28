import { useEffect, useRef, useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chat";

/**
 * Live "Thinking" panel — streams the agent's chain-of-thought
 * (agent_thought reasoning chunks) during a turn. The web analog of
 * the terminal dashboard's #reasoning panel: shows HOW the agent is
 * reasoning while it works, keeping the chat transcript clean. Tool
 * steps render inline in the message list, so this panel is
 * reasoning-only (with a tool hint in the header).
 *
 * Collapsible; auto-scrolls to the latest text. Hidden when there's
 * no reasoning to show (models without exposed reasoning, e.g. most
 * providers, simply never populate it).
 */
export function ReasoningPanel() {
  const reasoning = useChatStore((s) => s.reasoning);
  const lastTool = useChatStore(
    (s) => s.activeToolSteps[s.activeToolSteps.length - 1]?.toolName,
  );
  const isTyping = useChatStore((s) => s.isAgentTyping);
  const [open, setOpen] = useState(true);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the freshest reasoning while it streams.
  useEffect(() => {
    if (open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [reasoning, open]);

  if (!reasoning) return null;

  return (
    <div className="mx-4 mb-2 overflow-hidden rounded-lg border border-border/50 bg-card/40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-foreground/[3%]"
      >
        {open ? (
          <ChevronDown className="size-3 text-muted-foreground/50" />
        ) : (
          <ChevronRight className="size-3 text-muted-foreground/50" />
        )}
        <Brain
          className={cn(
            "size-3.5 text-muted-foreground",
            isTyping && "animate-pulse text-primary",
          )}
        />
        <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
          Thinking
        </span>
        {lastTool && (
          <span className="font-mono text-[9px] text-muted-foreground/40">
            · {lastTool}
          </span>
        )}
        {!open && (
          <span className="ml-auto font-mono text-[9px] text-muted-foreground/40">
            reasoning hidden
          </span>
        )}
      </button>

      {open && (
        <div
          ref={bodyRef}
          className="max-h-48 overflow-y-auto border-t border-border/30 px-3 py-2"
        >
          <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground/80">
            {reasoning}
          </p>
        </div>
      )}
    </div>
  );
}
