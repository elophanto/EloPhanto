import { useEffect } from "react";
import {
  Radio,
  Monitor,
  MessageSquare,
  Hash,
  Globe,
  Server,
  Users,
} from "lucide-react";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";

const channelIcons: Record<string, typeof Monitor> = {
  cli: Monitor,
  web: Globe,
  telegram: MessageSquare,
  discord: Hash,
  slack: Hash,
};

export function ChannelsPage() {
  const { channels, channelsLoading, fetchChannels } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchChannels();
    }
  }, [status, fetchChannels]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Channels
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {channels
                ? `${channels.clients.length} client${channels.clients.length !== 1 ? "s" : ""} connected`
                : "Gateway connections"}
            </p>
          </div>
          <button
            onClick={fetchChannels}
            disabled={channelsLoading}
            className="rounded-md px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
          >
            {channelsLoading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {channelsLoading && !channels ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading channels...
              </span>
            </div>
          </div>
        ) : !channels ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Connect to gateway to load channel info
            </span>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Gateway info */}
            <div className="crop-marks rounded-lg border border-border/50 p-4">
              <div className="mb-3 flex items-center gap-2">
                <Server className="size-3.5 text-muted-foreground" />
                <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
                  Gateway
                </h3>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                    Endpoint
                  </span>
                  <span className="font-mono text-xs">
                    ws://{channels.gateway.host}:{channels.gateway.port}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                    Sessions
                  </span>
                  <span className="font-mono text-xs">
                    {channels.sessions.active} active
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                    Mode
                  </span>
                  <Badge
                    variant="outline"
                    className="font-mono text-[8px] uppercase"
                  >
                    {channels.sessions.unified_mode
                      ? "unified"
                      : "per-channel"}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Connected clients */}
            <div>
              <div className="mb-2 flex items-center gap-2">
                <Users className="size-3.5 text-muted-foreground" />
                <h3 className="font-mono text-[11px] uppercase tracking-[0.15em]">
                  Connected Clients
                </h3>
                <span className="font-mono text-[9px] text-muted-foreground/50">
                  {channels.clients.length}
                </span>
              </div>

              {channels.clients.length === 0 ? (
                <div className="flex h-20 items-center justify-center">
                  <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                    No clients connected
                  </span>
                </div>
              ) : (
                <div className="space-y-1">
                  {channels.clients.map((client) => {
                    const Icon =
                      channelIcons[client.channel] ?? Radio;
                    return (
                      <div
                        key={client.client_id}
                        className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-foreground/[3%]"
                      >
                        <span className="status-dot status-connected shrink-0" />
                        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="font-mono text-xs">
                            {client.channel}
                          </span>
                          <span className="ml-2 font-mono text-[10px] text-muted-foreground/50">
                            {client.user_id}
                          </span>
                        </span>
                        <span className="font-mono text-[9px] text-muted-foreground/40">
                          {client.client_id}
                        </span>
                        {client.session_id && (
                          <Badge
                            variant="outline"
                            className="font-mono text-[7px] uppercase text-muted-foreground/50"
                          >
                            {client.session_id}
                          </Badge>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
