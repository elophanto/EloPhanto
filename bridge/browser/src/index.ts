/**
 * Browser Plugin - Direct Playwright browser automation
 * Opens real Chrome and supports CDP connections
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import type { AwarePlugin, AgentContext, PluginCapability } from './types.js';
import { AwareBrowserAgent, getDefaultChromeUserDataDir, getCdpWsEndpoint } from './browser-agent.js';

interface BrowserConfig {
  /**
   * Connection mode:
   * - 'cdp': Connect to existing Chrome (start Chrome with --remote-debugging-port=9222)
   * - 'chrome_profile': Launch Chrome with your user profile (cookies, extensions, sessions)
   * - 'fresh': Launch clean Chrome instance (uses system Chrome by default)
   */
  mode?: 'fresh' | 'chrome_profile' | 'cdp';
  cdpPort?: number;
  cdpWsEndpoint?: string;
  headless?: boolean;
  userDataDir?: string;
  profileDirectory?: string;
  copyProfile?: boolean;
  useSystemChrome?: boolean;
  viewport?: { width: number; height: number };
  openrouterKey?: string;
  visionModel?: string;
  visionMaxTokens?: number;
  visionRetryOnLength?: boolean;
  visionRetryMaxTokens?: number;
}

// Keep this aligned with `launch.sh` which exports SCHEMA_INK_DIR.
// - SCHEMA_INK_CONFIG_DIR: legacy/alternate name (some plugins/tools used this)
// - SCHEMA_INK_DIR: canonical runtime config dir used by the launcher
// Fall back to ./data (repo-relative) for dev usage.
const CONFIG_DIR = path.resolve(
  process.env.SCHEMA_INK_CONFIG_DIR ||
    process.env.SCHEMA_INK_DIR ||
    './data'
);

export default class BrowserPlugin implements AwarePlugin {
  name = 'browser';
  version = '5.1.0';
  description = 'Browser automation using Playwright with real Chrome support';
  author = 'aware-agent';

  private agent!: AgentContext;
  private browser: AwareBrowserAgent | null = null;
  private config: BrowserConfig = {
    mode: 'fresh',
    headless: false,
  };

  capabilities: PluginCapability[] = [
    {
      type: 'tool',
      name: 'browser_navigate',
      description: `Navigate to a URL. Opens Chrome browser if not already open.
Returns the page URL, title, and interactive elements.
Use the element indices with browser_click and browser_type.`,
      schema: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'URL to navigate to' },
        },
        required: ['url'],
      },
      execute: async (params: unknown) => {
        const { url } = params as { url: string };
        return this.navigate(url);
      },
    },
    {
      type: 'tool',
      name: 'browser_click',
      description: `Click an element by its index from browser_navigate output.
Indices are shown as [0], [1], [2] etc.`,
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Element index to click' },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => {
        const { index } = params as { index: number };
        return this.click(index);
      },
    },
    {
      type: 'tool',
      name: 'browser_click_text',
      description: `Click an INTERACTIVE element (button, link, input, select, etc.) by matching its visible text (or aria-label/title).
Only matches clickable elements — NOT plain page text, headings, or instructional content.
Use browser_get_elements first to see what's actually clickable. Use browser_click (by index) when you know the element index.`,
      schema: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'Text to match (substring match by default)' },
          exact: { type: 'boolean', description: 'If true, require an exact match (default: false)' },
          caseSensitive: { type: 'boolean', description: 'If true, match case-sensitively (default: false)' },
          nth: { type: 'number', description: 'If multiple matches exist, pick the nth match (0-based, default: 0)' },
        },
        required: ['text'],
      },
      execute: async (params: unknown) => {
        const { text, exact, caseSensitive, nth } = params as { text: string; exact?: boolean; caseSensitive?: boolean; nth?: number };
        return this.clickText(text, exact, caseSensitive, nth);
      },
    },
    {
      type: 'tool',
      name: 'browser_click_batch',
      description: `Click multiple elements in rapid succession within a single tool call.
Use this when the page requires clicking several elements quickly (e.g., split-part labels whose values rotate after each click, multi-step reveals).
Each target can be specified by text match or element index from browser_get_elements. All clicks happen in one tool invocation — no round-trips between clicks.`,
      schema: {
        type: 'object',
        properties: {
          texts: {
            type: 'array',
            items: { type: 'string' },
            description: 'Array of text labels to click (substring match). Order matters.',
          },
          indices: {
            type: 'array',
            items: { type: 'number' },
            description: 'Array of element indices to click (from browser_get_elements). Order matters.',
          },
          exact: { type: 'boolean', description: 'If true, require exact text match for text targets (default: false)' },
        },
      },
      execute: async (params: unknown) => {
        const { texts, indices, exact } = params as {
          texts?: string[]; indices?: number[]; exact?: boolean;
        };
        const browser = await this.ensureBrowser();

        const targets: Array<{ text: string; exact?: boolean } | { index: number }> = [];
        if (indices && indices.length > 0) {
          for (const idx of indices) targets.push({ index: idx });
        } else if (texts && texts.length > 0) {
          for (const t of texts) targets.push({ text: t, exact: exact ?? false });
        } else {
          return { success: false, error: 'Provide either texts or indices array.' };
        }

        const result = await browser.clickBatch(targets);

        // Success hardening — ALL clicks must succeed for batch to be considered successful.
        // Partial success (e.g. 1/3) misleads the planner into thinking the action worked.
        if (result.clicks.length === 0) {
          return { success: false, error: 'No click targets provided.', ...result };
        }
        const failedClicks = result.clicks.filter(c => !c.success);
        if (failedClicks.length > 0) {
          const failedTargets = failedClicks.map(c => c.target).join(', ');
          return {
            success: false,
            error: `${failedClicks.length}/${result.clicks.length} clicks failed (${failedTargets}). Batch requires all clicks to succeed.`,
            ...result,
          };
        }

        return { success: true, ...result };
      },
    },
    {
      type: 'tool',
      name: 'browser_eval',
      description: `Execute JavaScript in the page context (like the browser DevTools console).
Primary use: READ and INSPECT — variables, DOM attributes, script source, storage, cookies, computed styles.
Can also dispatch UI events (click, input, hover) when normal tools can't reach an element.
Do NOT override validation functions, call success handlers, remove/delete elements, or set innerHTML — these mutations break page state irreversibly.
The result is JSON-stringified in the page and returned as a string.`,
      schema: {
        type: 'object',
        properties: {
          expression: { type: 'string', description: 'JavaScript expression to evaluate (e.g., "document.title", "location.href")' },
          maxLength: { type: 'number', description: 'Max characters of returned JSON string (default: 8000)' },
        },
        required: ['expression'],
      },
      execute: async (params: unknown) => {
        const { expression, maxLength } = params as { expression: string; maxLength?: number };
        return this.evalExpression(expression, maxLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_type',
      description: `Type text into an input field by its index.
Set 'enter' to true to submit forms after typing.`,
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Input element index' },
          text: { type: 'string', description: 'Text to type' },
          enter: { type: 'boolean', description: 'Press Enter after typing' },
        },
        required: ['index', 'text'],
      },
      execute: async (params: unknown) => {
        const { index, text, enter } = params as { index: number; text: string | unknown; enter?: boolean };
        const textStr = this.ensureTypedTextIsString(text);
        return this.type(index, textStr, enter);
      },
    },
    {
      type: 'tool',
      name: 'browser_scroll',
      description: 'Scroll the page up or down.',
      schema: {
        type: 'object',
        properties: {
          direction: { type: 'string', enum: ['up', 'down'], description: 'Scroll direction' },
          amount: { type: 'number', description: 'Pixels to scroll (default: 500)' },
        },
        required: ['direction'],
      },
      execute: async (params: unknown) => {
        const { direction, amount } = params as { direction: 'up' | 'down'; amount?: number };
        return this.scroll(direction, amount);
      },
    },
    {
      type: 'tool',
      name: 'browser_scroll_container',
      description: `Scroll within a modal, dialog, sidebar, or other scrollable container.
Use this instead of browser_scroll when content is inside a modal/popup that needs scrolling.
Auto-detects common modal patterns, or you can specify a CSS selector.`,
      schema: {
        type: 'object',
        properties: {
          direction: { type: 'string', enum: ['up', 'down'], description: 'Scroll direction' },
          amount: { type: 'number', description: 'Pixels to scroll (default: 300)' },
          container: { type: 'string', description: 'Optional CSS selector for the container (auto-detects modals if not provided)' },
        },
        required: ['direction'],
      },
      execute: async (params: unknown) => {
        const { direction, amount, container } = params as { direction: 'up' | 'down'; amount?: number; container?: string };
        return this.scrollContainer(direction, amount, container);
      },
    },
    {
      type: 'tool',
      name: 'browser_extract',
      description: 'Extract text content from the current page.',
      schema: {
        type: 'object',
        properties: {},
      },
      execute: async () => {
        return this.extractContent();
      },
    },
    {
      type: 'tool',
      name: 'browser_read_semantic',
      description: `High-signal, screen-reader-style compressed page view. Returns headings, landmarks, form fields, and buttons — LLM-friendly for long/dense pages. Use when browser_extract is too verbose or you need a structured overview.`,
      schema: {
        type: 'object',
        properties: {},
      },
      execute: async () => {
        return this.readSemantic();
      },
    },
    {
      type: 'tool',
      name: 'browser_screenshot',
      description: `Take a screenshot of the current page and analyze it.
Returns a detailed description of what's visible on the page including:
- Page type (login form, search results, forum, etc.)
- Key interactive elements (buttons, forms, links)
- Important text content
- Suggested next actions
Use highlight=true to overlay element indices on the screenshot (helps correlate visual elements with browser_get_elements indices).`,
      schema: {
        type: 'object',
        properties: {
          highlight: { type: 'boolean', description: 'If true, overlay element index labels on screenshot for visual grounding (default: false)' },
          forceVision: { type: 'boolean', description: 'If true, always run vision analysis even when text content looks sufficient (use after hover to see revealed visual content)' },
        },
      },
      execute: async (params: unknown) => {
        const { highlight, forceVision } = (params || {}) as { highlight?: boolean; forceVision?: boolean };
        return this.screenshot(highlight, forceVision);
      },
    },
    {
      type: 'tool',
      name: 'browser_wait',
      description: 'Wait for a specified time in milliseconds.',
      schema: {
        type: 'object',
        properties: {
          ms: { type: 'number', description: 'Milliseconds to wait' },
        },
        required: ['ms'],
      },
      execute: async (params: unknown) => {
        const { ms } = params as { ms: number };
        return this.wait(ms);
      },
    },
    {
      type: 'tool',
      name: 'browser_go_back',
      description: 'Navigate back to previous page.',
      schema: { type: 'object', properties: {} },
      execute: async () => this.goBack(),
    },
    {
      type: 'tool',
      name: 'browser_get_elements',
      description: 'Get list of interactive elements on the current page with their indices. Use showAll=true when you need to see ALL offscreen/hidden elements (e.g. to find a submit button on a long page).',
      schema: {
        type: 'object',
        properties: {
          showAll: { type: 'boolean', description: 'Show all offscreen/hidden elements without truncation (default: false)' },
          compact: { type: 'boolean', description: 'Compact output: one-line per element, no offscreen, 30-char text limit (default: false)' },
        },
      },
      execute: async (params: unknown) => {
        const { showAll, compact } = (params || {}) as { showAll?: boolean; compact?: boolean };
        return this.getElements(showAll, compact);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_html',
      description: 'Get the full HTML source code of the current page. Useful for finding hidden codes in data-* attributes, meta tags, HTML comments, or script variables that are not visible via browser_extract.',
      schema: {
        type: 'object',
        properties: {
          maxLength: {
            type: 'number',
            description: 'Optional: truncate HTML to this length (default: 50000)',
          },
        },
      },
      execute: async (params: unknown) => this.getPageHtml(params),
    },
    {
      type: 'tool',
      name: 'browser_get_element_html',
      description: 'Get the HTML source of a specific element by index. Useful for inspecting data-* attributes, ARIA labels, or inner HTML.',
      schema: {
        type: 'object',
        properties: {
          index: {
            type: 'number',
            description: 'Element index from browser_get_elements',
          },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => this.getElementHtml(params),
    },
    {
      type: 'tool',
      name: 'browser_inspect_element',
      description: `Inspect an interactive element by index and return its attributes and outerHTML preview.
Use this for rigorous debugging: verify labels, roles, data-* attributes, and DOM structure before acting.`,
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Element index to inspect (from browser_get_elements)' },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => {
        const { index } = params as { index: number };
        return this.inspectElement(index);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_meta',
      description: 'Get page meta tags (name/property/content). Useful for debugging SEO/OG tags, redirects, and app metadata.',
      schema: { type: 'object', properties: {} },
      execute: async () => this.getMeta(),
    },
    {
      type: 'tool',
      name: 'browser_read_scripts',
      description: `Read ALL page scripts (inline + external JS bundles) and search for patterns.
CRITICAL for SPAs/React apps where logic is in bundled JS files.
Default patterns search for: validation functions, hardcoded codes/answers, success handlers, submit listeners.
Use this BEFORE guessing codes — the answer is always in the source code.`,
      schema: {
        type: 'object',
        properties: {
          patterns: {
            type: 'array',
            items: { type: 'string' },
            description: 'Regex patterns to search for in script content. Defaults to common validation/answer patterns.',
          },
          maxLength: { type: 'number', description: 'Max output characters (default: 15000)' },
          includeInline: { type: 'boolean', description: 'Include inline script content when no pattern matches (default: true)' },
        },
      },
      execute: async (params: unknown) => {
        const { patterns, maxLength, includeInline } = (params || {}) as {
          patterns?: string[];
          maxLength?: number;
          includeInline?: boolean;
        };
        return this.readScripts(patterns, maxLength, includeInline);
      },
    },
    {
      type: 'tool',
      name: 'browser_deep_inspect',
      description: `Deep DOM inspection — scans ALL elements for hidden data that normal extraction misses.
Checks: data-* attributes, aria-* labels, custom attributes, HTML comments, CSS ::before/::after content, hidden elements, <noscript> blocks.
Returns a definitive "CLEAN DOM" signal when nothing is hidden — meaning the answer is in JavaScript source code (use browser_read_scripts).
Use this early in challenges to decide whether to focus on DOM or JS.`,
      schema: { type: 'object', properties: {} },
      execute: async () => this.deepInspect(),
    },
    {
      type: 'tool',
      name: 'browser_extract_hidden_code',
      description: `Extract hidden codes from the page DOM after click-N challenges.
Scans for: 6-character alphanumeric codes in data-* attributes, aria-label, text content, and dynamically revealed elements.
Use AFTER clicking the required number of times on hidden DOM challenges to find the revealed code.
Returns found codes with their source location for verification.`,
      schema: {
        type: 'object',
        properties: {
          elementIndex: { type: 'number', description: 'Optional: specific element index to scan for codes' },
          scanAll: { type: 'boolean', description: 'If true, scan entire page (default: true)' },
        },
      },
      execute: async (params: unknown) => {
        const { elementIndex, scanAll } = (params || {}) as { elementIndex?: number; scanAll?: boolean };
        return this.extractHiddenCode(elementIndex, scanAll ?? true);
      },
    },
    {
      type: 'tool',
      name: 'browser_full_audit',
      description: `ONE-CALL page audit: runs deep DOM inspection + JS source search + storage + meta + cookies in parallel.
Returns a combined report in a SINGLE tool call, replacing 5+ separate calls.
USE THIS instead of calling browser_deep_inspect, browser_read_scripts, browser_get_storage, browser_get_meta, browser_get_cookies separately.
This is the FASTEST way to analyze a page for hidden data.`,
      schema: {
        type: 'object',
        properties: {
          patterns: {
            type: 'array',
            items: { type: 'string' },
            description: 'Optional regex patterns for JS source search (defaults to validation/answer patterns)',
          },
        },
      },
      execute: async (params: unknown) => {
        const { patterns } = (params || {}) as { patterns?: string[] };
        return this.fullAudit(patterns);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_console',
      description: `Get recent browser console logs (console.log/warn/error) and page errors.
Use this like DevTools Console for debugging and puzzle hints.`,
      schema: {
        type: 'object',
        properties: {
          limit: { type: 'number', description: 'Max entries to return (default: 50)' },
          clear: { type: 'boolean', description: 'If true, clear stored logs after returning (default: false)' },
          types: {
            type: 'array',
            items: { type: 'string' },
            description: 'Optional filter: console types to include (e.g., ["error","warning","log","pageerror"])',
          },
        },
      },
      execute: async (params: unknown) => {
        const { limit, clear, types } = (params || {}) as { limit?: number; clear?: boolean; types?: string[] };
        return this.getConsoleLogs(limit, clear, types);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_network',
      description: `Get recent network request/response log (HAR-like).
Use this like DevTools Network to find hidden API responses, redirects, or challenge hints.`,
      schema: {
        type: 'object',
        properties: {
          limit: { type: 'number', description: 'Max records to return (default: 30)' },
          clear: { type: 'boolean', description: 'If true, clear stored network log after returning (default: false)' },
          urlContains: { type: 'string', description: 'Optional: only include URLs containing this substring' },
          onlyErrors: { type: 'boolean', description: 'If true, only include failed/HTTP>=400 records (default: false)' },
          includeHeaders: { type: 'boolean', description: 'If true, include redacted request/response headers (default: false)' },
          includeResponseBody: { type: 'boolean', description: 'If true, include truncated response body for each record (default: false)' },
          maxBodyLength: { type: 'number', description: 'Max characters of each included response body (default: 4000)' },
        },
      },
      execute: async (params: unknown) => {
        const {
          limit,
          clear,
          urlContains,
          onlyErrors,
          includeHeaders,
          includeResponseBody,
          maxBodyLength,
        } = (params || {}) as {
          limit?: number;
          clear?: boolean;
          urlContains?: string;
          onlyErrors?: boolean;
          includeHeaders?: boolean;
          includeResponseBody?: boolean;
          maxBodyLength?: number;
        };
        return this.getNetworkLogs(limit, clear, urlContains, onlyErrors, includeHeaders, includeResponseBody, maxBodyLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_response_body',
      description: 'Get the response body (truncated) for a specific network record ID from browser_get_network.',
      schema: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Network record id (e.g., "net_...")' },
          maxLength: { type: 'number', description: 'Max characters to return (default: 8000)' },
        },
        required: ['id'],
      },
      execute: async (params: unknown) => {
        const { id, maxLength } = params as { id: string; maxLength?: number };
        return this.getResponseBody(id, maxLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_storage',
      description: `Get localStorage/sessionStorage snapshot (keys by default; values optional).
Useful for puzzles that hide codes in storage.`,
      schema: {
        type: 'object',
        properties: {
          scope: { type: 'string', enum: ['local', 'session', 'all'], description: 'Which storage to return (default: all)' },
          includeValues: { type: 'boolean', description: 'If true, include (truncated) values (default: false)' },
          maxValueLength: { type: 'number', description: 'Max characters per value when includeValues=true (default: 200)' },
        },
      },
      execute: async (params: unknown) => {
        const { scope, includeValues, maxValueLength } = (params || {}) as {
          scope?: 'local' | 'session' | 'all';
          includeValues?: boolean;
          maxValueLength?: number;
        };
        return this.getStorage(scope, includeValues, maxValueLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_cookies',
      description: `Get cookies for the current page/domain (names by default; values optional).
Useful for debugging auth/redirect flows and some CTF-like puzzles.`,
      schema: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'Optional URL to scope cookies to (defaults to current page URL)' },
          includeValues: { type: 'boolean', description: 'If true, include cookie values (default: false)' },
          maxValueLength: { type: 'number', description: 'Max characters per cookie value when includeValues=true (default: 120)' },
        },
      },
      execute: async (params: unknown) => {
        const { url, includeValues, maxValueLength } = (params || {}) as {
          url?: string;
          includeValues?: boolean;
          maxValueLength?: number;
        };
        return this.getCookies(url, includeValues, maxValueLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_dom_search',
      description: `Search the DOM (including non-interactive elements) for text or attribute matches.
This is similar to DevTools Elements search (Ctrl+F).`,
      schema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Substring to search for (case-insensitive)' },
          in: { type: 'string', enum: ['text', 'attributes', 'all'], description: 'Where to search (default: all)' },
          includeHidden: { type: 'boolean', description: 'Include hidden/offscreen elements (default: true)' },
          maxResults: { type: 'number', description: 'Max matches to return (default: 20)' },
          maxSnippetLength: { type: 'number', description: 'Max characters for snippets (default: 240)' },
          includeAllAttributes: { type: 'boolean', description: 'If true, return all attributes (default: false)' },
        },
        required: ['query'],
      },
      execute: async (params: unknown) => {
        const {
          query,
          in: where,
          includeHidden,
          maxResults,
          maxSnippetLength,
          includeAllAttributes,
        } = (params || {}) as {
          query: string;
          in?: 'text' | 'attributes' | 'all';
          includeHidden?: boolean;
          maxResults?: number;
          maxSnippetLength?: number;
          includeAllAttributes?: boolean;
        };
        return this.domSearch(query, where, includeHidden, maxResults, maxSnippetLength, includeAllAttributes);
      },
    },
    {
      type: 'tool',
      name: 'browser_new_tab',
      description: 'Open a new browser tab, optionally navigating to a URL. Use this to keep multiple pages open (e.g., main site + temp email service).',
      schema: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'URL to open in new tab (optional)' },
        },
      },
      execute: async (params: unknown) => {
        const { url } = params as { url?: string };
        return this.newTab(url);
      },
    },
    {
      type: 'tool',
      name: 'browser_list_tabs',
      description: 'List all open browser tabs with their URLs and titles.',
      schema: { type: 'object', properties: {} },
      execute: async () => this.listTabs(),
    },
    {
      type: 'tool',
      name: 'browser_switch_tab',
      description: 'Switch to a different tab by its index number.',
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Tab index to switch to (from browser_list_tabs)' },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => {
        const { index } = params as { index: number };
        return this.switchTab(index);
      },
    },
    {
      type: 'tool',
      name: 'browser_close_tab',
      description: 'Close a tab by index, or close the current tab if no index provided.',
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Tab index to close (optional, defaults to current tab)' },
        },
      },
      execute: async (params: unknown) => {
        const { index } = params as { index?: number };
        return this.closeTab(index);
      },
    },
    {
      type: 'tool',
      name: 'browser_click_at',
      description: `Click at specific x,y coordinates on the page. Use this for canvas elements, custom widgets, or when element indices don't work.`,
      schema: {
        type: 'object',
        properties: {
          x: { type: 'number', description: 'X coordinate (pixels from left)' },
          y: { type: 'number', description: 'Y coordinate (pixels from top)' },
        },
        required: ['x', 'y'],
      },
      execute: async (params: unknown) => {
        const { x, y } = params as { x: number; y: number };
        const browser = await this.ensureBrowser();
        await browser.clickAt(x, y);
        return { success: true, clicked: { x, y } };
      },
    },
    {
      type: 'tool',
      name: 'browser_press_key',
      description: `Press a keyboard key. Use for hotkeys, Enter, Escape, Tab, arrow keys, etc. Key names follow Playwright conventions (e.g. "Enter", "Escape", "ArrowDown", "Control+a").`,
      schema: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'Key to press (e.g. "Enter", "Escape", "Tab", "ArrowDown", "Control+c")' },
        },
        required: ['key'],
      },
      execute: async (params: unknown) => {
        const { key } = params as { key: string };
        const browser = await this.ensureBrowser();
        await browser.pressKey(key);
        return { success: true, pressed: key };
      },
    },
    {
      type: 'tool',
      name: 'browser_type_text',
      description: `Type text using the keyboard without targeting a specific element. Useful when focus is already set or for typing into canvas/custom inputs.`,
      schema: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'Text to type' },
          pressEnter: { type: 'boolean', description: 'Press Enter after typing (default: false)' },
        },
        required: ['text'],
      },
      execute: async (params: unknown) => {
        const { text, pressEnter } = params as { text: string; pressEnter?: boolean };
        const browser = await this.ensureBrowser();
        await browser.typeText(text, pressEnter ?? false);
        return { success: true, typed: text };
      },
    },
    {
      type: 'tool',
      name: 'browser_drag_drop',
      description: `Drag an element from one position to another. Supports index-based (preferred) and coordinate-based dragging.
Index-based: pass fromIndex + toIndex (element indices from browser_get_elements). Deterministic and scroll-safe.
Coordinate-based: pass fromX/fromY + toX/toY. Use only when no element index is available.
Dispatches both pointer events (mouse down/move/up) and HTML5 drag events for maximum compatibility.
Use this for drag-and-drop puzzles, sortable lists, sliders, etc.`,
      schema: {
        type: 'object',
        properties: {
          fromIndex: { type: 'number', description: 'Source element index from browser_get_elements (preferred)' },
          toIndex: { type: 'number', description: 'Target element index from browser_get_elements (preferred)' },
          fromX: { type: 'number', description: 'Source X coordinate (use only if no element index)' },
          fromY: { type: 'number', description: 'Source Y coordinate (use only if no element index)' },
          toX: { type: 'number', description: 'Target X coordinate (use only if no element index)' },
          toY: { type: 'number', description: 'Target Y coordinate (use only if no element index)' },
          steps: { type: 'number', description: 'Number of intermediate mouse move steps (default: 10)' },
        },
      },
      execute: async (params: unknown) => {
        const { fromIndex, toIndex, fromX, fromY, toX, toY, steps } = params as {
          fromIndex?: number; toIndex?: number;
          fromX?: number; fromY?: number; toX?: number; toY?: number;
          steps?: number;
        };
        const browser = await this.ensureBrowser();

        // Index-based drag (preferred)
        if (fromIndex !== undefined && toIndex !== undefined) {
          if (fromIndex === toIndex) {
            throw new Error(`browser_drag_drop: fromIndex === toIndex (${fromIndex}). This is a no-op — you must drag FROM a [DRAGGABLE] piece TO a different target/slot element.`);
          }
          const result = await browser.dragDropByIndex(fromIndex, toIndex, steps ? { steps } : undefined);
          const resp: Record<string, unknown> = { success: true, mode: 'index', fromIndex, toIndex, ...result };
          if (result.warning) resp.success = false; // Flag as not-success if source isn't draggable or target is also draggable
          return resp;
        }

        // Coordinate-based drag (fallback)
        if (fromX !== undefined && fromY !== undefined && toX !== undefined && toY !== undefined) {
          if (fromX === toX && fromY === toY) {
            throw new Error('browser_drag_drop: source and target coordinates are identical. This is a no-op.');
          }
          await browser.dragDrop(
            { x: fromX, y: fromY },
            { x: toX, y: toY },
            steps ? { steps } : undefined
          );
          return { success: true, mode: 'coordinate', from: { x: fromX, y: fromY }, to: { x: toX, y: toY } };
        }

        throw new Error('browser_drag_drop requires either (fromIndex + toIndex) or (fromX + fromY + toX + toY)');
      },
    },
    {
      type: 'tool',
      name: 'browser_drag_solve',
      description: `Deterministic drag-and-drop solver. Scans ALL draggable elements and target slots on the page, maps them, and executes all drag-drops in one atomic call.
Use this INSTEAD of multiple individual browser_drag_drop calls. It eliminates round-trip overhead and handles slot detection automatically.
Strategies:
- sequential (default): pairs draggable[i] → slot[i] in DOM order.
- textMatch: matches draggable text content to slot text/labels.
- positional: sorts by Y then X position and pairs nearest.
If auto-detection misses slots, pass slotSelector (CSS selector) explicitly.`,
      schema: {
        type: 'object',
        properties: {
          slotSelector: { type: 'string', description: 'CSS selector for target drop slots. If omitted, auto-detects from [data-drop], [class*="drop"], [class*="slot"], [role="listbox"], etc.' },
          maxDrops: { type: 'number', description: 'Max number of drops to execute (default: 20)' },
          strategy: { type: 'string', enum: ['sequential', 'textMatch', 'positional'], description: 'Pairing strategy (default: sequential)' },
        },
      },
      execute: async (params: unknown) => {
        const { slotSelector, maxDrops, strategy } = params as {
          slotSelector?: string; maxDrops?: number; strategy?: 'positional' | 'textMatch' | 'sequential';
        };
        const browser = await this.ensureBrowser();
        const result = await browser.dragSolve({ slotSelector, maxDrops, strategy });

        const drops = result.drops || [];

        // No drops executed
        if (drops.length === 0) {
          return {
            success: false,
            error: result.summary || (result.draggables === 0
              ? 'No draggable elements found on page.'
              : result.slots === 0
                ? `Found ${result.draggables} draggable(s) but no target slots. Use slotSelector parameter.`
                : 'Pairing produced zero pairs.'),
            ...result,
          };
        }

        // All drops failed
        const allFailed = drops.every((d: { success: boolean }) => !d.success);
        if (allFailed) {
          return {
            success: false,
            error: `All ${drops.length} drops failed. ` +
              drops.map((d: { error?: string }) => d.error || 'unknown').join('; '),
            ...result,
          };
        }

        // Self-slot pairing is already detected and rejected inside dragSolve() discovery.
        // No need for a redundant check here — drops use pair ordinals, not element indices.

        // Post-condition failure: drops reported success but slots didn't change
        const verification = (result as Record<string, unknown>).slotVerification as
          { slotsUnchanged?: boolean } | undefined;
        if (verification?.slotsUnchanged) {
          return {
            success: false,
            error: 'Drag operations reported success but page slot state is unchanged. ' +
              'Drags may not have registered. Try browser_drag_drop with explicit indices or dismiss overlays first.',
            ...result,
          };
        }

        const succeeded = drops.filter((d: { success: boolean }) => d.success).length;
        return {
          success: true,
          ...result,
          summary: result.summary + (succeeded < drops.length
            ? ` WARNING: ${drops.length - succeeded} drop(s) failed.`
            : ''),
        };
      },
    },
    {
      type: 'tool',
      name: 'browser_drag_brute_force',
      description: 'Brute-force drag-and-drop solver. Tries dropping every draggable element onto every plausible target container using synthetic HTML5 drag events. Use when browser_drag_solve fails to fill any slots.',
      schema: {
        type: 'object',
        properties: {},
      },
      execute: async () => {
        const browser = await this.ensureBrowser();
        return browser.dragSolveBruteForce();
      },
    },
    {
      type: 'tool',
      name: 'browser_hover',
      description: `Hover over a specific position on the page. Use for tooltips, dropdown menus, hover-reveal puzzles, etc.
The mouse stays at the position for the specified duration to trigger hover effects.`,
      schema: {
        type: 'object',
        properties: {
          x: { type: 'number', description: 'X coordinate to hover over' },
          y: { type: 'number', description: 'Y coordinate to hover over' },
          durationMs: { type: 'number', description: 'How long to hover in milliseconds (default: 500)' },
        },
        required: ['x', 'y'],
      },
      execute: async (params: unknown) => {
        const { x, y, durationMs } = params as { x: number; y: number; durationMs?: number };
        const holdMs = durationMs ?? 500;
        const browser = await this.ensureBrowser();
        await browser.hoverAt(x, y);
        if (holdMs > 0) {
          await new Promise(r => setTimeout(r, holdMs));
        }
        return { success: true, hovered: { x, y }, durationMs: holdMs };
      },
    },
    {
      type: 'tool',
      name: 'browser_hover_element',
      description: `Hover over an interactive element by index from browser_get_elements.
This is the preferred hover tool for challenge flows because it is deterministic (no coordinate guessing).
It scrolls the target into view, dispatches hover events, and holds for the requested duration.`,
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Element index from browser_get_elements' },
          durationMs: { type: 'number', description: 'Hover hold duration in milliseconds (default: 1200)' },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => {
        const { index, durationMs } = params as { index: number; durationMs?: number };
        return this.hoverElement(index, durationMs);
      },
    },
    {
      type: 'tool',
      name: 'browser_get_element_box',
      description: 'Get the bounding box of an element by index. Returns x, y, width, height in viewport pixels, plus viewport dimensions. Use this before browser_pointer_path with relative coordinates to draw on canvas elements.',
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Element index from browser_get_elements' },
        },
        required: ['index'],
      },
      execute: async (params: unknown) => {
        const { index } = params as { index: number };
        const browser = await this.ensureBrowser();
        return browser.getElementBox(index);
      },
    },
    {
      type: 'tool',
      name: 'browser_pointer_path',
      description: `Execute a continuous pointer path (drawing/gesture). Sends real pointerdown → pointermove… → pointerup through the browser input pipeline.
Use this for drawing on canvas, gesture recognition, signature pads, slider tracks, and any interaction requiring a continuous stroke.
With elementIndex + relative: true, points are normalized 0..1 within the element box (so {x:0, y:0} = top-left, {x:1, y:1} = bottom-right).
Without elementIndex, points are absolute viewport pixel coordinates.
Call browser_get_element_box first to understand the target area dimensions.`,
      schema: {
        type: 'object',
        properties: {
          elementIndex: { type: 'number', description: 'Target element index from browser_get_elements (optional). Used for coordinate mapping.' },
          points: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                x: { type: 'number', description: 'X coordinate (0..1 if relative, pixels if absolute)' },
                y: { type: 'number', description: 'Y coordinate (0..1 if relative, pixels if absolute)' },
              },
              required: ['x', 'y'],
            },
            description: 'Ordered waypoints defining the path. Minimum 2 points.',
          },
          relative: { type: 'boolean', description: 'If true, points are 0..1 normalized within elementIndex bounding box (default: false)' },
          pointerType: { type: 'string', enum: ['mouse', 'touch'], description: 'Pointer type (default: mouse)' },
          durationMs: { type: 'number', description: 'Total path duration in ms (default: 300). Longer = slower stroke.' },
        },
        required: ['points'],
      },
      execute: async (params: unknown) => {
        const p = params as {
          elementIndex?: number;
          points: Array<{ x: number; y: number }>;
          relative?: boolean;
          pointerType?: 'mouse' | 'touch';
          durationMs?: number;
        };
        if (!p.points || p.points.length < 2) {
          return { success: false, error: 'browser_pointer_path requires at least 2 points.' };
        }
        if (p.relative && p.elementIndex === undefined) {
          return { success: false, error: 'relative: true requires elementIndex to map normalized coordinates.' };
        }
        const browser = await this.ensureBrowser();
        return browser.pointerPath(p);
      },
    },
    {
      type: 'tool',
      name: 'browser_select_option',
      description: `Select an option from a <select> dropdown, or check/uncheck a radio button or checkbox.
Uses Playwright's native APIs (selectOption/setChecked) which properly trigger framework events (React, Angular, Vue).
Works with: <select>, <input type="radio">, <input type="checkbox">, [role="radio"], [role="checkbox"], and <label> elements.
Prefer this over browser_click for form controls — it handles event dispatch, aria state, and sibling unchecking automatically.`,
      schema: {
        type: 'object',
        properties: {
          index: { type: 'number', description: 'Element index from browser_get_elements (preferred)' },
          selector: { type: 'string', description: 'CSS selector (fallback if index not available)' },
          value: { type: 'string', description: 'For <select>: option value or label to select' },
          label: { type: 'string', description: 'For <select>: option label text to select (alternative to value)' },
          checked: { type: 'boolean', description: 'For checkbox: true to check, false to uncheck (default: true). Ignored for radio (always checks).' },
        },
      },
      execute: async (params: unknown) => {
        const p = params as { index?: number; selector?: string; value?: string; label?: string; checked?: boolean };
        if (p.index === undefined && !p.selector) {
          return { success: false, error: 'Provide either index (from browser_get_elements) or selector.' };
        }
        const browser = await this.ensureBrowser();
        return browser.selectOption(p);
      },
    },
    {
      type: 'tool',
      name: 'browser_wait_for_selector',
      description: `Wait for a CSS selector to appear/disappear, or wait for a JS condition to become truthy.
Much more reliable than fixed-ms browser_wait for dynamic content (reveals, modals, AJAX).
Use after clicking "Reveal Code", dismissing overlays, or submitting forms.
state="visible" (default): wait for element to appear and be visible.
state="hidden": wait for element to disappear (useful after overlay dismiss).
state="attached": wait for element to exist in DOM (even if not visible).
expression: wait for arbitrary JS to return truthy (e.g., "document.querySelector('.code').innerText.length > 0").`,
      schema: {
        type: 'object',
        properties: {
          selector: { type: 'string', description: 'CSS selector to wait for' },
          state: {
            type: 'string',
            description: 'Wait condition: "visible" (default), "hidden", or "attached"',
            enum: ['visible', 'hidden', 'attached'],
          },
          expression: { type: 'string', description: 'JS expression to wait for (instead of selector). Returns truthy when condition is met.' },
          timeout: { type: 'number', description: 'Max wait time in ms (default: 5000, max: 15000)' },
        },
      },
      execute: async (params: unknown) => {
        const p = params as { selector?: string; state?: 'visible' | 'hidden' | 'attached'; expression?: string; timeout?: number };
        if (!p.selector && !p.expression) {
          return { success: false, error: 'Provide either selector or expression.' };
        }
        const browser = await this.ensureBrowser();
        return browser.waitForCondition(p);
      },
    },
    {
      type: 'tool',
      name: 'browser_inject',
      description: `Inject PERSISTENT JavaScript into the page (survives across tool calls).
Use for: setInterval watchers, MutationObservers, window-scoped helper functions, event listeners.
Unlike browser_eval (one-shot), injected scripts stay active on the page.
Provide an 'id' to manage scripts — re-injecting the same id replaces the previous script.
If your script returns a cleanup function, it will be called on replacement: return () => clearInterval(timerId).
HACK MODE: Use after conventional UI approaches have failed to solve the challenge.`,
      schema: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Unique script identifier (e.g., "code_scanner", "mutation_watcher"). Re-using an id replaces the previous injection.' },
          script: { type: 'string', description: 'JavaScript to inject. Runs immediately and persists (closures, intervals, observers stay active).' },
          maxLength: { type: 'number', description: 'Max characters of returned JSON string (default: 8000)' },
        },
        required: ['id', 'script'],
      },
      execute: async (params: unknown) => {
        const { id, script, maxLength } = params as { id: string; script: string; maxLength?: number };
        return this.injectPersistentScript(id, script, maxLength);
      },
    },
    {
      type: 'tool',
      name: 'browser_close',
      description: 'Close the browser completely.',
      schema: { type: 'object', properties: {} },
      execute: async () => this.close(),
    },
  ];

  async onLoad(agent: AgentContext): Promise<void> {
    this.agent = agent;

    // Read individual config keys (they're set directly in the config Map, not nested)
    const mode = agent.getConfig<BrowserConfig['mode']>('mode');
    const headless = agent.getConfig<boolean>('headless');
    const cdpPort = agent.getConfig<number>('cdpPort');
    const cdpWsEndpoint = agent.getConfig<string>('cdpWsEndpoint');
    const userDataDir = agent.getConfig<string>('userDataDir');
    const copyProfile = agent.getConfig<boolean>('copyProfile');
    const useSystemChrome = agent.getConfig<boolean>('useSystemChrome');
    const profileDirectory = agent.getConfig<string>('profileDirectory');
    const viewport = agent.getConfig<{ width: number; height: number }>('viewport');
    const openrouterKey = agent.getConfig<string>('openrouterKey');
    const visionModel = agent.getConfig<string>('visionModel');
    const visionMaxTokens = agent.getConfig<number>('visionMaxTokens');
    const visionRetryOnLength = agent.getConfig<boolean>('visionRetryOnLength');
    const visionRetryMaxTokens = agent.getConfig<number>('visionRetryMaxTokens');

    if (mode) this.config.mode = mode;
    if (headless !== undefined) this.config.headless = headless;
    if (cdpPort) this.config.cdpPort = cdpPort;
    if (cdpWsEndpoint) this.config.cdpWsEndpoint = cdpWsEndpoint;
    if (userDataDir) this.config.userDataDir = userDataDir;
    if (copyProfile !== undefined) this.config.copyProfile = copyProfile;
    if (useSystemChrome !== undefined) this.config.useSystemChrome = useSystemChrome;
    if (profileDirectory) this.config.profileDirectory = profileDirectory;
    if (viewport) this.config.viewport = viewport;
    if (openrouterKey) this.config.openrouterKey = openrouterKey;
    if (visionModel) this.config.visionModel = visionModel;
    if (visionMaxTokens !== undefined) this.config.visionMaxTokens = visionMaxTokens;
    if (visionRetryOnLength !== undefined) this.config.visionRetryOnLength = visionRetryOnLength;
    if (visionRetryMaxTokens !== undefined) this.config.visionRetryMaxTokens = visionRetryMaxTokens;

    agent.log.info(`Browser plugin v${this.version} loaded (Real Chrome support)`);

    switch (this.config.mode) {
      case 'chrome_profile':
        agent.log.info('Browser: will use your Chrome profile (cookies/sessions/extensions preserved)');
        break;
      case 'cdp':
        agent.log.info(`Browser: will connect to existing Chrome on port ${this.config.cdpPort || 9222}`);
        agent.log.info('  Start Chrome with: chrome --remote-debugging-port=9222');
        break;
      default:
        agent.log.info('Browser: will launch fresh Chrome instance (using system Chrome)');
    }
  }

  async onUnload(): Promise<void> {
    await this.close();
  }

  private async ensureBrowser(): Promise<AwareBrowserAgent> {
    if (!this.browser) {
      let cdpWsEndpoint: string | undefined;
      let cdpPort: number | undefined;
      let userDataDir: string | undefined;

      if (this.config.mode === 'cdp') {
        // CDP mode: Connect to existing Chrome with remote debugging enabled
        // Start Chrome with: chrome --remote-debugging-port=9222
        if (this.config.cdpWsEndpoint) {
          cdpWsEndpoint = this.config.cdpWsEndpoint;
        } else {
          cdpPort = this.config.cdpPort || 9222;
          // We'll let the browser-agent handle the connection and error
        }
      } else if (this.config.mode === 'chrome_profile') {
        userDataDir = this.config.userDataDir || getDefaultChromeUserDataDir(this.config.copyProfile ?? true);
        if (!userDataDir) {
          this.agent?.log.warn('Could not find Chrome profile, launching fresh instance');
        }
      }

      this.browser = new AwareBrowserAgent({
        headless: this.config.headless,
        cdpWsEndpoint,
        cdpPort,
        userDataDir,
        copyProfile: this.config.copyProfile,
        useSystemChrome: this.config.useSystemChrome ?? true,
        viewport: this.config.viewport,
      });

      await this.browser.initialize();
    }

    return this.browser;
  }

  private async navigate(url: string) {
    const browser = await this.ensureBrowser();
    
    let finalUrl = url;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      finalUrl = `https://${url}`;
    }

    const result = await browser.navigate(finalUrl);
    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      url: result.url,
      title: result.title,
      elements: elements,
      message: `Navigated to "${result.title}". Interactive elements listed above with [index] numbers.`,
    };
  }

  private async click(index: number) {
    const browser = await this.ensureBrowser();
    await browser.clickElementByIndex(index);
    await browser.waitForDomStable();

    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      message: `Clicked element [${index}]`,
      elements: elements,
    };
  }

  private async clickText(text: string, exact?: boolean, caseSensitive?: boolean, nth?: number) {
    const browser = await this.ensureBrowser();
    const hit = await browser.clickElementByText(text, { exact, caseSensitive, nth });
    await browser.waitForDomStable();

    const elements = await browser.getInteractiveElements();
    return {
      success: true,
      message: `Clicked element matching text "${text}"`,
      matchedText: hit.matchedText,
      matchedTag: hit.tag,
      elements,
    };
  }

  private async hoverElement(index: number, durationMs?: number) {
    const browser = await this.ensureBrowser();
    const holdMs = typeof durationMs === 'number' && Number.isFinite(durationMs)
      ? Math.max(0, Math.floor(durationMs))
      : 1200;

    const result = await browser.hoverElement(index, holdMs);
    await browser.waitForDomStable(1200, 120);

    const elements = await browser.getInteractiveElements();
    return {
      success: true,
      message: `Hovered element [${index}] for ${holdMs}ms`,
      hovered: result,
      elements,
    };
  }

  private async evalExpression(expression: string, maxLength?: number) {
    const browser = await this.ensureBrowser();
    const expr = String(expression ?? '');
    const max = typeof maxLength === 'number' && Number.isFinite(maxLength) ? Math.max(200, Math.floor(maxLength)) : 8000;

    const payload = await browser.evaluate<{ ok: boolean; json: string; error?: string }>(`
      (() => {
        try {
          const expr = ${JSON.stringify(expr)};
          // eslint-disable-next-line no-eval
          const value = eval(expr);
          let json = '';
          try {
            json = JSON.stringify(value);
          } catch {
            try {
              json = JSON.stringify(String(value));
            } catch {
              json = '"[unserializable]"';
            }
          }
          return { ok: true, json };
        } catch (e) {
          const msg = (e && (e.message || String(e))) ? (e.message || String(e)) : 'eval_failed';
          return { ok: false, json: 'null', error: msg };
        }
      })()
    `);

    const json = typeof payload?.json === 'string' ? payload.json : 'null';
    const out = json.length > max ? json.slice(0, max) + '...[truncated]' : json;

    return {
      success: Boolean(payload?.ok),
      expression: expr,
      resultJson: out,
      error: payload?.ok ? undefined : payload?.error,
    };
  }

  private static readonly INJECT_TIMEOUT_MS = 45000;

  private async injectPersistentScript(id: string, script: string, maxLength?: number) {
    const browser = await this.ensureBrowser();
    const scriptId = String(id ?? 'default');
    const code = String(script ?? '');
    const max = typeof maxLength === 'number' && Number.isFinite(maxLength) ? Math.max(200, Math.floor(maxLength)) : 8000;

    const evalPromise = browser.evaluate<{ ok: boolean; json: string; error?: string; replaced: boolean }>(`
      (() => {
        try {
          if (!window.__aware_injected) window.__aware_injected = {};
          window.__aware_bg_codes = Array.isArray(window.__aware_bg_codes) ? window.__aware_bg_codes : [];
          const id = ${JSON.stringify(scriptId)};
          const code = ${JSON.stringify(code)};
          const replaced = !!window.__aware_injected[id];
          if (replaced && typeof window.__aware_injected[id]?.cleanup === 'function') {
            try { window.__aware_injected[id].cleanup(); } catch {}
          }
          // eslint-disable-next-line no-eval
          const value = eval(code);
          window.__aware_injected[id] = { installedAt: Date.now(), cleanup: typeof value === 'function' ? value : null };
          let json = '';
          try { json = JSON.stringify(value); } catch { try { json = JSON.stringify(String(value)); } catch { json = '"[unserializable]"'; } }
          return { ok: true, json, replaced };
        } catch (e) {
          const msg = (e && (e.message || String(e))) ? (e.message || String(e)) : 'inject_failed';
          return { ok: false, json: 'null', error: msg, replaced: false };
        }
      })()
    `);

    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`browser_inject timed out after ${BrowserPlugin.INJECT_TIMEOUT_MS / 1000}s`)), BrowserPlugin.INJECT_TIMEOUT_MS)
    );
    const payload = await Promise.race([evalPromise, timeoutPromise]);

    const json = typeof payload?.json === 'string' ? payload.json : 'null';
    const out = json.length > max ? json.slice(0, max) + '...[truncated]' : json;

    return {
      success: Boolean(payload?.ok),
      scriptId,
      replaced: Boolean(payload?.replaced),
      resultJson: out,
      error: payload?.ok ? undefined : payload?.error,
    };
  }

  private async getConsoleLogs(limit?: number, clear?: boolean, types?: string[]) {
    const browser = await this.ensureBrowser();
    const entries = browser.getConsoleLogEntries({ limit, clear, types });
    return {
      success: true,
      count: entries.length,
      entries,
    };
  }

  private async getNetworkLogs(
    limit?: number,
    clear?: boolean,
    urlContains?: string,
    onlyErrors?: boolean,
    includeHeaders?: boolean,
    includeResponseBody?: boolean,
    maxBodyLength?: number
  ) {
    const browser = await this.ensureBrowser();
    const records = browser.getNetworkLogEntries({ limit, clear, urlContains, onlyErrors });

    const bodyMax =
      typeof maxBodyLength === 'number' && Number.isFinite(maxBodyLength) ? Math.max(200, Math.floor(maxBodyLength)) : 4000;

    const withBodies = includeResponseBody
      ? await Promise.all(
          records.map(async (r) => {
            const body = await browser.getNetworkResponseBody(r.id, bodyMax);
            return {
              ...r,
              responseBody: body.body,
              responseContentType: body.contentType,
              responseBodyError: body.error,
            };
          })
        )
      : records.map((r) => ({ ...r }));

    const normalized = withBodies.map((r) => {
      if (includeHeaders) return r;
      // Strip headers by default to avoid log bloat and accidental leakage.
      const { requestHeaders, responseHeaders, ...rest } = r as Record<string, unknown>;
      return rest;
    });

    return {
      success: true,
      count: normalized.length,
      records: normalized,
    };
  }

  private async getResponseBody(id: string, maxLength?: number) {
    const browser = await this.ensureBrowser();
    const clamp =
      typeof maxLength === 'number' && Number.isFinite(maxLength) ? Math.max(200, Math.floor(maxLength)) : 8000;
    const res = await browser.getNetworkResponseBody(id, clamp);
    return {
      success: !res.error,
      id,
      contentType: res.contentType,
      body: res.body,
      error: res.error,
    };
  }

  private async getStorage(scope?: 'local' | 'session' | 'all', includeValues?: boolean, maxValueLength?: number) {
    const browser = await this.ensureBrowser();
    const snap = await browser.getStorageSnapshot();
    const sc = scope || 'all';
    const include = Boolean(includeValues);
    const clamp =
      typeof maxValueLength === 'number' && Number.isFinite(maxValueLength) ? Math.max(20, Math.floor(maxValueLength)) : 200;

    const clampMap = (m: Record<string, string>): Record<string, string> => {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(m || {})) {
        const s = String(v ?? '');
        out[k] = s.length > clamp ? s.slice(0, clamp) + '...[truncated]' : s;
      }
      return out;
    };

    const local = snap.localStorage || {};
    const session = snap.sessionStorage || {};

    return {
      success: true,
      url: snap.url,
      scope: sc,
      ...(sc === 'local' || sc === 'all'
        ? include
          ? { localStorage: clampMap(local) }
          : { localStorageKeys: Object.keys(local) }
        : {}),
      ...(sc === 'session' || sc === 'all'
        ? include
          ? { sessionStorage: clampMap(session) }
          : { sessionStorageKeys: Object.keys(session) }
        : {}),
    };
  }

  private async getCookies(url?: string, includeValues?: boolean, maxValueLength?: number) {
    const browser = await this.ensureBrowser();
    const clamp =
      typeof maxValueLength === 'number' && Number.isFinite(maxValueLength) ? Math.max(20, Math.floor(maxValueLength)) : 120;
    const include = Boolean(includeValues);
    const cookies = await browser.getCookiesSnapshot(url);
    const out = cookies.map((c) => {
      const v = String(c.value ?? '');
      const value = include ? (v.length > clamp ? v.slice(0, clamp) + '...[truncated]' : v) : '[redacted]';
      return { ...c, value };
    });
    return {
      success: true,
      url: url || '(current)',
      count: out.length,
      cookies: out,
    };
  }

  private async domSearch(
    query: string,
    where?: 'text' | 'attributes' | 'all',
    includeHidden?: boolean,
    maxResults?: number,
    maxSnippetLength?: number,
    includeAllAttributes?: boolean
  ) {
    const browser = await this.ensureBrowser();
    const q = String(query ?? '').trim();
    const matches = await browser.domSearch(q, {
      in: where || 'all',
      includeHidden: includeHidden !== undefined ? Boolean(includeHidden) : true,
      maxResults,
      maxSnippetLength,
    });

    const needleLower = q.toLowerCase();
    const clampAttr = (s: string, n: number) => (s.length > n ? s.slice(0, n) + '...[truncated]' : s);

    const pickAttrs = (attrs: Record<string, string>): Record<string, string> => {
      const out: Record<string, string> = {};
      const maxLen = 200;
      const keys = Object.keys(attrs || {});
      for (const k of keys) {
        const v = String(attrs[k] ?? '');
        const kLower = k.toLowerCase();
        const isImportant =
          kLower === 'id' ||
          kLower === 'class' ||
          kLower === 'name' ||
          kLower === 'role' ||
          kLower === 'type' ||
          kLower === 'title' ||
          kLower === 'value' ||
          kLower === 'placeholder' ||
          kLower.startsWith('aria-') ||
          kLower.startsWith('data-') ||
          (needleLower && (kLower.includes(needleLower) || v.toLowerCase().includes(needleLower)));
        if (isImportant) {
          out[k] = clampAttr(v, maxLen);
        }
      }
      return out;
    };

    const normalized = matches.map((m) => ({
      ...m,
      attributes: includeAllAttributes
        ? Object.fromEntries(
            Object.entries(m.attributes || {}).map(([k, v]) => [k, clampAttr(String(v ?? ''), 200)])
          )
        : pickAttrs(m.attributes || {}),
    }));

    return {
      success: true,
      query: q,
      count: normalized.length,
      matches: normalized,
    };
  }

  /**
   * Ensure text param is a string. LLM/vision sometimes pass objects (e.g. {code: "ZGSJCP"})
   * which would become "[object Object]" when coerced — extract the actual code string.
   */
  private ensureTypedTextIsString(text: unknown): string {
    if (typeof text === 'string') return text;
    if (text && typeof text === 'object') {
      const o = text as Record<string, unknown>;
      if (typeof o.code === 'string') return o.code;
      if (typeof o.value === 'string') return o.value;
      if (typeof o.text === 'string') return o.text;
    }
    return String(text ?? '');
  }

  private async type(index: number, text: string, enter?: boolean) {
    const browser = await this.ensureBrowser();
    await browser.typeIntoElementByIndex(index, text);
    
    if (enter) {
      await browser.pressKey('Enter');
      await browser.waitForDomStable(2000);
    }

    return {
      success: true,
      message: `Typed "${text}" into element [${index}]${enter ? ' and pressed Enter' : ''}`,
    };
  }

  private async scroll(direction: 'up' | 'down', amount?: number) {
    const browser = await this.ensureBrowser();
    await browser.scroll(direction, amount || 500);

    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      message: `Scrolled ${direction}`,
      elements: elements,
    };
  }

  private async scrollContainer(direction: 'up' | 'down', amount?: number, container?: string) {
    const browser = await this.ensureBrowser();
    const result = await browser.scrollWithinContainer(direction, amount || 300, container);

    // Get updated elements after scroll
    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      scrolled: result.scrolled,
      container: result.container,
      scrollTop: result.scrollTop,
      message: result.scrolled
        ? `Scrolled ${direction} within "${result.container}" (scrollTop: ${result.scrollTop})`
        : `No scroll occurred in "${result.container}" - may have reached end`,
      elements: elements,
    };
  }

  private async extractContent() {
    const browser = await this.ensureBrowser();
    const content = await browser.extractContent();

    return {
      success: true,
      content: content,
      length: content.length,
    };
  }

  private async readSemantic() {
    const browser = await this.ensureBrowser();
    const content = await browser.extractSemanticContent();
    return {
      success: true,
      content,
      length: content.length,
    };
  }

  private async screenshot(highlight = false, forceVision = false) {
    const browser = await this.ensureBrowser();
    const result = await browser.takeScreenshot(highlight);

    const saved = await this.saveScreenshotToDisk(result.imageBase64, result.imageType, {
      url: result.url,
      title: result.title,
    }).catch((e) => {
      this.agent?.log?.warn?.(`Failed to save screenshot to disk: ${e instanceof Error ? e.message : String(e)}`);
      return null;
    });

    // Always gather deterministic context so the agent never gets stuck on vision
    const [content, elements] = await Promise.all([
      browser.extractContent().catch(() => ''),
      browser.getInteractiveElements().catch(() => ''),
    ]);

    // Include highlighted indices info if highlighting was enabled
    const highlightInfo = highlight && result.highlightedIndices
      ? `\n\n[Highlighted ${result.highlightedIndices.length} elements with index labels on screenshot. Red boxes/numbers show clickable element indices.]`
      : '';

    // Use vision model only when deterministic data is insufficient.
    // If both extract and getElements returned usable data, skip the expensive API call.
    // Threshold raised to 500 chars — simple pages (challenge steps, forms) easily exceed
    // this with headings + instructions; vision is only needed for truly blank/canvas pages.
    const hasContent = typeof content === 'string' && content.trim().length > 500;
    const elemStr = typeof elements === 'string' ? elements : String(elements ?? '');
    const hasElements = elemStr.trim().length > 50;
    // forceVision=true bypasses the sufficiency check (used after hover-reveal actions
    // where text doesn't change but visual content does)
    const needsVision = forceVision || !hasContent || !hasElements;

    if (this.config.openrouterKey && this.config.visionModel && needsVision) {
      try {
        this.agent.log.info(`📸 Analyzing screenshot with vision model: ${this.config.visionModel} (deterministic data insufficient)`);

        const analysis = await this.analyzeScreenshotWithVision(
          result.imageBase64,
          result.imageType,
          content.slice(0, 5000),
          elements
        );
        
        // Log the full vision analysis so user can see what agent "sees"
        this.agent.log.info(`👁️ Vision Analysis:\n${analysis}`);

        const parsedVision = this.parseVisionJson(analysis);
        if (!parsedVision) {
          this.agent.log.warn('⚠️ Vision output was not valid JSON (or could not be parsed). Using deterministic fallback vision from extract+elements.');
        }

        // Treat non-JSON or explicit failures as analysis failure (but still return content/elements)
        const trimmed = analysis.trim();
        const isAnalysisFailed =
          trimmed.startsWith('ANALYSIS_FAILED:') ||
          trimmed === 'Unable to analyze screenshot' ||
          (!trimmed.startsWith('{') && !trimmed.startsWith('[')); // we expect JSON output

        const fallbackVision = isAnalysisFailed && !parsedVision
          ? this.buildFallbackVision(content.slice(0, 5000), elements)
          : null;

        return {
          success: true,
          analysis,
          vision: (parsedVision ?? fallbackVision) ?? undefined,
          recommended_actions: (parsedVision?.recommended_actions ?? fallbackVision?.recommended_actions) ?? undefined,
          progress_signal_to_watch: (parsedVision?.progress_signal_to_watch ?? fallbackVision?.progress_signal_to_watch) ?? undefined,
          questions_for_human: (parsedVision?.questions_for_human ?? fallbackVision?.questions_for_human) ?? undefined,
          visionModel: this.config.visionModel,
          url: result.url,
          title: result.title,
          savedScreenshotPath: saved?.path ?? undefined,
          content: content.slice(0, 5000),
          contentLength: content.length,
          elements,
          highlightedElements: highlight ? result.highlightedIndices : undefined,
          note: (isAnalysisFailed
            ? 'Vision analysis unavailable/unstructured; included extracted page content + interactive elements for deterministic progress.'
            : 'Screenshot analyzed by vision model with structured output.') + highlightInfo,
        };
      } catch (error) {
        this.agent.log.warn(`Vision analysis failed: ${error}`);
        // Fall back to returning raw image
      }
    }

    // Return deterministic data (vision skipped or unavailable)
    const skipReason = !needsVision
      ? 'Vision skipped: deterministic data (extract + elements) sufficient.'
      : (!this.config.openrouterKey || !this.config.visionModel)
        ? 'No vision model configured - returning raw image.'
        : 'Vision analysis failed - returning raw image.';
    this.agent.log.info(`📸 ${skipReason}`);
    return {
      success: true,
      imageBase64: !needsVision ? undefined : result.imageBase64,
      imageType: !needsVision ? undefined : result.imageType,
      url: result.url,
      title: result.title,
      savedScreenshotPath: saved?.path ?? undefined,
      content: content.slice(0, 5000),
      contentLength: content.length,
      elements,
      highlightedElements: highlight ? result.highlightedIndices : undefined,
      note: skipReason + highlightInfo,
    };
  }

  private parseStepTag(text: string): string | null {
    const m = (text || '').match(/step\s+(\d+)\s+of\s+(\d+)/i);
    if (!m) return null;
    return `step${m[1]}of${m[2]}`;
  }

  private safeSlug(input: string, maxLen = 60): string {
    const s = (input || '')
      .toLowerCase()
      .replace(/https?:\/\//g, '')
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, maxLen);
    return s || 'page';
  }

  private async saveScreenshotToDisk(
    imageBase64: string,
    imageType: string,
    ctx: { url?: string; title?: string }
  ): Promise<{ path: string; bytes: number }> {
    const date = new Date();
    const day = date.toISOString().slice(0, 10);
    const ts = date.toISOString().replace(/[:.]/g, '-');
    const ext = imageType === 'image/png' ? 'png' : 'jpg';

    const urlHost = (() => {
      try {
        return ctx.url ? new URL(ctx.url).host : '';
      } catch {
        return '';
      }
    })();

    const stepTag = this.parseStepTag(ctx.title || '') || null;
    const hostSlug = this.safeSlug(urlHost || ctx.url || '');
    const titleSlug = this.safeSlug(ctx.title || '', 40);

    const dir = path.join(CONFIG_DIR, 'screenshots', day);
    await fs.mkdir(dir, { recursive: true });

    const filenameParts = [
      ts,
      stepTag,
      hostSlug || null,
      titleSlug || null,
    ].filter(Boolean) as string[];

    const filename = `${filenameParts.join('__')}.${ext}`;
    const filePath = path.join(dir, filename);

    const buf = Buffer.from(imageBase64, 'base64');
    await fs.writeFile(filePath, buf);
    return { path: filePath, bytes: buf.length };
  }

  private parseVisionJson(analysis: string): null | {
    scene_summary?: string;
    primary_goal_guess?: string;
    blockers?: string[];
    styling_broken?: boolean;
    visible_clues?: string[];
    recommended_actions?: Array<{ tool: string; args: Record<string, unknown>; why?: string }>;
    progress_signal_to_watch?: string;
    questions_for_human?: string[];
    scene?: string;
    progress_signal?: string;
  } {
    try {
      const trimmed = analysis.trim();
      let jsonText = trimmed;

      // Accept fenced JSON (common model behavior)
      const fenced = trimmed.match(/```json\s*([\s\S]*?)\s*```/i);
      if (fenced?.[1]) {
        jsonText = fenced[1].trim();
      }

      // If model prefixed text, try to extract the first JSON object.
      if (!jsonText.startsWith('{')) {
        const first = jsonText.indexOf('{');
        const last = jsonText.lastIndexOf('}');
        if (first >= 0 && last > first) {
          jsonText = jsonText.slice(first, last + 1).trim();
        }
      }
      if (!jsonText.startsWith('{')) return null;
      // Some models still emit JSON-with-comments (e.g., `// ...`) or trailing commas.
      // Sanitize those so we can parse robustly without changing the prompt too much.
      const cleaned = this.sanitizeJsonLike(jsonText);
      const parsed = JSON.parse(cleaned) as Record<string, unknown>;
      if (!parsed || typeof parsed !== 'object') return null;

      const recommendedRaw = Array.isArray(parsed.recommended_actions)
        ? (parsed.recommended_actions as Array<Record<string, unknown>>).map(a => ({
            tool: typeof a.tool === 'string' ? a.tool : '',
            args: (a.args && typeof a.args === 'object' ? (a.args as Record<string, unknown>) : {}),
            why: typeof a.why === 'string' ? a.why : undefined,
          })).filter(a => a.tool)
        : undefined;

      const recommended = recommendedRaw
        ? this.sanitizeRecommendedActions(recommendedRaw)
        : undefined;

      // Accept both old field names (scene_summary, progress_signal_to_watch) and new compact names (scene, progress_signal)
      const sceneVal = typeof parsed.scene === 'string' ? parsed.scene : undefined;
      const progressVal = typeof parsed.progress_signal === 'string' ? parsed.progress_signal : undefined;

      return {
        scene_summary: typeof parsed.scene_summary === 'string' ? parsed.scene_summary : sceneVal,
        primary_goal_guess: typeof parsed.primary_goal_guess === 'string' ? parsed.primary_goal_guess : undefined,
        blockers: Array.isArray(parsed.blockers) ? (parsed.blockers as unknown[]).map(String) : undefined,
        styling_broken: typeof parsed.styling_broken === 'boolean' ? parsed.styling_broken : undefined,
        visible_clues: Array.isArray(parsed.visible_clues) ? (parsed.visible_clues as unknown[]).map(String) : undefined,
        recommended_actions: recommended,
        progress_signal_to_watch: typeof parsed.progress_signal_to_watch === 'string' ? parsed.progress_signal_to_watch : progressVal,
        questions_for_human: Array.isArray(parsed.questions_for_human)
          ? (parsed.questions_for_human as unknown[]).map(String)
          : undefined,
        scene: sceneVal,
        progress_signal: progressVal,
      };
    } catch {
      return null;
    }
  }

  private sanitizeRecommendedActions(
    actions: Array<{ tool: string; args: Record<string, unknown>; why?: string }>
  ): Array<{ tool: string; args: Record<string, unknown>; why?: string }> {
    const allowed = new Set([
      'browser_click',
      'browser_click_text',
      'browser_scroll',
      'browser_type',
      'browser_hover_element',
      'browser_hover',
      'browser_drag_drop',
      'browser_drag_solve',
      'browser_drag_brute_force',
      'browser_click_batch',
      'browser_pointer_path',
      'browser_get_element_box',
      'browser_extract',
      'browser_get_elements',
      'browser_get_meta',
      'browser_inspect_element',
      'browser_screenshot',
    ]);

    const out: Array<{ tool: string; args: Record<string, unknown>; why?: string }> = [];

    for (const a of actions) {
      if (!a?.tool || !allowed.has(a.tool)) continue;
      const args = a.args && typeof a.args === 'object' ? a.args : {};

      // Convert selector-ish suggestions into browser_click_text when possible
      if (a.tool === 'browser_click' && typeof (args as any).selector === 'string') {
        const sel = String((args as any).selector);
        const m = sel.match(/has-text\\(\\s*['"]([^'"]+)['"]\\s*\\)/i);
        if (m?.[1]) {
          out.push({
            tool: 'browser_click_text',
            args: { text: m[1], exact: true },
            why: a.why,
          });
        }
        continue;
      }

      // Validate required arg shapes
      if (a.tool === 'browser_click') {
        const idx = (args as any).index;
        if (typeof idx !== 'number' || !Number.isFinite(idx)) continue;
        out.push({ tool: 'browser_click', args: { index: idx }, why: a.why });
        continue;
      }
      if (a.tool === 'browser_click_text') {
        const text = (args as any).text;
        if (typeof text !== 'string' || !text.trim()) continue;
        const exact = typeof (args as any).exact === 'boolean' ? (args as any).exact : undefined;
        const nth = typeof (args as any).nth === 'number' && Number.isFinite((args as any).nth) ? Math.max(0, Math.floor((args as any).nth)) : undefined;
        out.push({ tool: 'browser_click_text', args: { text: text.trim(), ...(exact !== undefined ? { exact } : {}), ...(nth !== undefined ? { nth } : {}) }, why: a.why });
        continue;
      }
      if (a.tool === 'browser_scroll') {
        const direction = (args as any).direction;
        if (direction !== 'up' && direction !== 'down') continue;
        const amount = (args as any).amount;
        const outArgs: Record<string, unknown> = { direction };
        if (typeof amount === 'number' && Number.isFinite(amount)) outArgs.amount = amount;
        out.push({ tool: 'browser_scroll', args: outArgs, why: a.why });
        continue;
      }
      if (a.tool === 'browser_type') {
        const idx = (args as any).index;
        const text = (args as any).text;
        const enter = (args as any).enter;
        if (typeof idx !== 'number' || !Number.isFinite(idx)) continue;
        if (typeof text !== 'string') continue;
        out.push({ tool: 'browser_type', args: { index: idx, text, ...(typeof enter === 'boolean' ? { enter } : {}) }, why: a.why });
        continue;
      }
      if (a.tool === 'browser_inspect_element' || a.tool === 'browser_get_element_box') {
        const idx = (args as any).index;
        if (typeof idx !== 'number' || !Number.isFinite(idx)) continue;
        out.push({ tool: a.tool, args: { index: idx }, why: a.why });
        continue;
      }
      if (a.tool === 'browser_hover_element') {
        const idx = (args as any).index;
        if (typeof idx !== 'number' || !Number.isFinite(idx)) continue;
        const outArgs: Record<string, unknown> = { index: idx };
        if (typeof (args as any).durationMs === 'number') outArgs.durationMs = (args as any).durationMs;
        out.push({ tool: 'browser_hover_element', args: outArgs, why: a.why });
        continue;
      }
      if (a.tool === 'browser_hover') {
        const x = (args as any).x; const y = (args as any).y;
        if (typeof x !== 'number' || typeof y !== 'number') continue;
        const outArgs: Record<string, unknown> = { x, y };
        if (typeof (args as any).durationMs === 'number') outArgs.durationMs = (args as any).durationMs;
        out.push({ tool: 'browser_hover', args: outArgs, why: a.why });
        continue;
      }
      if (a.tool === 'browser_drag_drop') {
        // Index-based or coordinate-based
        if (typeof (args as any).fromIndex === 'number' && typeof (args as any).toIndex === 'number') {
          const outArgs: Record<string, unknown> = { fromIndex: (args as any).fromIndex, toIndex: (args as any).toIndex };
          if (typeof (args as any).steps === 'number') outArgs.steps = (args as any).steps;
          out.push({ tool: 'browser_drag_drop', args: outArgs, why: a.why });
        } else if (typeof (args as any).fromX === 'number' && typeof (args as any).toX === 'number') {
          const outArgs: Record<string, unknown> = { fromX: (args as any).fromX, fromY: (args as any).fromY, toX: (args as any).toX, toY: (args as any).toY };
          if (typeof (args as any).steps === 'number') outArgs.steps = (args as any).steps;
          out.push({ tool: 'browser_drag_drop', args: outArgs, why: a.why });
        }
        continue;
      }
      if (a.tool === 'browser_drag_solve') {
        const outArgs: Record<string, unknown> = {};
        if (typeof (args as any).slotSelector === 'string') outArgs.slotSelector = (args as any).slotSelector;
        if (typeof (args as any).strategy === 'string') outArgs.strategy = (args as any).strategy;
        out.push({ tool: 'browser_drag_solve', args: outArgs, why: a.why });
        continue;
      }
      if (a.tool === 'browser_drag_brute_force') {
        out.push({ tool: 'browser_drag_brute_force', args: {}, why: a.why });
        continue;
      }
      if (a.tool === 'browser_click_batch') {
        const outArgs: Record<string, unknown> = {};
        if (Array.isArray((args as any).texts)) outArgs.texts = (args as any).texts;
        if (Array.isArray((args as any).indices)) outArgs.indices = (args as any).indices;
        if (typeof (args as any).exact === 'boolean') outArgs.exact = (args as any).exact;
        if (!outArgs.texts && !outArgs.indices) continue;
        out.push({ tool: 'browser_click_batch', args: outArgs, why: a.why });
        continue;
      }
      if (a.tool === 'browser_pointer_path') {
        if (!Array.isArray((args as any).points)) continue;
        const outArgs: Record<string, unknown> = { points: (args as any).points };
        if (typeof (args as any).elementIndex === 'number') outArgs.elementIndex = (args as any).elementIndex;
        if (typeof (args as any).relative === 'boolean') outArgs.relative = (args as any).relative;
        if (typeof (args as any).durationMs === 'number') outArgs.durationMs = (args as any).durationMs;
        out.push({ tool: 'browser_pointer_path', args: outArgs, why: a.why });
        continue;
      }

      // Tools with empty args
      if (
        a.tool === 'browser_extract' ||
        a.tool === 'browser_get_elements' ||
        a.tool === 'browser_get_meta' ||
        a.tool === 'browser_screenshot'
      ) {
        out.push({ tool: a.tool, args: {}, why: a.why });
      }
    }

    return out;
  }

  private sanitizeJsonLike(input: string): string {
    const s = input ?? '';
    let out = '';
    let inString = false;
    let escaped = false;

    for (let i = 0; i < s.length; i++) {
      const c = s[i]!;
      const n = s[i + 1];

      if (inString) {
        out += c;
        if (escaped) {
          escaped = false;
        } else if (c === '\\\\') {
          escaped = true;
        } else if (c === '"') {
          inString = false;
        }
        continue;
      }

      if (c === '"') {
        inString = true;
        out += c;
        continue;
      }

      // Line comment: // ...
      if (c === '/' && n === '/') {
        // Skip until newline (or end)
        while (i < s.length && s[i] !== '\n') i++;
        out += '\n';
        continue;
      }

      // Block comment: /* ... */
      if (c === '/' && n === '*') {
        i += 2;
        while (i < s.length && !(s[i] === '*' && s[i + 1] === '/')) i++;
        i++; // skip trailing '/'
        continue;
      }

      out += c;
    }

    // Remove trailing commas before } or ]
    out = out.replace(/,\s*([}\]])/g, '$1');
    return out.trim();
  }

  private buildFallbackVision(
    pageText: string,
    elementsRaw: unknown
  ): {
    scene_summary: string;
    primary_goal_guess: string;
    blockers: string[];
    styling_broken: boolean;
    visible_clues: string[];
    recommended_actions: Array<{ tool: string; args: Record<string, unknown>; why?: string }>;
    progress_signal_to_watch: string;
    questions_for_human: string[];
  } {
    const text = (pageText || '').toString();

    const elementsText = typeof elementsRaw === 'string'
      ? elementsRaw
      : Array.isArray(elementsRaw)
        ? elementsRaw.map(String).join('\n')
        : JSON.stringify(elementsRaw ?? '');

    const lines = elementsText.split('\n');
    const parsed = lines
      .map((line) => {
        const m = line.match(/^\[(\d+)\]\s+(.*)$/);
        if (!m) return null;
        return { index: Number(m[1]), line: m[2] };
      })
      .filter(Boolean) as Array<{ index: number; line: string }>;

    const findIndex = (needle: RegExp): number | null => {
      const hit = parsed.find(p => needle.test(p.line));
      return hit ? hit.index : null;
    };

    const findIndexPrefer = (needle: RegExp, avoid?: RegExp): number | null => {
      const hit = parsed.find(p => needle.test(p.line) && !(avoid?.test(p.line) ?? false));
      if (hit) return hit.index;
      return findIndex(needle);
    };

    const blockers: string[] = [];
    if (/cookie consent/i.test(text)) blockers.push('cookie_consent');
    if (/\bwarning!\b/i.test(text) || /popup message/i.test(text)) blockers.push('popup_warning');
    if (/important alert/i.test(text)) blockers.push('important_alert');
    if (/please select an option/i.test(text) || /scrollable modal/i.test(text)) blockers.push('scrollable_modal');

    const recommended_actions: Array<{ tool: string; args: Record<string, unknown>; why?: string }> = [];

    // If this looks like a hidden DOM/code step, push deterministic inspection tools.
    if (/hidden dom/i.test(text) || (/hint:/i.test(text) && /attributes|aria|meta/i.test(text))) {
      recommended_actions.push({
        tool: 'browser_get_meta',
        args: {},
        why: 'Check meta tags for hidden code hints (name/property/content).',
      });
      recommended_actions.push({
        tool: 'browser_get_elements',
        args: {},
        why: 'Refresh interactive element indices before inspecting candidates for hidden attributes.',
      });
    }

    // Popups/modals often block progress but their text may not appear in extracted page text.
    // Infer blockers from button labels and prioritize "Dismiss"/"Accept"/real "Close" controls.
    const dismissIdx = findIndex(/\bdismiss\b/i);
    if (dismissIdx !== null) {
      recommended_actions.push({
        tool: 'browser_click',
        args: { index: dismissIdx },
        why: 'Dismiss a blocking modal/overlay to unblock the page.',
      });
    }

    const acceptIdx = findIndex(/\baccept\b/i);
    if (acceptIdx !== null) {
      recommended_actions.push({
        tool: 'browser_click',
        args: { index: acceptIdx },
        why: 'Accept cookie consent to remove overlay and unblock clicks.',
      });
    }

    const closeIdx = findIndexPrefer(/\bclose\b/i, /\bfake\b/i);
    if (closeIdx !== null) {
      recommended_actions.push({
        tool: 'browser_click',
        args: { index: closeIdx },
        why: 'Close a blocking popup/modal (prefer a real Close over “Close (Fake)”).',
      });
    }

    // If page mentions "enter code", highlight likely next steps even without knowing the code yet.
    const codeInputIdx = findIndex(/<input\b[^>]*placeholder="[^"]*code/i);
    const submitCodeIdx = findIndex(/submit code/i);
    if (codeInputIdx !== null && submitCodeIdx !== null) {
      recommended_actions.push({
        tool: 'browser_extract',
        args: {},
        why: 'Re-extract after closing overlays to find the revealed code in text (or instructions to reveal it).',
      });
    }

    // Scrollable modal with radio options: scroll within the modal first to see all choices.
    if (blockers.includes('scrollable_modal') && /radio|option|choice/i.test(text)) {
      recommended_actions.push({
        tool: 'browser_scroll_container',
        args: { direction: 'down' },
        why: 'Scroll within the modal to reveal all radio options before selecting one.',
      });
    }

    return {
      scene_summary: 'Vision failed; using extracted page text + element list for guidance.',
      primary_goal_guess: 'Clear blockers/popups, reveal the step code, enter it, and proceed to the next step.',
      blockers,
      styling_broken: false,
      visible_clues: [
        ...( /close button.*fake/i.test(text) ? ['Some close buttons are fake; try an alternate close/dismiss control.'] : [] ),
      ],
      recommended_actions,
      progress_signal_to_watch: 'Blockers disappear and the page shows the revealed code or advances to the next step (e.g., "Step 5 of 30").',
      questions_for_human: [],
    };
  }

  /**
   * Analyze a screenshot using the configured vision model via OpenRouter
   */
  private async analyzeScreenshotWithVision(
    imageBase64: string,
    imageType: string,
    pageText: string,
    elements: unknown
  ): Promise<string> {
    const elementsText =
      typeof elements === 'string'
        ? elements
        : JSON.stringify(elements).slice(0, 5000);

    const basePrompt = (textInput: string, elemsInput: string) => `You recommend next actions for a web automation agent.

TEXT: ${textInput || '[none]'}
ELEMENTS: ${elemsInput}

Rules:
1. OBVIOUS FIRST: visible code + input field → type it immediately. Only clear blockers if typing fails.
2. Follow page instructions before exploring ("click here N times", "scroll to see options").
3. Be deterministic: reference element indices. Never guess codes/passwords.
4. Max 4 actions. End with browser_extract to verify.

Tools (use ONLY these):
browser_click {index} | browser_click_text {text, exact?, nth?} | browser_type {index, text, enter?}
browser_scroll {direction:"up"|"down", amount?} | browser_hover_element {index} | browser_hover {x, y}
browser_drag_drop {fromIndex, toIndex} or {fromX, fromY, toX, toY} | browser_drag_solve {strategy?} | browser_drag_brute_force {}
browser_click_batch {texts?, indices?} | browser_pointer_path {points:[{x,y},...], elementIndex?, relative?}
browser_get_element_box {index} | browser_extract {} | browser_get_elements {} | browser_get_meta {}
browser_inspect_element {index} | browser_screenshot {}

No selectors. No comments/links. Put "why" next to action, not in args.

Return ONE JSON (no markdown, no extra text):
{
  "scene": "what you see + what agent is trying to do (1-2 sentences)",
  "blockers": ["modal/overlay/..."],
  "visible_clues": ["codes/text that matter"],
  "recommended_actions": [{"tool": "...", "args": {...}, "why": "..."}],
  "progress_signal": "what change proves success"
}

If cannot analyze: ANALYSIS_FAILED: <reason>`;

    const prompt = basePrompt(pageText, elementsText);
    const retryPrompt = basePrompt(
      // shrink for retry to reduce both context + output needs
      (pageText || '').slice(0, 2500),
      (elementsText || '').slice(0, 2500)
    ) + `\n\nRETRY RULES:\n- Your previous response was truncated.\n- Return ONLY the JSON object.\n- Keep JSON concise (<= 250 tokens).\n- <= 4 actions.\n`;

    const clampInt = (n: unknown, min: number, max: number, fallback: number): number => {
      const v = typeof n === 'number' ? n : Number(n);
      if (!Number.isFinite(v)) return fallback;
      return Math.max(min, Math.min(max, Math.floor(v)));
    };

    // Allow very large outputs for long-context models (e.g., 262k token models).
    const maxTokens = clampInt(this.config.visionMaxTokens, 256, 262000, 1024);
    const retryMaxTokens = clampInt(this.config.visionRetryMaxTokens, 256, 262000, 4096);
    const shouldRetryOnLength = this.config.visionRetryOnLength !== false;

    // Log the prompt being sent for full transparency
    this.agent.log.info(`📤 Vision prompt:\n${prompt}`);
    this.agent.log.info(
      `📤 Sending to: ${this.config.visionModel} (image size: ${Math.round(imageBase64.length / 1024)}KB, max_tokens=${maxTokens})`
    );

    const VISION_TIMEOUT_MS = 90_000;
    const VISION_MAX_RETRIES = 3;
    const VISION_BASE_DELAY_MS = 1_500;

    const callOnce = async (promptText: string, maxTokensThisCall: number): Promise<{
      analysisText: string;
      finishReason: string;
      rawPreview: string;
    }> => {
      let lastError: Error | null = null;

      for (let attempt = 0; attempt < VISION_MAX_RETRIES; attempt++) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), VISION_TIMEOUT_MS);

        try {
          const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${this.config.openrouterKey}`,
            },
            body: JSON.stringify({
              model: this.config.visionModel,
              messages: [
                {
                  role: 'user',
                  content: [
                    { type: 'text', text: promptText },
                    {
                      type: 'image_url',
                      image_url: {
                        url: `data:${imageType};base64,${imageBase64}`,
                      },
                    },
                  ],
                },
              ],
              max_tokens: maxTokensThisCall,
            }),
            signal: controller.signal,
          });

          clearTimeout(timeoutId);

          if (!response.ok) {
            const errorText = await response.text();
            const status = response.status;
            const isRetryable = status === 429 || status >= 500;

            if (isRetryable && attempt < VISION_MAX_RETRIES - 1) {
              const delay = VISION_BASE_DELAY_MS * Math.pow(2, attempt);
              this.agent.log.warn(`⚠️ Vision API ${status}, retrying in ${delay}ms (attempt ${attempt + 1}/${VISION_MAX_RETRIES})`);
              await new Promise(r => setTimeout(r, delay));
              continue;
            }

            this.agent.log.error(`❌ Vision API error: ${response.statusText} - ${errorText}`);
            throw new Error(`Vision API failed: ${response.statusText} - ${errorText}`);
          }

          const data = await response.json() as {
            choices?: Array<{ message?: { content?: unknown; reasoning?: unknown }; finish_reason?: string }>;
            error?: unknown;
          };

          const rawContent = data.choices?.[0]?.message?.content;
          let analysisText = '';
          if (typeof rawContent === 'string') {
            analysisText = rawContent;
          } else if (Array.isArray(rawContent)) {
            analysisText = rawContent
              .map((p) => {
                if (typeof p === 'string') return p;
                if (p && typeof p === 'object' && 'text' in (p as Record<string, unknown>)) {
                  const t = (p as Record<string, unknown>).text;
                  return typeof t === 'string' ? t : '';
                }
                return '';
              })
              .join('');
          }

          // Some providers return useful text in a separate "reasoning" field.
          if (!analysisText.trim()) {
            const rawReasoning = data.choices?.[0]?.message?.reasoning;
            if (typeof rawReasoning === 'string' && rawReasoning.trim()) {
              analysisText = rawReasoning;
            }
          }

          const finishReason = String(data.choices?.[0]?.finish_reason ?? '');
          const rawPreview = (() => {
            try {
              return JSON.stringify(data).slice(0, 2000);
            } catch {
              return '[unserializable vision response]';
            }
          })();

          if (!analysisText.trim()) {
            this.agent.log.warn(`⚠️ Vision response missing/empty content. finish_reason=${finishReason} preview=${rawPreview}`);
            analysisText = 'ANALYSIS_FAILED: empty_or_missing_content';
          }

          return { analysisText, finishReason, rawPreview };
        } catch (err) {
          clearTimeout(timeoutId);
          lastError = err instanceof Error ? err : new Error(String(err));

          if (lastError.name === 'AbortError') {
            lastError = new Error(`Vision API timed out after ${VISION_TIMEOUT_MS}ms`);
          }

          const isRetryable = lastError.message.includes('timed out') ||
            lastError.message.includes('network') ||
            lastError.message.includes('ECONNRESET') ||
            lastError.message.includes('fetch failed');

          if (isRetryable && attempt < VISION_MAX_RETRIES - 1) {
            const delay = VISION_BASE_DELAY_MS * Math.pow(2, attempt);
            this.agent.log.warn(`⚠️ Vision ${lastError.message}, retrying in ${delay}ms (attempt ${attempt + 1}/${VISION_MAX_RETRIES})`);
            await new Promise(r => setTimeout(r, delay));
            continue;
          }

          throw lastError;
        }
      }

      throw lastError || new Error(`Vision API failed after ${VISION_MAX_RETRIES} retries`);
    };

    const first = await callOnce(prompt, maxTokens);

    // If provider truncated, retry with a stricter, smaller output request to get usable JSON.
    if (shouldRetryOnLength && first.finishReason.toLowerCase() === 'length') {
      this.agent.log.warn(
        `⚠️ Vision output truncated (finish_reason=length). Retrying with strict concise JSON (max_tokens=${retryMaxTokens}).`
      );
      const second = await callOnce(retryPrompt, retryMaxTokens);
      const chosen = second.analysisText.trim() ? second.analysisText : first.analysisText;
      this.agent.log.info(`📥 Vision response received (${chosen.length} chars)`);
      return chosen;
    }

    this.agent.log.info(`📥 Vision response received (${first.analysisText.length} chars)`);
    return first.analysisText;
  }

  private async wait(ms: number) {
    const browser = await this.ensureBrowser();
    await browser.wait(ms);

    return {
      success: true,
      message: `Waited ${ms}ms`,
    };
  }

  private async goBack() {
    const browser = await this.ensureBrowser();
    await browser.goBack();
    
    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      message: 'Navigated back',
      elements: elements,
    };
  }

  private async getElements(showAll?: boolean, compact?: boolean) {
    const browser = await this.ensureBrowser();
    const elements = await browser.getInteractiveElements({ showAll, compact });

    return {
      success: true,
      elements: elements,
    };
  }

  private async getPageHtml(params: unknown) {
    const args = (params as { maxLength?: number }) || {};
    const browser = await this.ensureBrowser();
    let html = await browser.getHtml();

    const maxLength = args.maxLength || 50000;
    if (html.length > maxLength) {
      html = html.slice(0, maxLength) + '\n...[truncated]';
    }

    return {
      success: true,
      html,
      length: html.length,
    };
  }

  private async getElementHtml(params: unknown) {
    const args = params as { index: number };
    const browser = await this.ensureBrowser();

    // Use browser.evaluate to get element HTML by index
    const html = await browser.evaluate<string | null>(`
      (function() {
        var idx = ${args.index};
        // 1. Stable lookup via data-aware-idx (stamped by getInteractiveElements)
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');
        // 2. Fallback to positional index
        if (!el) {
          var interactiveSelectors = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
          var elements = document.querySelectorAll(interactiveSelectors);
          el = elements[idx] || null;
        }
        return el ? el.outerHTML : null;
      })()
    `);

    return {
      success: true,
      html: html || 'Element not found',
      index: args.index,
    };
  }

  private async inspectElement(index: number) {
    const browser = await this.ensureBrowser();
    const element = await browser.inspectElementByIndex(index);
    return {
      success: true,
      element,
    };
  }

  private async getMeta() {
    const browser = await this.ensureBrowser();
    const meta = await browser.getMetaTags();
    return {
      success: true,
      meta,
      count: meta.length,
    };
  }

  private async readScripts(patterns?: string[], maxLength?: number, includeInline?: boolean) {
    const browser = await this.ensureBrowser();
    const result = await browser.readScripts(patterns, maxLength ?? 15000, includeInline ?? true);
    return {
      success: true,
      ...result,
    };
  }

  private async deepInspect() {
    const browser = await this.ensureBrowser();
    const result = await browser.deepInspect();
    return {
      success: true,
      ...result,
    };
  }

  private async extractHiddenCode(elementIndex?: number, scanAll: boolean = true) {
    const browser = await this.ensureBrowser();

    const expression = `
      (function() {
        var codes = [];
        var codePattern = /[A-Z][A-Z0-9]{5,9}/g;
        
        function addCode(code, source) {
          var normalized = (code || '').toUpperCase().trim();
          if (normalized.length >= 6 && normalized.length <= 10 && /^[A-Z0-9]+$/.test(normalized)) {
            if (!codes.some(c => c.code === normalized)) {
              codes.push({ code: normalized, source: source });
            }
          }
        }
        
        var targets = [];
        if (${elementIndex !== undefined ? 'true' : 'false'}) {
          var el = document.querySelector('[data-aware-idx="' + ${elementIndex ?? -1} + '"]');
          if (el) targets.push(el);
          else {
            var allInteractive = document.querySelectorAll('a, button, input, select, textarea, [onclick], [tabindex], .cursor-pointer');
            if (${elementIndex ?? -1} >= 0 && ${elementIndex ?? -1} < allInteractive.length) {
              targets.push(allInteractive[${elementIndex ?? 0}]);
            }
          }
        } else if (${scanAll ? 'true' : 'false'}) {
          targets = Array.from(document.querySelectorAll('*'));
        }
        
        for (var i = 0; i < targets.length; i++) {
          var el = targets[i];
          if (!el || !el.attributes) continue;
          
          for (var j = 0; j < el.attributes.length; j++) {
            var attr = el.attributes[j];
            var name = (attr.name || '').toLowerCase();
            if (name.startsWith('data-') || name.includes('code') || name.includes('answer') || name.includes('secret')) {
              var matches = (attr.value || '').match(codePattern);
              if (matches) {
                for (var m = 0; m < matches.length; m++) {
                  addCode(matches[m], name + '="' + (attr.value || '').slice(0, 50) + '"');
                }
              }
            }
          }
          
          var aria = el.getAttribute('aria-label') || el.getAttribute('aria-describedby');
          if (aria) {
            var ariaMatches = aria.match(codePattern);
            if (ariaMatches) {
              for (var am = 0; am < ariaMatches.length; am++) {
                addCode(ariaMatches[am], 'aria-label="' + aria.slice(0, 50) + '"');
              }
            }
          }
          
          var text = (el.innerText || el.textContent || '').trim();
          var textMatches = text.match(codePattern);
          if (textMatches) {
            for (var tm = 0; tm < textMatches.length; tm++) {
              addCode(textMatches[tm], 'text content');
            }
          }
        }
        
        var bodyText = document.body.innerText || '';
        var lines = bodyText.split('\\n');
        for (var l = 0; l < lines.length; l++) {
          var line = lines[l];
          if (/code|answer|secret|reveal/i.test(line)) {
            var lineMatches = line.match(codePattern);
            if (lineMatches) {
              for (var lm = 0; lm < lineMatches.length; lm++) {
                addCode(lineMatches[lm], 'page text: "' + line.slice(0, 80) + '"');
              }
            }
          }
        }
        
        return {
          success: true,
          codes: codes,
          count: codes.length,
          summary: codes.length > 0 
            ? 'Found ' + codes.length + ' candidate code(s): ' + codes.map(c => c.code).join(', ')
            : 'No codes found. Try clicking the hidden DOM element more times or using browser_deep_inspect for comprehensive scan.'
        };
      })()
    `;

    const result = await browser.evaluate(expression);
    return result as { success: boolean; codes: Array<{ code: string; source: string }>; count: number; summary: string };
  }

  private async fullAudit(patterns?: string[]) {
    // Run all inspections in parallel — single LLM turn instead of 5+
    const [domResult, scriptsResult, storageResult, metaResult, cookiesResult] = await Promise.allSettled([
      this.deepInspect(),
      this.readScripts(patterns, 10000, true),
      this.getStorage('all', true, 200),
      this.getMeta(),
      this.getCookies(undefined, true, 120),
    ]);

    const unwrap = <T>(r: PromiseSettledResult<T>, label: string): T | { error: string } =>
      r.status === 'fulfilled' ? r.value : { error: `${label} failed: ${(r as PromiseRejectedResult).reason}` };

    const dom = unwrap(domResult, 'deep_inspect') as any;
    const scripts = unwrap(scriptsResult, 'read_scripts') as any;
    const storage = unwrap(storageResult, 'storage') as any;
    const meta = unwrap(metaResult, 'meta') as any;
    const cookies = unwrap(cookiesResult, 'cookies') as any;

    // Build concise summary
    const findings: string[] = [];
    if (dom && !dom.error) {
      if (dom.isClean) {
        findings.push('DOM: CLEAN — no hidden data-*, aria-*, comments, or hidden elements');
      } else {
        const domParts: string[] = [];
        const hiddenCount = (dom.hiddenData?.length || 0) + (dom.comments?.length || 0);
        if (hiddenCount > 0) domParts.push(`${hiddenCount} hidden items`);
        if (dom.clickableNonInteractive?.length > 0) {
          const texts = dom.clickableNonInteractive.map((c: any) => `"${c.text?.slice(0, 40)}"`).join(', ');
          domParts.push(`clickable divs: ${texts} — use browser_click_text`);
        }
        if (dom.scrollableContainers?.length > 0) {
          domParts.push(`${dom.scrollableContainers.length} scrollable containers (use browser_scroll_container)`);
        }
        if (dom.overlays?.length > 0) {
          domParts.push(`${dom.overlays.length} overlays (dismiss highest z-index first)`);
        }
        if (dom.disabledButtons?.length > 0) {
          domParts.push(`${dom.disabledButtons.length} disabled/fake buttons (avoid)`);
        }
        findings.push(`DOM: ${domParts.join('; ')}`);
      }
    }
    if (scripts && !scripts.error) {
      // scripts.scripts is an array; each entry may have a .matches array
      const scriptEntries = scripts.scripts || [];
      const matchCount = scriptEntries.reduce((n: number, s: any) => n + (s.matches?.length || 0), 0);
      if (matchCount > 0) {
        findings.push(`JS: Found ${matchCount} pattern matches in scripts`);
      } else {
        findings.push('JS: No validation/answer patterns found in scripts');
      }
    }
    if (storage && !storage.error) {
      const keys = [
        ...Object.keys(storage.localStorage || {}),
        ...Object.keys(storage.sessionStorage || {}),
      ];
      findings.push(keys.length > 0 ? `Storage: ${keys.join(', ')}` : 'Storage: empty');
    }

    return {
      success: true,
      summary: findings.join(' | '),
      dom,
      scripts,
      storage,
      meta,
      cookies,
    };
  }

  // ==================== TAB MANAGEMENT ====================

  private async newTab(url?: string) {
    const browser = await this.ensureBrowser();
    const result = await browser.newTab(url);
    
    let elements = '';
    if (url) {
      elements = await browser.getInteractiveElements();
    }

    return {
      success: true,
      tabIndex: result.tabIndex,
      url: result.url,
      title: result.title,
      elements: elements,
      message: url 
        ? `Opened new tab [${result.tabIndex}] and navigated to "${result.title}"`
        : `Opened new empty tab [${result.tabIndex}]`,
    };
  }

  private async listTabs() {
    const browser = await this.ensureBrowser();
    const tabs = await browser.listTabs();

    const tabList = tabs.map(t => 
      `[${t.index}]${t.active ? '*' : ''}: ${t.title} (${t.url})`
    ).join('\n');

    return {
      success: true,
      tabs: tabs,
      summary: tabList,
      activeTab: tabs.find(t => t.active)?.index ?? 0,
    };
  }

  private async switchTab(index: number) {
    const browser = await this.ensureBrowser();
    const result = await browser.switchTab(index);
    const elements = await browser.getInteractiveElements();

    return {
      success: true,
      url: result.url,
      title: result.title,
      elements: elements,
      message: `Switched to tab [${index}]: "${result.title}"`,
    };
  }

  private async closeTab(index?: number) {
    const browser = await this.ensureBrowser();
    const result = await browser.closeTab(index);

    return {
      success: true,
      remainingTabs: result.remainingTabs,
      message: index !== undefined 
        ? `Closed tab [${index}]. ${result.remainingTabs} tabs remaining.`
        : `Closed current tab. ${result.remainingTabs} tabs remaining.`,
    };
  }

  private async close() {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }

    return { success: true };
  }
}

export { AwareBrowserAgent, getCdpWsEndpoint, getDefaultChromeUserDataDir };
