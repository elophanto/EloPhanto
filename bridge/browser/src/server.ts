/**
 * EloPhanto Bridge Server — JSON-RPC over stdin/stdout.
 *
 * Loads the full BrowserPlugin (44 tools) and exposes them to Python
 * via newline-delimited JSON messages.
 *
 * Protocol:
 *   Request:  {"id": 1, "method": "call_tool", "params": {"name": "browser_navigate", "args": {"url": "..."}}}
 *   Response: {"id": 1, "result": {"success": true, "url": "...", "title": "..."}}
 *   Error:    {"id": 1, "error": {"message": "...", "code": -1}}
 *
 *   Lifecycle:
 *     {"id": 1, "method": "initialize", "params": {"mode": "chrome_profile", ...}}
 *     {"id": 2, "method": "list_tools", "params": {}}
 *     {"id": 3, "method": "close", "params": {}}
 */

import BrowserPlugin from './index.js';
import type { AgentContext } from './types.js';
import * as readline from 'readline';

const plugin = new (BrowserPlugin as any)() as InstanceType<typeof BrowserPlugin>;
let mockContext: AgentContext | null = null;

// ------------------------------------------------------------------
// Redirect console to stderr so stdout stays clean for JSON-RPC
// ------------------------------------------------------------------

console.log = (...args: unknown[]) => process.stderr.write(args.join(' ') + '\n');
console.warn = (...args: unknown[]) => process.stderr.write('[WARN] ' + args.join(' ') + '\n');
console.error = (...args: unknown[]) => process.stderr.write('[ERROR] ' + args.join(' ') + '\n');

// ------------------------------------------------------------------
// RPC handlers
// ------------------------------------------------------------------

type Handler = (params: Record<string, unknown>) => Promise<unknown>;

const handlers: Record<string, Handler> = {
  /**
   * Initialize the browser plugin with config from Python.
   * Config keys are flat (matching BrowserPlugin.onLoad expectations):
   *   mode, headless, cdpPort, cdpWsEndpoint, userDataDir, copyProfile,
   *   useSystemChrome, openrouterKey, visionModel, visionMaxTokens, etc.
   */
  initialize: async (params) => {
    const configMap = new Map(Object.entries(params));
    mockContext = {
      getConfig: <T = unknown>(key: string): T | undefined => configMap.get(key) as T | undefined,
      log: {
        info: (...args: any[]) => process.stderr.write('[INFO] ' + args.join(' ') + '\n'),
        warn: (...args: any[]) => process.stderr.write('[WARN] ' + args.join(' ') + '\n'),
        error: (...args: any[]) => process.stderr.write('[ERROR] ' + args.join(' ') + '\n'),
        debug: (...args: any[]) => process.stderr.write('[DEBUG] ' + args.join(' ') + '\n'),
      },
    };

    await plugin.onLoad(mockContext);

    const toolNames = plugin.capabilities.map((c) => c.name);
    return { ok: true, toolCount: toolNames.length, tools: toolNames };
  },

  /**
   * List all available browser tools with their schemas.
   */
  list_tools: async () => {
    return {
      tools: plugin.capabilities.map((c) => ({
        name: c.name,
        description: c.description,
        parameters: c.schema,
      })),
    };
  },

  /**
   * Call any browser tool by name.
   * This is the primary dispatch method — all 44 tools go through here.
   */
  call_tool: async (params) => {
    const name = params.name as string;
    const args = (params.args || {}) as Record<string, unknown>;

    if (!name) throw new Error('call_tool requires a "name" parameter');

    const capability = plugin.capabilities.find((c) => c.name === name);
    if (!capability) {
      throw new Error(`Unknown tool: ${name}. Available: ${plugin.capabilities.map((c) => c.name).join(', ')}`);
    }

    if (!mockContext) {
      throw new Error('Plugin not initialized — call initialize first');
    }

    return await capability.execute(args, mockContext);
  },

  /**
   * Close the browser and clean up.
   */
  close: async () => {
    if (plugin.onUnload) {
      await plugin.onUnload();
    }
    return { ok: true };
  },
};

// ------------------------------------------------------------------
// JSON-RPC main loop
// ------------------------------------------------------------------

function send(obj: unknown): void {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on('line', async (line: string) => {
  let id: number | string | null = null;
  try {
    const msg = JSON.parse(line);
    id = msg.id ?? null;
    const method = msg.method as string;
    const params = (msg.params || {}) as Record<string, unknown>;

    const handler = handlers[method];
    if (!handler) {
      send({ id, error: { message: `Unknown method: ${method}`, code: -32601 } });
      return;
    }

    const result = await handler(params);
    send({ id, result });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    send({ id, error: { message, code: -1 } });
  }
});

rl.on('close', async () => {
  if (plugin.onUnload) {
    try { await plugin.onUnload(); } catch { /* ignore */ }
  }
  process.exit(0);
});

// Signal readiness
send({ id: null, result: { ready: true, pid: process.pid } });
