import { useEffect, useState } from "react";
import { Search, Sparkles, Globe, Download, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type SkillInfo } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const sourceConfig = {
  local: { icon: Sparkles, label: "Bundled", color: "text-foreground/60" },
  hub: { icon: Download, label: "Hub", color: "text-emerald-500" },
  external: { icon: Globe, label: "External", color: "text-blue-500" },
} as const;

export function SkillsPage() {
  const { skills, skillsLoading, fetchSkills } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [search, setSearch] = useState("");
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);

  useEffect(() => {
    if (status === "connected") {
      fetchSkills();
    }
  }, [status, fetchSkills]);

  const filtered = skills.filter((s) => {
    const matchesSearch =
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.description.toLowerCase().includes(search.toLowerCase()) ||
      s.triggers.some((t) => t.toLowerCase().includes(search.toLowerCase()));
    const matchesSource = !selectedSource || s.source === selectedSource;
    return matchesSearch && matchesSource;
  });

  const sources = [...new Set(skills.map((s) => s.source))].sort();

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Skills
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {skills.length} available
            </p>
          </div>

          {/* Search */}
          <div className="relative w-72">
            <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search skills..."
              className="h-8 pl-9 font-mono text-xs"
            />
          </div>
        </div>

        {/* Source filters */}
        {sources.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <button
              onClick={() => setSelectedSource(null)}
              className={cn(
                "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                !selectedSource
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              All
            </button>
            {sources.map((src) => (
              <button
                key={src}
                onClick={() =>
                  setSelectedSource(selectedSource === src ? null : src)
                }
                className={cn(
                  "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                  selectedSource === src
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {src}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Skills grid */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {skillsLoading ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading skills...
              </span>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {skills.length === 0
                ? "Connect to gateway to load skills"
                : "No skills match your search"}
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {filtered.map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                expanded={expandedSkill === skill.name}
                onToggle={() =>
                  setExpandedSkill(
                    expandedSkill === skill.name ? null : skill.name
                  )
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SkillCard({
  skill,
  expanded,
  onToggle,
}: {
  skill: SkillInfo;
  expanded: boolean;
  onToggle: () => void;
}) {
  const src =
    sourceConfig[skill.source as keyof typeof sourceConfig] ??
    sourceConfig.local;
  const SrcIcon = src.icon;

  return (
    <button
      onClick={onToggle}
      className={cn(
        "crop-marks rounded-lg border border-border/50 p-4 text-left transition-colors hover:bg-card",
        expanded && "bg-card"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-mono text-xs font-medium">{skill.name}</h3>
        <div className="flex items-center gap-1">
          <SrcIcon className={cn("size-3", src.color)} />
          <span
            className={cn(
              "font-mono text-[8px] uppercase tracking-[0.1em]",
              src.color
            )}
          >
            {src.label}
          </span>
        </div>
      </div>

      {skill.description && (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {expanded
            ? skill.description
            : skill.description.slice(0, 120) +
              (skill.description.length > 120 ? "..." : "")}
        </p>
      )}

      {skill.triggers.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {(expanded ? skill.triggers : skill.triggers.slice(0, 4)).map(
            (trigger) => (
              <Badge
                key={trigger}
                variant="outline"
                className="gap-1 font-mono text-[8px] uppercase"
              >
                <Tag className="size-2" />
                {trigger}
              </Badge>
            )
          )}
          {!expanded && skill.triggers.length > 4 && (
            <span className="px-1 font-mono text-[8px] text-muted-foreground/50">
              +{skill.triggers.length - 4}
            </span>
          )}
        </div>
      )}
    </button>
  );
}
