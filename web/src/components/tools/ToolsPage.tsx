import { useEffect, useState } from "react";
import { Search, Shield, AlertTriangle, Zap, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type ToolInfo } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const permissionConfig = {
  safe: { icon: Shield, color: "text-emerald-500", label: "Safe" },
  moderate: { icon: Zap, color: "text-amber-500", label: "Moderate" },
  destructive: {
    icon: AlertTriangle,
    color: "text-orange-500",
    label: "Destructive",
  },
  critical: { icon: Lock, color: "text-red-500", label: "Critical" },
} as const;

function getCategory(name: string): string {
  if (name.startsWith("browser_")) return "Browser";
  if (name.startsWith("file_")) return "System";
  if (name.startsWith("shell_")) return "System";
  if (name.startsWith("vault_")) return "System";
  if (name.startsWith("knowledge_") || name.startsWith("skill_")) return "Knowledge";
  if (name.startsWith("hub_")) return "Hub";
  if (name.startsWith("self_")) return "Self-Dev";
  if (name.startsWith("schedule_")) return "Schedule";
  if (name.startsWith("document_")) return "Documents";
  if (name.startsWith("goal_")) return "Goals";
  if (name.startsWith("identity_")) return "Identity";
  if (name.startsWith("email_")) return "Email";
  if (name.startsWith("payment_") || name.startsWith("crypto_") || name.startsWith("wallet_"))
    return "Payments";
  if (name.startsWith("totp_")) return "Verification";
  if (name.startsWith("swarm_")) return "Swarm";
  if (name.startsWith("mcp_")) return "MCP";
  if (name === "set_next_wakeup" || name === "update_scratchpad") return "Mind";
  if (name === "llm_call") return "Data";
  return "Other";
}

export function ToolsPage() {
  const { tools, toolsLoading, fetchTools } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  useEffect(() => {
    if (status === "connected") {
      fetchTools();
    }
  }, [status, fetchTools]);

  const filtered = tools.filter((t) => {
    const matchesSearch =
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase());
    const matchesCategory =
      !selectedCategory || getCategory(t.name) === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  // Group tools by category
  const categories = new Map<string, ToolInfo[]>();
  for (const tool of filtered) {
    const cat = getCategory(tool.name);
    const list = categories.get(cat) ?? [];
    list.push(tool);
    categories.set(cat, list);
  }

  const allCategories = [...new Set(tools.map((t) => getCategory(t.name)))].sort();

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Tools
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {tools.length} registered
            </p>
          </div>

          {/* Search */}
          <div className="relative w-72">
            <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tools..."
              className="h-8 pl-9 font-mono text-xs"
            />
          </div>
        </div>

        {/* Category filters */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <button
            onClick={() => setSelectedCategory(null)}
            className={cn(
              "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
              !selectedCategory
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            All
          </button>
          {allCategories.map((cat) => (
            <button
              key={cat}
              onClick={() =>
                setSelectedCategory(selectedCategory === cat ? null : cat)
              }
              className={cn(
                "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                selectedCategory === cat
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {toolsLoading ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading tools...
              </span>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {tools.length === 0
                ? "Connect to gateway to load tools"
                : "No tools match your search"}
            </span>
          </div>
        ) : (
          <div className="space-y-6">
            {[...categories.entries()].map(([category, catTools]) => (
              <div key={category}>
                <div className="mb-2 flex items-center gap-2">
                  <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                    {category}
                  </h2>
                  <span className="font-mono text-[9px] text-muted-foreground/50">
                    {catTools.length}
                  </span>
                </div>
                <div className="space-y-1">
                  {catTools.map((tool) => (
                    <ToolRow
                      key={tool.name}
                      tool={tool}
                      expanded={expandedTool === tool.name}
                      onToggle={() =>
                        setExpandedTool(
                          expandedTool === tool.name ? null : tool.name
                        )
                      }
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolRow({
  tool,
  expanded,
  onToggle,
}: {
  tool: ToolInfo;
  expanded: boolean;
  onToggle: () => void;
}) {
  const perm =
    permissionConfig[tool.permission as keyof typeof permissionConfig] ??
    permissionConfig.safe;
  const PermIcon = perm.icon;
  const paramNames = Object.keys(tool.parameters);

  return (
    <div
      className={cn(
        "rounded-md border border-transparent transition-colors",
        expanded && "border-border/50 bg-card"
      )}
    >
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-foreground/[3%]"
      >
        <PermIcon className={cn("size-3.5 shrink-0", perm.color)} />
        <span className="min-w-0 flex-1">
          <span className="font-mono text-xs">{tool.name}</span>
          <span className="ml-2 text-xs text-muted-foreground/60">
            {tool.description.slice(0, 80)}
            {tool.description.length > 80 ? "..." : ""}
          </span>
        </span>
        {paramNames.length > 0 && (
          <Badge
            variant="outline"
            className="shrink-0 font-mono text-[8px] uppercase"
          >
            {paramNames.length} param{paramNames.length !== 1 ? "s" : ""}
          </Badge>
        )}
      </button>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-3">
          <p className="text-xs leading-relaxed text-muted-foreground">
            {tool.description}
          </p>

          {paramNames.length > 0 && (
            <div className="mt-3">
              <h4 className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
                Parameters
              </h4>
              <div className="space-y-1">
                {paramNames.map((name) => {
                  const param = tool.parameters[name];
                  const isRequired = tool.required.includes(name);
                  return (
                    <div key={name} className="flex items-start gap-2 text-xs">
                      <code className="shrink-0 font-mono text-[11px]">
                        {name}
                      </code>
                      {isRequired && (
                        <span className="shrink-0 font-mono text-[8px] uppercase text-amber-500">
                          req
                        </span>
                      )}
                      {param?.type && (
                        <span className="shrink-0 font-mono text-[9px] text-muted-foreground/50">
                          {param.type}
                        </span>
                      )}
                      {param?.description && (
                        <span className="text-muted-foreground/60">
                          {param.description}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="mt-2 flex items-center gap-1.5">
            <PermIcon className={cn("size-3", perm.color)} />
            <span
              className={cn(
                "font-mono text-[9px] uppercase tracking-[0.1em]",
                perm.color
              )}
            >
              {perm.label}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
