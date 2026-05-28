import { useEffect } from "react";
import { Users } from "lucide-react";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";

export function RolesPage() {
  const { roles, rolesLoading, fetchRoles } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") fetchRoles();
  }, [status, fetchRoles]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Roles</h1>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {roles.length} persona{roles.length !== 1 ? "s" : ""} — system-prompt overlays the agent wears per cycle
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {rolesLoading && roles.length === 0 ? (
          <Empty text="Loading roles..." />
        ) : roles.length === 0 ? (
          <Empty text="No roles defined. Add YAML files under roles/<name>.yaml." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {roles.map((r) => (
              <div key={r.name} className="rounded-lg border border-border/50 p-4">
                <div className="flex items-center gap-2">
                  <Users className="size-3.5 text-muted-foreground" />
                  <span className="font-mono text-xs uppercase tracking-[0.1em]">
                    {r.name}
                  </span>
                </div>
                {r.description && (
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    {r.description}
                  </p>
                )}
                {r.allowed_tool_groups.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {r.allowed_tool_groups.map((g) => (
                      <Badge key={g} variant="outline" className="text-[8px]">
                        {g}
                      </Badge>
                    ))}
                  </div>
                )}
                {Object.keys(r.kpi).length > 0 && (
                  <div className="mt-3 space-y-1 font-mono text-[10px]">
                    <p className="text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                      KPIs
                    </p>
                    {Object.entries(r.kpi).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span className="text-muted-foreground/70">{k}</span>
                        <span>{String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {r.last_active_at && (
                  <p className="mt-3 font-mono text-[9px] text-muted-foreground/40">
                    last active {r.last_active_at}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center px-8 text-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {text}
      </span>
    </div>
  );
}
