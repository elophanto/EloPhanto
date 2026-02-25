import { cn } from "@/lib/utils";
import { Shield, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ApprovalRequest } from "@/stores/chat";
import { useChatStore } from "@/stores/chat";

interface ApprovalCardProps {
  request: ApprovalRequest;
}

export function ApprovalCard({ request }: ApprovalCardProps) {
  const respondToApproval = useChatStore((s) => s.respondToApproval);
  const isPending = request.status === "pending";

  return (
    <div
      className={cn(
        "message-enter my-2 rounded-lg border px-5 py-4",
        isPending
          ? "approval-pending border-border/50 bg-card"
          : request.status === "approved"
            ? "border-border/30 bg-card/50 opacity-70"
            : "border-destructive/30 bg-card/50 opacity-70"
      )}
    >
      {/* Header */}
      <div className="mb-3 flex items-center gap-2">
        <Shield className="size-3.5 text-muted-foreground" />
        <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
          Approval Required
        </span>
      </div>

      {/* Tool info */}
      <div className="mb-3 flex items-center gap-2">
        <Badge variant="outline" className="font-mono text-[10px]">
          {request.toolName}
        </Badge>
      </div>

      {/* Description */}
      <p className="mb-3 text-sm leading-relaxed text-foreground/80">
        {request.description}
      </p>

      {/* Params */}
      {Object.keys(request.params).length > 0 && (
        <pre className="mb-4 overflow-x-auto rounded-md border border-border/30 bg-secondary/30 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {JSON.stringify(request.params, null, 2)}
        </pre>
      )}

      {/* Actions */}
      {isPending ? (
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={() => respondToApproval(request.id, true)}
            className="gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em]"
          >
            <Check className="size-3" />
            Approve
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => respondToApproval(request.id, false)}
            className="gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em]"
          >
            <X className="size-3" />
            Deny
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          {request.status === "approved" ? (
            <Check className="size-3 text-foreground/60" />
          ) : (
            <X className="size-3 text-destructive/60" />
          )}
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            {request.status === "approved" ? "Approved" : "Denied"}
          </span>
        </div>
      )}
    </div>
  );
}
