import { useEffect, useState } from "react";
import { Shield, Zap, MessageSquare, Radio, Ban } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { gateway } from "@/lib/gateway";
import { MessageType } from "@/lib/protocol";
import { useConnectionStore } from "@/stores/connection";
import { useNavigationStore } from "@/stores/navigation";

interface HostedStatus {
  hosted: boolean;
  custody_label: string | null;
  stopped: boolean;
  spend_frozen: boolean;
  permission_mode: string;
}

/**
 * First-run surface for Hosted / basic users: one wedge, clear brakes,
 * no nuclear theater. Hidden when not connected or not hosted.
 */
export function HostedOnboarding() {
  const status = useConnectionStore((s) => s.status);
  const navigate = useNavigationStore((s) => s.navigate);
  const [hosted, setHosted] = useState<HostedStatus | null>(null);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem("elophanto.hosted.onboarding.dismissed") === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (status !== "connected") return;
    gateway.sendCommand("hosted_status");
  }, [status]);

  useEffect(() => {
    const unsub = gateway.on(MessageType.RESPONSE, (msg) => {
      try {
        const content = msg.data?.content as string | undefined;
        if (!content?.startsWith("{")) return;
        const parsed = JSON.parse(content) as { hosted_status?: HostedStatus };
        if (parsed.hosted_status) setHosted(parsed.hosted_status);
      } catch {
        /* ignore */
      }
    });
    return unsub;
  }, []);

  if (!hosted?.hosted || dismissed) return null;

  const dismiss = () => {
    try {
      localStorage.setItem("elophanto.hosted.onboarding.dismissed", "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  };

  return (
    <div className="mx-6 mt-4 rounded-lg border border-border bg-card/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant="secondary">Hosted</Badge>
            <h2 className="text-lg font-semibold tracking-tight">
              Your always-on agent
            </h2>
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">
            {hosted.custody_label ||
              "Managed custody — this box runs on infrastructure we operate."}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={dismiss}>
          Dismiss
        </Button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="space-y-2 rounded-md border border-border/60 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Zap className="h-4 w-4" /> Start with one job
          </div>
          <p className="text-xs text-muted-foreground">
            Research → draft outreach → queue sends → approve CRITICAL steps.
            Keep the first goal narrow so you get a receipt today.
          </p>
          <Button size="sm" onClick={() => navigate("chat")}>
            <MessageSquare className="h-4 w-4" /> Open chat
          </Button>
        </div>
        <div className="space-y-2 rounded-md border border-border/60 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Radio className="h-4 w-4" /> Connect a channel
          </div>
          <p className="text-xs text-muted-foreground">
            Telegram for remote approvals while the laptop is closed. Mode max
            is full_auto — nuclear does not exist here.
          </p>
          <Button size="sm" variant="outline" onClick={() => navigate("channels")}>
            Channels
          </Button>
        </div>
        <div className="space-y-2 rounded-md border border-border/60 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Shield className="h-4 w-4" /> Owner brakes
          </div>
          <p className="text-xs text-muted-foreground">
            Kill stops the agent. Spend freeze blocks money tools. Status:{" "}
            {hosted.stopped ? "STOPPED" : "running"}
            {hosted.spend_frozen ? " · SPEND FROZEN" : ""}.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="destructive"
              onClick={() => {
                if (
                  window.confirm(
                    "Kill the agent now? This stops work, freezes spend, and cancels in-flight tasks."
                  )
                ) {
                  gateway.sendCommand("owner_kill");
                }
              }}
            >
              <Ban className="h-4 w-4" /> Kill
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (window.confirm("Freeze all payment / wallet tools?")) {
                  gateway.sendCommand("owner_spend_freeze");
                }
              }}
            >
              Freeze spend
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
