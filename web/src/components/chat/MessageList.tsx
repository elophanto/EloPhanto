import { ChevronDown } from "lucide-react";
import { useChatStore } from "@/stores/chat";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { MessageBubble } from "./MessageBubble";
import { ToolIndicator } from "./ToolIndicator";
import { ApprovalCard } from "./ApprovalCard";
import { Button } from "@/components/ui/button";

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const approvalRequests = useChatStore((s) => s.approvalRequests);
  const activeToolSteps = useChatStore((s) => s.activeToolSteps);
  const isAgentTyping = useChatStore((s) => s.isAgentTyping);

  const { ref, isAtBottom, scrollToBottom } = useAutoScroll<HTMLDivElement>([
    messages,
    approvalRequests,
    activeToolSteps,
  ]);

  const pendingApprovals = approvalRequests.filter(
    (r) => r.status === "pending"
  );

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={ref} className="h-full overflow-y-auto px-6 py-4">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
          </>
        )}

        {/* Tool execution indicators */}
        {isAgentTyping && <ToolIndicator steps={activeToolSteps} />}

        {/* Pending approvals */}
        {pendingApprovals.map((req) => (
          <ApprovalCard key={req.id} request={req} />
        ))}
      </div>

      {/* Jump to bottom */}
      {!isAtBottom && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
          <Button
            variant="outline"
            size="sm"
            onClick={scrollToBottom}
            className="gap-1.5 rounded-full shadow-lg"
          >
            <ChevronDown className="size-3" />
            <span className="font-mono text-[9px] uppercase tracking-[0.1em]">
              Latest
            </span>
          </Button>
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6">
      <div className="crop-marks p-8">
        <div className="flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-lg border border-border/50 bg-card">
            <span className="font-mono text-lg font-bold text-foreground/60">
              E
            </span>
          </div>
          <h2 className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            EloPhanto
          </h2>
        </div>
      </div>
      <p className="max-w-sm text-center text-sm leading-relaxed text-muted-foreground/60">
        Send a message to start a conversation with your agent.
      </p>
    </div>
  );
}
