/**
 * Minimal type stubs replacing @schema-ink/plugin-sdk.
 *
 * The aware-agent's BrowserPlugin (index.ts) imports three interfaces from
 * the SDK.  We provide compatible definitions here so the plugin works
 * standalone inside our bridge without the full framework.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface AgentContext {
  getConfig<T = unknown>(key: string): T | undefined;
  log: {
    info(...args: any[]): void;
    warn(...args: any[]): void;
    error(...args: any[]): void;
    debug(...args: any[]): void;
  };
}

export interface PluginCapability {
  type: 'tool';
  name: string;
  description: string;
  schema: Record<string, any>;
  execute: (args: any, context: AgentContext) => Promise<any>;
}

export interface AwarePlugin {
  name: string;
  version: string;
  description: string;
  capabilities: PluginCapability[];
  onLoad(context: AgentContext): Promise<void>;
  onUnload?(): Promise<void>;
}
