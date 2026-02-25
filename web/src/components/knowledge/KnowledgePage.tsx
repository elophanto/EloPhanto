import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Search,
  BookOpen,
  Database,
  FileText,
  Tag,
  ChevronDown,
  ChevronRight,
  Hash,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useDataStore,
  type KnowledgeFile,
  type KnowledgeChunk,
} from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const scopeConfig: Record<string, { color: string; label: string }> = {
  system: { color: "text-blue-500", label: "System" },
  user: { color: "text-emerald-500", label: "User" },
  learned: { color: "text-amber-500", label: "Learned" },
  plugin: { color: "text-purple-500", label: "Plugin" },
};

export function KnowledgePage() {
  const {
    knowledge,
    knowledgeLoading,
    fetchKnowledge,
    knowledgeDetail,
    knowledgeDetailLoading,
    fetchKnowledgeDetail,
    clearKnowledgeDetail,
  } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const [search, setSearch] = useState("");
  const [selectedScope, setSelectedScope] = useState<string | null>(null);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  useEffect(() => {
    if (status === "connected") {
      fetchKnowledge();
    }
  }, [status, fetchKnowledge]);

  const handleToggle = (filePath: string) => {
    if (expandedFile === filePath) {
      setExpandedFile(null);
      clearKnowledgeDetail();
    } else {
      setExpandedFile(filePath);
      fetchKnowledgeDetail(filePath);
    }
  };

  const files = knowledge?.files ?? [];
  const stats = knowledge?.stats;

  const filtered = files.filter((f) => {
    const matchesSearch =
      !search ||
      f.path.toLowerCase().includes(search.toLowerCase()) ||
      f.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()));
    const matchesScope = !selectedScope || f.scope === selectedScope;
    return matchesSearch && matchesScope;
  });

  const allScopes = [...new Set(files.map((f) => f.scope))].sort();

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Knowledge
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {stats && stats.chunks != null
                ? `${stats.chunks} chunks · ${stats.embeddings} embeddings · ${stats.files} files`
                : "Knowledge base browser"}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchKnowledge}
              disabled={knowledgeLoading}
              className="rounded-md px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
            >
              {knowledgeLoading ? "Loading..." : "Refresh"}
            </button>
            <div className="relative w-72">
              <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search files or tags..."
                className="h-8 pl-9 font-mono text-xs"
              />
            </div>
          </div>
        </div>

        {/* Scope filters */}
        {allScopes.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <button
              onClick={() => setSelectedScope(null)}
              className={cn(
                "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                !selectedScope
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              All
            </button>
            {allScopes.map((scope) => (
              <button
                key={scope}
                onClick={() =>
                  setSelectedScope(selectedScope === scope ? null : scope)
                }
                className={cn(
                  "rounded-full px-2.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                  selectedScope === scope
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {scope}
                {stats?.scopes[scope] != null && (
                  <span className="ml-1 text-muted-foreground/50">
                    {stats.scopes[scope]}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {knowledgeLoading && !knowledge ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading knowledge...
              </span>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {files.length === 0
                ? "No knowledge indexed yet"
                : "No files match your search"}
            </span>
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                expanded={expandedFile === file.path}
                onToggle={() => handleToggle(file.path)}
                chunks={
                  expandedFile === file.path
                    ? knowledgeDetail?.chunks ?? null
                    : null
                }
                chunksLoading={
                  expandedFile === file.path && knowledgeDetailLoading
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FileRow({
  file,
  expanded,
  onToggle,
  chunks,
  chunksLoading,
}: {
  file: KnowledgeFile;
  expanded: boolean;
  onToggle: () => void;
  chunks: KnowledgeChunk[] | null;
  chunksLoading: boolean;
}) {
  const scope = scopeConfig[file.scope] ?? {
    color: "text-muted-foreground",
    label: file.scope,
  };

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
        {expanded ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        )}
        <FileText className={cn("size-3.5 shrink-0", scope.color)} />
        <span className="min-w-0 flex-1">
          <span className="font-mono text-xs">{file.path}</span>
        </span>
        <Badge
          variant="outline"
          className={cn(
            "shrink-0 font-mono text-[7px] uppercase",
            scope.color
          )}
        >
          {scope.label}
        </Badge>
        <Badge
          variant="outline"
          className="shrink-0 font-mono text-[8px] uppercase"
        >
          {file.chunks} chunk{file.chunks !== 1 ? "s" : ""}
        </Badge>
      </button>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-3">
          {/* File metadata */}
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Database className="size-3 text-muted-foreground/50" />
              <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                {file.chunks} chunks
              </span>
            </div>

            {file.tags.length > 0 && (
              <div className="flex items-center gap-1.5">
                <Tag className="size-3 shrink-0 text-muted-foreground/50" />
                <div className="flex flex-wrap gap-1">
                  {file.tags.map((tag) => (
                    <Badge
                      key={tag}
                      variant="outline"
                      className="font-mono text-[8px]"
                    >
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {file.updated_at && (
              <div className="flex items-center gap-1.5">
                <BookOpen className="size-3 text-muted-foreground/50" />
                <span className="font-mono text-[10px] text-muted-foreground/60">
                  Indexed: {file.updated_at}
                </span>
              </div>
            )}
          </div>

          {/* Chunk content */}
          {chunksLoading ? (
            <div className="flex items-center gap-3 py-4">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading chunks...
              </span>
            </div>
          ) : chunks && chunks.length > 0 ? (
            <div className="space-y-2">
              {chunks.map((chunk, i) => (
                <ChunkCard key={i} chunk={chunk} index={i} />
              ))}
            </div>
          ) : chunks && chunks.length === 0 ? (
            <div className="py-3 text-center">
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                No chunks found for this file
              </span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ChunkCard({
  chunk,
  index,
}: {
  chunk: KnowledgeChunk;
  index: number;
}) {
  const [expanded, setExpanded] = useState(index === 0);

  return (
    <div className="rounded-md border border-border/30 bg-foreground/[2%]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-foreground/[3%]"
      >
        {expanded ? (
          <ChevronDown className="size-2.5 shrink-0 text-muted-foreground/50" />
        ) : (
          <ChevronRight className="size-2.5 shrink-0 text-muted-foreground/50" />
        )}
        <Hash className="size-2.5 shrink-0 text-muted-foreground/40" />
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground/80">
          {chunk.heading || `Chunk ${index + 1}`}
        </span>
        <span className="shrink-0 font-mono text-[9px] text-muted-foreground/40">
          {chunk.tokens} tokens
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border/20 px-3 py-2">
          <div className="markdown-content max-h-64 overflow-y-auto text-xs leading-relaxed text-muted-foreground/80">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {chunk.content}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
