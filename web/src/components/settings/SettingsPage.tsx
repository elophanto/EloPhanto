import { useEffect, useState, useCallback } from "react";
import { Eye, EyeOff, Check, AlertCircle, Loader2, ChevronDown, ChevronRight, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore, type ConfigData } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { gateway } from "@/lib/gateway";
import { MessageType } from "@/lib/protocol";

// ---- Types ----

interface ProviderInfo {
  name: string;
  enabled: boolean;
  base_url: string;
  has_key: boolean;
  default_model: string;
  available_models: string[];
}

interface SettingsData {
  agent_name: string;
  permission_mode: string;
  providers: ProviderInfo[];
  vault_unlocked: boolean;
  vault_keys: string[];
  config_path: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: "OpenRouter",
  openai: "OpenAI",
  zai: "Z.AI (GLM)",
  kimi: "Kimi (Moonshot)",
  ollama: "Ollama (local)",
};

const PROVIDER_VAULT_KEY: Record<string, string> = {
  openrouter: "openrouter_api_key",
  openai: "openai_api_key",
  zai: "zai_api_key",
  kimi: "kimi_api_key",
};

const PERMISSION_MODES = ["ask_always", "smart_auto", "full_auto"] as const;

// ---- Hook to listen for gateway responses ----

function useSettingsGateway() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<Record<string, "saving" | "ok" | "error">>({});
  const status = useConnectionStore((s) => s.status);

  const fetch = useCallback(() => {
    setLoading(true);
    gateway.sendCommand("settings_get");
  }, []);

  useEffect(() => {
    if (status !== "connected") return;
    fetch();
  }, [status, fetch]);

  // Mark all "saving" keys as "error" after 8s timeout
  useEffect(() => {
    const saving = Object.entries(saveStatus).filter(([, v]) => v === "saving");
    if (saving.length === 0) return;
    const timer = setTimeout(() => {
      setSaveStatus((prev) => {
        const next = { ...prev };
        for (const [k, v] of Object.entries(next)) {
          if (v === "saving") next[k] = "error";
        }
        return next;
      });
    }, 8000);
    return () => clearTimeout(timer);
  }, [saveStatus]);

  useEffect(() => {
    const unsubResponse = gateway.on(MessageType.RESPONSE, (msg) => {
      try {
        const content = msg.data?.content as string | undefined;
        if (!content) return;
        const parsed = JSON.parse(content);

        if (parsed?.settings) {
          setSettings(parsed.settings);
          setLoading(false);
        }
        if (parsed?.vault_set?.ok) {
          const key = parsed.vault_set.key as string;
          setSaveStatus((prev) => ({ ...prev, [key]: "ok" }));
          setTimeout(() => setSaveStatus((prev) => { const n = { ...prev }; delete n[key]; return n; }), 2000);
          fetch();
        }
        if (parsed?.config_update?.ok) {
          const key = (parsed.config_update.status_key as string) ?? "config";
          setSaveStatus((prev) => ({ ...prev, [key]: "ok" }));
          setTimeout(() => setSaveStatus((prev) => { const n = { ...prev }; delete n[key]; return n; }), 2000);
          fetch();
        }
      } catch {
        // ignore non-settings messages
      }
    });

    const unsubError = gateway.on(MessageType.ERROR, (msg) => {
      const detail = (msg.data?.detail as string) ?? "";
      if (detail.toLowerCase().includes("vault")) {
        // Mark all saving keys as error
        setSaveStatus((prev) => {
          const next = { ...prev };
          for (const [k, v] of Object.entries(next)) {
            if (v === "saving") next[k] = "error";
          }
          return next;
        });
      }
    });

    return () => { unsubResponse(); unsubError(); };
  }, [fetch]);

  const saveVaultKey = useCallback((key: string, value: string) => {
    setSaveStatus((prev) => ({ ...prev, [key]: "saving" }));
    gateway.sendCommand("vault_set", { key, value });
  }, []);

  const saveConfig = useCallback((args: Record<string, unknown>, statusKey = "config") => {
    setSaveStatus((prev) => ({ ...prev, [statusKey]: "saving" }));
    gateway.sendCommand("config_update", { ...args, _status_key: statusKey });
  }, []);

  return { settings, loading, saveStatus, saveVaultKey, saveConfig, refresh: fetch };
}

// ---- Main component ----

export function SettingsPage() {
  const { config, fetchConfig } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const { settings, loading, saveStatus, saveVaultKey, saveConfig } = useSettingsGateway();
  const [rawExpanded, setRawExpanded] = useState(false);

  useEffect(() => {
    if (status === "connected") fetchConfig();
  }, [status, fetchConfig]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Settings</h1>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          Configure your agent
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {loading && !settings ? (
          <div className="flex h-40 items-center justify-center gap-3">
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Loading settings...
            </span>
          </div>
        ) : !settings ? (
          <div className="flex h-32 items-center justify-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              Connect to gateway to load settings
            </span>
          </div>
        ) : (
          <>
            <IdentitySection
              settings={settings}
              saveStatus={saveStatus}
              onSave={saveConfig}
            />
            <ProvidersSection
              settings={settings}
              saveStatus={saveStatus}
              onSaveKey={saveVaultKey}
              onToggleProvider={(name, enabled) =>
                saveConfig({ provider_enabled: { [name]: enabled } })
              }
              onSaveModel={(name, model) =>
                saveConfig({ provider_model: { [name]: model } }, `model_${name}`)
              }
            />
            <VaultSection settings={settings} />
            {/* Raw config viewer */}
            <div className="rounded-lg border border-border/40">
              <button
                onClick={() => setRawExpanded(!rawExpanded)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-foreground/[3%]"
              >
                {rawExpanded ? <ChevronDown className="size-3 text-muted-foreground" /> : <ChevronRight className="size-3 text-muted-foreground" />}
                <Settings className="size-3.5 text-muted-foreground" />
                <span className="font-mono text-xs">Raw Configuration</span>
                <span className="ml-auto font-mono text-[9px] uppercase text-muted-foreground/50">read-only</span>
              </button>
              {rawExpanded && config && (
                <div className="border-t border-border/30 px-4 py-3 space-y-1.5">
                  {Object.entries(config).map(([section, value]) => (
                    <ConfigSection key={section} name={section} value={value} />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---- Identity section ----

function IdentitySection({
  settings,
  saveStatus,
  onSave,
}: {
  settings: SettingsData;
  saveStatus: Record<string, "saving" | "ok" | "error">;
  onSave: (args: Record<string, unknown>) => void;
}) {
  const [name, setName] = useState(settings.agent_name);
  const [mode, setMode] = useState(settings.permission_mode);
  const dirty = name !== settings.agent_name || mode !== settings.permission_mode;
  const saving = saveStatus.config === "saving";
  const saved = saveStatus.config === "ok";

  useEffect(() => {
    setName(settings.agent_name);
    setMode(settings.permission_mode);
  }, [settings.agent_name, settings.permission_mode]);

  return (
    <section>
      <SectionTitle>Identity</SectionTitle>
      <div className="space-y-3 mt-3">
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Agent Name
          </label>
          <input
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-foreground/20"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Permission Mode
          </label>
          <div className="mt-1 flex gap-2">
            {PERMISSION_MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "rounded-md border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  mode === m
                    ? "border-foreground/40 bg-foreground/10 text-foreground"
                    : "border-border text-muted-foreground hover:border-foreground/20"
                )}
              >
                {m.replace("_", " ")}
              </button>
            ))}
          </div>
        </div>
        <div className="flex justify-end">
          <SaveButton
            dirty={dirty}
            saving={saving}
            saved={saved}
            onSave={() => onSave({ agent_name: name, permission_mode: mode })}
          />
        </div>
      </div>
    </section>
  );
}

// ---- Providers section ----

function ProvidersSection({
  settings,
  saveStatus,
  onSaveKey,
  onToggleProvider,
  onSaveModel,
}: {
  settings: SettingsData;
  saveStatus: Record<string, "saving" | "ok" | "error">;
  onSaveKey: (key: string, value: string) => void;
  onToggleProvider: (name: string, enabled: boolean) => void;
  onSaveModel: (name: string, model: string) => void;
}) {
  return (
    <section>
      <SectionTitle>LLM Providers</SectionTitle>
      <div className="mt-3 space-y-2">
        {settings.providers
          .filter((p) => p.name !== "ollama")
          .map((provider) => (
            <ProviderCard
              key={provider.name}
              provider={provider}
              saveStatus={saveStatus}
              onSaveKey={onSaveKey}
              onToggle={(enabled) => onToggleProvider(provider.name, enabled)}
              onSaveModel={(model) => onSaveModel(provider.name, model)}
            />
          ))}
        {/* Ollama — no API key needed */}
        {settings.providers
          .filter((p) => p.name === "ollama")
          .map((provider) => (
            <div key="ollama" className="flex items-center justify-between rounded-lg border border-border/40 px-4 py-3">
              <div>
                <span className="font-mono text-xs">Ollama</span>
                <span className="ml-2 font-mono text-[10px] text-muted-foreground">(local — no API key)</span>
              </div>
              <Toggle
                checked={provider.enabled}
                onChange={(v) => onToggleProvider("ollama", v)}
              />
            </div>
          ))}
      </div>
    </section>
  );
}

function ProviderCard({
  provider,
  saveStatus,
  onSaveKey,
  onToggle,
  onSaveModel,
}: {
  provider: ProviderInfo;
  saveStatus: Record<string, "saving" | "ok" | "error">;
  onSaveKey: (key: string, value: string) => void;
  onToggle: (enabled: boolean) => void;
  onSaveModel: (model: string) => void;
}) {
  const vaultKey = PROVIDER_VAULT_KEY[provider.name] ?? `${provider.name}_api_key`;
  const [apiKey, setApiKey] = useState("");
  const [show, setShow] = useState(false);
  const [model, setModel] = useState(provider.default_model ?? "");
  const keySaving = saveStatus[vaultKey] === "saving";
  const keySaved = saveStatus[vaultKey] === "ok";
  const modelKey = `model_${provider.name}`;
  const modelSaving = saveStatus[modelKey] === "saving";
  const modelSaved = saveStatus[modelKey] === "ok";
  const label = PROVIDER_LABELS[provider.name] ?? provider.name;

  useEffect(() => {
    setModel(provider.default_model ?? "");
  }, [provider.default_model]);

  return (
    <div className="rounded-lg border border-border/40 px-4 py-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-medium">{label}</span>
          {provider.has_key ? (
            <Badge variant="outline" className="font-mono text-[7px] uppercase border-emerald-500/30 text-emerald-500">
              key set
            </Badge>
          ) : (
            <Badge variant="outline" className="font-mono text-[7px] uppercase border-amber-500/30 text-amber-500">
              no key
            </Badge>
          )}
        </div>
        <Toggle checked={provider.enabled} onChange={onToggle} />
      </div>
      {/* API key row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={show ? "text" : "password"}
            placeholder={provider.has_key ? "••••••••••••  (leave blank to keep)" : "Paste API key…"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-3 py-1.5 pr-9 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-foreground/20"
          />
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {show ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
          </button>
        </div>
        <SaveButton
          dirty={apiKey.length > 0}
          saving={keySaving}
          saved={keySaved}
          error={saveStatus[vaultKey] === "error"}
          onSave={() => { if (apiKey) { onSaveKey(vaultKey, apiKey); setApiKey(""); } }}
          label="Save"
        />
      </div>
      {/* Model row */}
      <div className="flex gap-2 items-center">
        <label className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground whitespace-nowrap">
          Model
        </label>
        {provider.available_models.length > 0 ? (
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-foreground/20"
          >
            {model && !provider.available_models.includes(model) && (
              <option value={model}>{model}</option>
            )}
            {provider.available_models.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            placeholder="e.g. openrouter/anthropic/claude-3-5-haiku"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-foreground/20"
          />
        )}
        <SaveButton
          dirty={model !== (provider.default_model ?? "")}
          saving={modelSaving}
          saved={modelSaved}
          error={saveStatus[modelKey] === "error"}
          onSave={() => { if (model !== (provider.default_model ?? "")) onSaveModel(model); }}
          label="Save"
        />
      </div>
    </div>
  );
}

// ---- Vault section ----

function VaultSection({ settings }: { settings: SettingsData }) {
  return (
    <section>
      <SectionTitle>Vault</SectionTitle>
      <div className="mt-3 rounded-lg border border-border/40 px-4 py-3 flex items-center gap-3">
        <div className={cn("size-2 rounded-full", settings.vault_unlocked ? "bg-emerald-500" : "bg-amber-500")} />
        <span className="font-mono text-xs">
          {settings.vault_unlocked ? "Vault unlocked" : "Vault locked"}
        </span>
        {!settings.vault_unlocked && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            Set ELOPHANTO_VAULT_PASSWORD secret in Fly dashboard
          </span>
        )}
        {settings.vault_unlocked && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            {settings.vault_keys.length} key{settings.vault_keys.length !== 1 ? "s" : ""} stored
          </span>
        )}
      </div>
    </section>
  );
}

// ---- Shared UI pieces ----

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
      {children}
    </h2>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-4 w-7 items-center rounded-full transition-colors",
        checked ? "bg-emerald-500" : "bg-muted"
      )}
    >
      <span
        className={cn(
          "inline-block size-3 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-3.5" : "translate-x-0.5"
        )}
      />
    </button>
  );
}

function SaveButton({
  dirty,
  saving,
  saved,
  error,
  onSave,
  label = "Save",
}: {
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  error?: boolean;
  onSave: () => void;
  label?: string;
}) {
  return (
    <button
      onClick={onSave}
      disabled={(!dirty && !saved && !error) || saving}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
        saved
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
          : error
          ? "border-red-500/30 bg-red-500/10 text-red-400"
          : dirty
          ? "border-foreground/30 bg-foreground/10 text-foreground hover:bg-foreground/15"
          : "border-border text-muted-foreground/40 cursor-not-allowed"
      )}
    >
      {saving ? (
        <Loader2 className="size-3 animate-spin" />
      ) : saved ? (
        <Check className="size-3" />
      ) : error ? (
        <AlertCircle className="size-3" />
      ) : null}
      {saved ? "Saved" : error ? "Failed" : label}
    </button>
  );
}

// ---- Raw config viewer (read-only, collapsible) ----

function ConfigSection({ name, value }: { name: string; value: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const isObject = typeof value === "object" && value !== null && !Array.isArray(value);

  if (!isObject) {
    return (
      <div className="flex items-center justify-between rounded-md px-3 py-1.5">
        <span className="font-mono text-[11px] text-muted-foreground">{name}</span>
        <ConfigValue value={value} />
      </div>
    );
  }

  const entries = Object.entries(value as ConfigData);
  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-foreground/[2%]"
      >
        {expanded ? <ChevronDown className="size-2.5 text-muted-foreground/50" /> : <ChevronRight className="size-2.5 text-muted-foreground/50" />}
        <span className="font-mono text-[11px] text-muted-foreground">{name}</span>
      </button>
      {expanded && (
        <div className="ml-4 border-l border-border/20 pl-3 space-y-0.5">
          {entries.map(([k, v]) => (
            <ConfigSection key={k} name={k} value={v} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConfigValue({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    return value
      ? <Check className="size-3 text-emerald-500" />
      : <AlertCircle className="size-3 text-muted-foreground/30" />;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="font-mono text-[10px] text-muted-foreground/30">[]</span>;
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <Badge key={i} variant="outline" className="font-mono text-[8px]">{String(v)}</Badge>
        ))}
      </div>
    );
  }
  if (value === null || value === undefined || value === "") {
    return <span className="font-mono text-[10px] text-muted-foreground/30">—</span>;
  }
  return <span className="font-mono text-[11px]">{String(value)}</span>;
}
