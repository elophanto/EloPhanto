import { useEffect, useState } from "react";
import {
  Settings,
  ChevronDown,
  ChevronRight,
  Check,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type ConfigData } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";

export function SettingsPage() {
  const { config, configLoading, fetchConfig } = useDataStore();
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (status === "connected") {
      fetchConfig();
    }
  }, [status, fetchConfig]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm uppercase tracking-[0.15em]">
              Settings
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Configuration (read-only)
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {configLoading && !config ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="tool-spinner" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                Loading configuration...
              </span>
            </div>
          </div>
        ) : !config ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Connect to gateway to load config
            </span>
          </div>
        ) : (
          <div className="space-y-3">
            {Object.entries(config).map(([section, value]) => (
              <ConfigSection
                key={section}
                name={section}
                value={value}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ConfigSection({
  name,
  value,
}: {
  name: string;
  value: unknown;
}) {
  const [expanded, setExpanded] = useState(false);

  // Determine if this section has an "enabled" field
  const isObject = typeof value === "object" && value !== null && !Array.isArray(value);
  const entries = isObject ? Object.entries(value as ConfigData) : [];
  const enabledField = entries.find(([k]) => k === "enabled");
  const isEnabled = enabledField ? Boolean(enabledField[1]) : null;

  // For simple values, render inline
  if (!isObject) {
    return (
      <div className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-foreground/[3%]">
        <span className="font-mono text-xs">{name}</span>
        <ConfigValue value={value} />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-lg border border-transparent transition-colors",
        expanded && "border-border/50 bg-card"
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-foreground/[3%]"
      >
        {expanded ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        )}
        <Settings className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-mono text-xs">{name}</span>

        {isEnabled !== null && (
          <Badge
            variant="outline"
            className={cn(
              "ml-auto font-mono text-[7px] uppercase",
              isEnabled
                ? "border-emerald-500/30 text-emerald-500"
                : "border-muted-foreground/30 text-muted-foreground/50"
            )}
          >
            {isEnabled ? "enabled" : "disabled"}
          </Badge>
        )}
      </button>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-3">
          <div className="space-y-1.5">
            {entries.map(([key, val]) => (
              <ConfigEntry key={key} entryKey={key} value={val} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigEntry({
  entryKey,
  value,
}: {
  entryKey: string;
  value: unknown;
}) {
  const [expanded, setExpanded] = useState(false);
  const isObject =
    typeof value === "object" && value !== null && !Array.isArray(value);

  if (isObject) {
    const entries = Object.entries(value as ConfigData);
    return (
      <div className="ml-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 py-0.5 text-left"
        >
          {expanded ? (
            <ChevronDown className="size-2.5 text-muted-foreground/50" />
          ) : (
            <ChevronRight className="size-2.5 text-muted-foreground/50" />
          )}
          <span className="font-mono text-[11px] text-muted-foreground">
            {entryKey}
          </span>
        </button>
        {expanded && (
          <div className="ml-3 space-y-1 border-l border-border/30 pl-3">
            {entries.map(([k, v]) => (
              <ConfigEntry key={k} entryKey={k} value={v} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="ml-2 flex items-center justify-between py-0.5">
      <span className="font-mono text-[11px] text-muted-foreground">
        {entryKey}
      </span>
      <ConfigValue value={value} />
    </div>
  );
}

function ConfigValue({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    return value ? (
      <Check className="size-3 text-emerald-500" />
    ) : (
      <X className="size-3 text-muted-foreground/40" />
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <span className="font-mono text-[10px] text-muted-foreground/40">
          []
        </span>
      );
    }
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <Badge
            key={i}
            variant="outline"
            className="font-mono text-[8px]"
          >
            {String(v)}
          </Badge>
        ))}
      </div>
    );
  }

  if (value === null || value === undefined || value === "") {
    return (
      <span className="font-mono text-[10px] text-muted-foreground/30">
        —
      </span>
    );
  }

  return (
    <span className="font-mono text-[11px]">
      {String(value)}
    </span>
  );
}
