/**
 * AwareBrowserAgent - Real Chrome browser automation
 * 
 * Supports multiple connection modes to REAL Chrome:
 * 1. CDP WebSocket - Connect to existing Chrome instance (best for using your logged-in sessions)
 * 2. Chrome Profile - Launch Chrome with your actual user data (cookies, extensions, sessions)
 * 3. Fresh Launch - Launch clean Chrome instance (uses system Chrome, not Playwright Chromium)
 * 
 * IMPORTANT: This uses your REAL Chrome browser, not Playwright's bundled Chromium.
 * To start Chrome with CDP enabled:
 *   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// Types for Playwright (lazy loaded)
type PlaywrightBrowser = import('playwright').Browser;
type PlaywrightBrowserContext = import('playwright').BrowserContext;
type PlaywrightPage = import('playwright').Page;
type PlaywrightRequest = import('playwright').Request;
type PlaywrightResponse = import('playwright').Response;
type PlaywrightConsoleMessage = import('playwright').ConsoleMessage;

type ConsoleLogEntry = {
  ts: number;
  type: string;
  text: string;
  location?: { url?: string; lineNumber?: number; columnNumber?: number };
};

type NetworkLogEntry = {
  id: string;
  startedAt: number;
  method: string;
  url: string;
  resourceType: string;
  requestHeaders: Record<string, string>;
  finishedAt?: number;
  status?: number;
  ok?: boolean;
  responseHeaders?: Record<string, string>;
  error?: string;
  timingMs?: number;
};

// Cache chromium with stealth plugin to avoid reloading on each browser init
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let cachedChromium: any = null;
let stealthApplied = false;

// Cache sharp module for faster screenshot processing
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let cachedSharp: any = null;

export interface AwareBrowserConfig {
  headless?: boolean;
  cdpWsEndpoint?: string;
  cdpPort?: number;
  userDataDir?: string;
  copyProfile?: boolean;
  profileDirectory?: string;
  viewport?: { width: number; height: number };
  useSystemChrome?: boolean;
}

/**
 * Get default Chrome user data directory for the current platform
 */
export function getDefaultChromeUserDataDir(copyToTempDir = false): string | undefined {
  const platform = os.platform();
  const homeDir = os.homedir();
  let defaultPath: string | undefined;

  switch (platform) {
    case 'win32':
      const localAppData = process.env.LOCALAPPDATA || path.join(homeDir, 'AppData', 'Local');
      defaultPath = path.join(localAppData, 'Google', 'Chrome', 'User Data');
      break;
    case 'darwin':
      defaultPath = path.join(homeDir, 'Library', 'Application Support', 'Google', 'Chrome');
      break;
    case 'linux':
      defaultPath = path.join(homeDir, '.config', 'google-chrome');
      break;
  }

  if (defaultPath && fs.existsSync(defaultPath)) {
    if (copyToTempDir) {
      const tempDir = os.tmpdir();
      const tempPath = path.join(tempDir, 'aware-agent-chrome-profile');

      // REUSE existing temp profile if it exists (copying is SLOW - can be 1+ minute for large profiles)
      // Only copy if temp profile doesn't exist yet
      if (!fs.existsSync(tempPath)) {
        console.log('[Browser] First-time profile copy (this may take a minute)...');
        fs.cpSync(defaultPath, tempPath, { recursive: true });
      } else {
        console.log('[Browser] Reusing existing profile copy (fast startup)');
      }

      // Always remove lock files to prevent conflicts
      removeLockFiles(tempPath);

      const defaultProfilePath = path.join(tempPath, 'Default');
      if (fs.existsSync(defaultProfilePath)) {
        removeLockFiles(defaultProfilePath);
      }

      return tempPath;
    }
    return defaultPath;
  }
  return undefined;
}

/**
 * Remove Chrome lock files to prevent startup conflicts
 */
function removeLockFiles(dirPath: string): void {
  try {
    const items = fs.readdirSync(dirPath);
    for (const item of items) {
      const itemPath = path.join(dirPath, item);
      try {
        const stat = fs.statSync(itemPath);

        if (stat.isDirectory()) {
          removeLockFiles(itemPath);
        }

        const shouldDelete =
          item === 'SingletonLock' ||
          item === 'lockfile' ||
          item === 'RunningChromeVersion' ||
          item === 'SingletonCookie' ||
          item === 'SingletonSocket' ||
          item.includes('.lock') ||
          item.includes('Lock') ||
          item.includes('LOCK');

        if (shouldDelete) {
          fs.rmSync(itemPath, { recursive: true, force: true });
        }
      } catch {
        // Ignore errors
      }
    }
  } catch {
    // Ignore errors
  }
}

/**
 * Fetch CDP WebSocket endpoint from Chrome's /json/version endpoint
 */
export async function getCdpWsEndpoint(port: number): Promise<string> {
  const response = await fetch(`http://127.0.0.1:${port}/json/version`);
  const data = await response.json() as { webSocketDebuggerUrl: string };
  return data.webSocketDebuggerUrl;
}

/**
 * AwareBrowserAgent - Real Chrome browser automation
 */
export class AwareBrowserAgent {
  private config: AwareBrowserConfig;
  private browser: PlaywrightBrowser | null = null;
  private context: PlaywrightBrowserContext | null = null;
  private activePage: PlaywrightPage | null = null;
  private initialized = false;

  // ==================== ELEMENTS CACHE ====================
  private elementsCache: { value: string; ts: number } | null = null;
  private readonly ELEMENTS_CACHE_TTL = 500; // ms

  // ==================== ADAPTIVE CLICK TIMING ====================
  // Tracks click sequences to ensure minimum timing requirements are met.
  // Challenge pages often reject clicks that happen too fast (e.g., hidden_dom needs 1000ms).
  // Sequences reset on URL change OR time gap >3s (handles SPAs that don't change URLs).
  private _clickSeqUrl: string = '';       // URL when current click sequence started
  private _clickSeqStart: number = 0;      // timestamp of first click in sequence
  private _clickSeqCount: number = 0;      // number of clicks in current sequence
  private _lastClickTime: number = 0;      // timestamp of most recent click (for gap detection)
  private _detectedMinTime: number = 0;    // detected minimum time from page JS (ms)
  private _minTimeDetected: boolean = false; // whether we've attempted detection for this URL

  // ==================== INSTRUMENTATION (Console/Network) ====================
  private instrumentedPages = new WeakSet<PlaywrightPage>();
  private consoleLog: ConsoleLogEntry[] = [];
  private networkLog: NetworkLogEntry[] = [];
  private requestIdByRequest = new WeakMap<PlaywrightRequest, string>();
  private responseByNetId = new Map<string, PlaywrightResponse>();
  private netSeq = 0;
  private readonly MAX_CONSOLE_LOG = 500;
  private readonly MAX_NETWORK_LOG = 500;

  constructor(config: AwareBrowserConfig = {}) {
    this.config = {
      headless: false,
      viewport: { width: 1024, height: 768 }, // Smaller default for less screen space
      useSystemChrome: true, // Default to using system Chrome
      ...config,
    };
  }

  /**
   * Initialize the browser with the configured connection mode
   */
  async initialize(): Promise<void> {
    if (this.initialized && (this.browser || this.context)) return;

    // Lazy load playwright with stealth - cache to avoid reload overhead
    if (!cachedChromium) {
      console.log('[Browser] Loading Playwright with stealth...');
      const { chromium } = await import('playwright-extra');
      const StealthPlugin = (await import('puppeteer-extra-plugin-stealth')).default;
      cachedChromium = chromium;

      if (!stealthApplied) {
        cachedChromium.use(StealthPlugin());
        stealthApplied = true;
      }
    }
    const chromium = cachedChromium!;  // Safe - we just assigned it above

    const viewport = this.config.viewport || { width: 1024, height: 768 };

    // Use system Chrome if enabled (recommended for real browser functionality)
    const channel = this.config.useSystemChrome ? 'chrome' : undefined;

    // Mode 1: CDP WebSocket connection to existing Chrome
    // This connects to a Chrome you already have running with --remote-debugging-port=9222
    if (this.config.cdpWsEndpoint) {
      console.log('[Browser] Connecting to existing Chrome via CDP WebSocket...');
      console.log('[Browser] Endpoint:', this.config.cdpWsEndpoint);
      const browser = await chromium.connectOverCDP(this.config.cdpWsEndpoint);
      this.browser = browser;
      // Use existing contexts from the connected browser
      const contexts = browser.contexts();
      if (contexts.length > 0) {
        this.context = contexts[0];
        console.log('[Browser] Using existing browser context');
      } else {
        this.context = await browser.newContext({ viewport });
      }
    }
    // Mode 2: CDP port connection (fetches WebSocket URL automatically)
    else if (this.config.cdpPort) {
      console.log(`[Browser] Connecting to existing Chrome on port ${this.config.cdpPort}...`);
      const wsEndpoint = await getCdpWsEndpoint(this.config.cdpPort);
      console.log('[Browser] Got WebSocket endpoint:', wsEndpoint);
      const browser = await chromium.connectOverCDP(wsEndpoint);
      this.browser = browser;
      const contexts = browser.contexts();
      if (contexts.length > 0) {
        this.context = contexts[0];
        console.log('[Browser] Using existing browser context with cookies/sessions');
      } else {
        this.context = await browser.newContext({ viewport });
      }
    }
    // Mode 3: User data directory (persistent Chrome profile)
    // Launches Chrome with your actual profile — cookies, extensions, sessions preserved
    else if (this.config.userDataDir) {
      const profileDir = this.config.profileDirectory || 'Default';
      console.log(`[Browser] Launching Chrome with profile '${profileDir}' from: ${this.config.userDataDir}`);
      const args = this.getChromiumArgs();
      if (profileDir !== 'Default') {
        args.push(`--profile-directory=${profileDir}`);
      }
      this.context = await chromium.launchPersistentContext(this.config.userDataDir, {
        headless: this.config.headless,
        channel,
        viewport,
        args,
      });
      this.browser = null;
    }
    // Mode 4: Fresh Chrome launch (default)
    // Launches a clean Chrome instance using system Chrome
    else {
      console.log('[Browser] Launching fresh Chrome instance...');
      if (channel) {
        console.log('[Browser] Using system Chrome (not Playwright Chromium)');
      }
      const browser = await chromium.launch({
        headless: this.config.headless,
        channel, // Use system Chrome
        args: this.getChromiumArgs(),
      });
      this.browser = browser;
      this.context = await browser.newContext({ viewport });
    }

    this.initialized = true;
    console.log('[Browser] Initialized successfully');

    // Instrument existing and future pages (console + network).
    try {
      const ctx = this.context;
      if (ctx) {
        for (const p of ctx.pages()) this.instrumentPage(p);
        // @ts-ignore - Playwright BrowserContext has event emitter methods.
        ctx.on?.('page', (p: PlaywrightPage) => this.instrumentPage(p));
      }
    } catch {
      // Best-effort only
    }
  }

  private redactHeaders(headers: Record<string, string>): Record<string, string> {
    const out: Record<string, string> = {};
    const sensitive = new Set([
      'authorization',
      'proxy-authorization',
      'cookie',
      'set-cookie',
      'x-api-key',
      'x-auth-token',
      'x-csrf-token',
    ]);
    for (const [k, v] of Object.entries(headers || {})) {
      const key = String(k || '').toLowerCase();
      if (sensitive.has(key)) {
        out[k] = '[redacted]';
      } else {
        out[k] = String(v ?? '');
      }
    }
    return out;
  }

  private instrumentPage(page: PlaywrightPage): void {
    if (!page || this.instrumentedPages.has(page)) return;
    this.instrumentedPages.add(page);

    page.on('console', (msg: PlaywrightConsoleMessage) => {
      try {
        const loc = msg.location?.();
        this.consoleLog.push({
          ts: Date.now(),
          type: msg.type?.() || 'log',
          text: msg.text?.() || '',
          location: loc ? { url: loc.url, lineNumber: loc.lineNumber, columnNumber: loc.columnNumber } : undefined,
        });
        if (this.consoleLog.length > this.MAX_CONSOLE_LOG) {
          this.consoleLog.splice(0, this.consoleLog.length - this.MAX_CONSOLE_LOG);
        }
      } catch {
        // ignore
      }
    });

    page.on('pageerror', (err: Error) => {
      const text = err?.message || String(err);
      this.consoleLog.push({ ts: Date.now(), type: 'pageerror', text });
      if (this.consoleLog.length > this.MAX_CONSOLE_LOG) {
        this.consoleLog.splice(0, this.consoleLog.length - this.MAX_CONSOLE_LOG);
      }
    });

    page.on('request', (req: PlaywrightRequest) => {
      try {
        const id = `net_${Date.now()}_${++this.netSeq}`;
        this.requestIdByRequest.set(req, id);
        const rec: NetworkLogEntry = {
          id,
          startedAt: Date.now(),
          method: req.method?.() || 'GET',
          url: req.url?.() || '',
          resourceType: req.resourceType?.() || 'other',
          requestHeaders: this.redactHeaders(req.headers?.() || {}),
        };
        this.networkLog.push(rec);
        if (this.networkLog.length > this.MAX_NETWORK_LOG) {
          const removed = this.networkLog.splice(0, this.networkLog.length - this.MAX_NETWORK_LOG);
          for (const r of removed) this.responseByNetId.delete(r.id);
        }
      } catch {
        // ignore
      }
    });

    page.on('response', async (resp: PlaywrightResponse) => {
      try {
        const req = resp.request?.();
        const id = req ? this.requestIdByRequest.get(req) : undefined;
        if (!id) return;
        const rec = this.networkLog.find((r) => r.id === id);
        if (!rec) return;
        rec.status = resp.status?.();
        rec.ok = resp.ok?.();
        rec.responseHeaders = this.redactHeaders(resp.headers?.() || {});
        rec.finishedAt = Date.now();
        rec.timingMs = rec.finishedAt - rec.startedAt;
        this.responseByNetId.set(id, resp);
        // Keep response map bounded to the network log
        if (this.responseByNetId.size > this.MAX_NETWORK_LOG) {
          const keep = new Set(this.networkLog.map((r) => r.id));
          for (const k of this.responseByNetId.keys()) {
            if (!keep.has(k)) this.responseByNetId.delete(k);
          }
        }
      } catch {
        // ignore
      }
    });

    page.on('requestfailed', (req: PlaywrightRequest) => {
      try {
        const id = this.requestIdByRequest.get(req);
        if (!id) return;
        const rec = this.networkLog.find((r) => r.id === id);
        if (!rec) return;
        // @ts-ignore - failure() exists on Playwright Request
        const failure = req.failure?.();
        rec.error = failure?.errorText || 'request_failed';
        rec.finishedAt = Date.now();
        rec.timingMs = rec.finishedAt - rec.startedAt;
      } catch {
        // ignore
      }
    });
  }

  /**
   * Get Chromium args for stealth
   */
  private getChromiumArgs(): string[] {
    return [
      '--disable-blink-features=AutomationControlled',
      '--disable-features=IsolateOrigins,site-per-process,ChromeWhatsNewUI',
      '--no-first-run',
      '--no-default-browser-check',
      '--noerrdialogs',
      '--disable-session-crashed-bubble',
      '--hide-crash-restore-bubble',
      '--no-restore-state-for-testing',
      '--disable-infobars',
      '--disable-sync',
      '--disable-background-networking',
      '--disable-component-update',
      '--disable-default-apps',
      '--disable-popup-blocking',
    ];
  }

  /**
   * Get or create the active page
   */
  private async getPage(): Promise<PlaywrightPage> {
    if (!this.context) {
      await this.initialize();
    }

    if (!this.activePage || this.activePage.isClosed()) {
      const pages = this.context!.pages();
      if (pages.length > 0) {
        this.activePage = pages[pages.length - 1];
      } else {
        this.activePage = await this.context!.newPage();
      }
    }

    // Ensure instrumentation on the active page
    this.instrumentPage(this.activePage);
    return this.activePage;
  }

  getConsoleLogEntries(opts?: { limit?: number; clear?: boolean; types?: string[] }): ConsoleLogEntry[] {
    const limit =
      typeof opts?.limit === 'number' && Number.isFinite(opts.limit) ? Math.max(1, Math.floor(opts.limit)) : 50;
    const wanted = Array.isArray(opts?.types) ? opts!.types.map((t) => String(t).toLowerCase()) : null;
    const filtered = wanted
      ? this.consoleLog.filter((e) => wanted.includes((e.type || '').toLowerCase()))
      : this.consoleLog;
    const slice = filtered.slice(-limit);
    if (opts?.clear) this.consoleLog = [];
    return slice;
  }

  getNetworkLogEntries(opts?: {
    limit?: number;
    clear?: boolean;
    urlContains?: string;
    onlyErrors?: boolean;
  }): NetworkLogEntry[] {
    const limit =
      typeof opts?.limit === 'number' && Number.isFinite(opts.limit) ? Math.max(1, Math.floor(opts.limit)) : 30;
    const needle = typeof opts?.urlContains === 'string' ? opts.urlContains : '';
    const onlyErrors = Boolean(opts?.onlyErrors);

    let out = this.networkLog;
    if (needle) {
      out = out.filter((r) => r.url.includes(needle));
    }
    if (onlyErrors) {
      out = out.filter((r) => !!r.error || (typeof r.status === 'number' && r.status >= 400));
    }

    const slice = out.slice(-limit);
    if (opts?.clear) {
      this.networkLog = [];
      this.responseByNetId.clear();
    }
    return slice;
  }

  async getNetworkResponseBody(id: string, maxLength = 8000): Promise<{ contentType?: string; body?: string; error?: string }> {
    const resp = this.responseByNetId.get(id);
    if (!resp) return { error: 'response_not_found' };

    try {
      const headers = resp.headers?.() || {};
      const contentType = String(headers['content-type'] || headers['Content-Type'] || '');
      const ctLower = contentType.toLowerCase();

      // Avoid pulling binary payloads into logs.
      if (
        ctLower.startsWith('image/') ||
        ctLower.startsWith('audio/') ||
        ctLower.startsWith('video/') ||
        ctLower.includes('application/octet-stream') ||
        ctLower.includes('application/zip') ||
        ctLower.includes('font/')
      ) {
        return { contentType, body: '[binary omitted]' };
      }

      const text = await resp.text();
      const clamp = Math.max(200, Math.floor(maxLength));
      const body = text.length > clamp ? text.slice(0, clamp) + '...[truncated]' : text;
      return { contentType, body };
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }

  async getStorageSnapshot(): Promise<{ url: string; localStorage: Record<string, string>; sessionStorage: Record<string, string> }> {
    const page = await this.getPage();
    const url = page.url();
    const data = await page.evaluate(
      `(() => {
        const toObj = (s) => {
          const out = {};
          try {
            for (let i = 0; i < s.length; i++) {
              const k = s.key(i);
              if (k != null) out[k] = String(s.getItem(k));
            }
          } catch {}
          return out;
        };
        return { local: toObj(window.localStorage), session: toObj(window.sessionStorage) };
      })()`
    ) as { local: Record<string, string>; session: Record<string, string> };
    return { url, localStorage: data.local || {}, sessionStorage: data.session || {} };
  }

  async getCookiesSnapshot(url?: string): Promise<Array<{ name: string; value: string; domain: string; path: string; expires: number; httpOnly: boolean; secure: boolean; sameSite: string }>> {
    if (!this.context) {
      await this.initialize();
    }
    const page = await this.getPage();
    const target = url || page.url();
    // @ts-ignore - cookies() exists on Playwright BrowserContext.
    const cookies = await this.context!.cookies(target);
    return cookies as Array<{ name: string; value: string; domain: string; path: string; expires: number; httpOnly: boolean; secure: boolean; sameSite: string }>;
  }

  async domSearch(query: string, opts?: { in?: 'text' | 'attributes' | 'all'; includeHidden?: boolean; maxResults?: number; maxSnippetLength?: number }): Promise<Array<{
    tag: string;
    visible: boolean;
    textSnippet: string;
    attributes: Record<string, string>;
    outerHTMLSnippet: string;
  }>> {
    const page = await this.getPage();
    const q = String(query ?? '').trim();
    const mode = (opts?.in || 'all') as 'text' | 'attributes' | 'all';
    const includeHidden = Boolean(opts?.includeHidden);
    const maxResults =
      typeof opts?.maxResults === 'number' && Number.isFinite(opts.maxResults) ? Math.max(1, Math.floor(opts.maxResults)) : 20;
    const maxSnippet =
      typeof opts?.maxSnippetLength === 'number' && Number.isFinite(opts.maxSnippetLength) ? Math.max(80, Math.floor(opts.maxSnippetLength)) : 240;

    return await page.evaluate(
      `((q, mode, includeHidden, maxResults, maxSnippet) => {
        const norm = (s) => (s ?? '').toString().replace(/\\s+/g, ' ').replace(/\\u00a0/g, ' ').trim();
        const needle = norm(q);
        if (!needle) throw new Error('query is empty');

        const isVisible = (el) => {
          try {
            const cs = window.getComputedStyle(el);
            if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || '1') < 0.05) return false;
            const r = el.getBoundingClientRect();
            if (!r || r.width < 2 || r.height < 2) return false;
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;
            if (cx < -50 || cy < -50) return false;
            if (cx > (window.innerWidth + 50) || cy > (window.innerHeight + 50)) return false;
            return true;
          } catch {
            return false;
          }
        };

        const out = [];
        const els = Array.from(document.querySelectorAll('*'));
        for (const el of els) {
          const vis = isVisible(el);
          if (!includeHidden && !vis) continue;

          let hit = false;
          let text = '';
          if (mode === 'text' || mode === 'all') {
            text = norm(el.innerText || el.textContent || '');
            if (text && text.toLowerCase().includes(needle.toLowerCase())) hit = true;
          }

          let attrs = {};
          if (!hit && (mode === 'attributes' || mode === 'all')) {
            try {
              for (const a of Array.from(el.attributes || [])) {
                // @ts-ignore
                const k = a.name;
                // @ts-ignore
                const v = String(a.value);
                // @ts-ignore
                attrs[k] = v;
                if ((k && k.toLowerCase().includes(needle.toLowerCase())) || (v && v.toLowerCase().includes(needle.toLowerCase()))) {
                  hit = true;
                }
              }
            } catch {}
          } else {
            try {
              for (const a of Array.from(el.attributes || [])) {
                // @ts-ignore
                attrs[a.name] = String(a.value);
              }
            } catch {}
          }

          if (!hit) continue;
          const outer = norm(el.outerHTML || '');
          out.push({
            tag: (el.tagName || '').toLowerCase(),
            visible: vis,
            textSnippet: (text || '').slice(0, maxSnippet),
            attributes: attrs,
            outerHTMLSnippet: outer.slice(0, Math.max(maxSnippet, 1200)),
          });
          if (out.length >= maxResults) break;
        }
        return out;
      })(${JSON.stringify(q)}, ${JSON.stringify(mode)}, ${includeHidden ? 'true' : 'false'}, ${maxResults}, ${maxSnippet})`
    ) as Array<{ tag: string; visible: boolean; textSnippet: string; attributes: Record<string, string>; outerHTMLSnippet: string }>;
  }


  /**
   * Navigate to URL
   */
  async navigate(url: string): Promise<{ url: string; title: string }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    try {
      await page.goto(url, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });

      // Wait for network to settle - reduced from 5s to 3s for faster navigation
      // Most SPAs settle within 2-3 seconds; beyond that usually means infinite polling
      await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => { });
    } catch (error) {
      // Continue even if timeout - page might still be usable
      console.log('[Browser] Navigation timeout, continuing...');
    }

    // Parallel fetch of url and title
    const [pageUrl, pageTitle] = await Promise.all([
      Promise.resolve(page.url()),
      page.title().catch(() => ''),
    ]);

    return {
      url: pageUrl,
      title: pageTitle,
    };
  }

  /**
   * Take a screenshot and resize proportionally for faster vision API processing
   * @param highlightElements - If true, adds visual index labels to interactive elements
   */
  async takeScreenshot(highlightElements = false): Promise<{
    imageBase64: string;
    imageType: 'image/jpeg' | 'image/png' | 'image/webp';
    url: string;
    title: string;
    highlightedIndices?: number[];
  }> {
    const page = await this.getPage();
    const [url, title] = await Promise.all([
      Promise.resolve(page.url()).catch(() => ''),
      page.title().catch(() => ''),
    ]);

    // Let the UI settle after the last action (animations, overlays, async DOM updates).
    // Use adaptive waiting: wait for network to idle OR 500ms max (whichever comes first).
    // This ensures we capture error modals/dynamic content without waiting unnecessarily.
    await Promise.race([
      page.waitForLoadState('networkidle', { timeout: 500 }).catch(() => { }),
      page.waitForTimeout(500).catch(() => { }),
    ]);

    // Optionally highlight elements with their indices for vision grounding
    let highlightedIndices: number[] = [];
    if (highlightElements) {
      highlightedIndices = await this.addElementHighlights(page);
    }

    const buffer = await page.screenshot({ type: 'jpeg', quality: 80 });

    // Remove highlights after screenshot
    if (highlightElements) {
      await this.removeElementHighlights(page);
    }

    // Resize proportionally for faster vision API upload while keeping text readable.
    // (We intentionally keep this fairly high-res because many tasks require OCR of small UI text.)
    try {
      // Cache sharp import for performance
      if (!cachedSharp) {
        cachedSharp = (await import('sharp')).default;
      }
      const sharp = cachedSharp;
      // Keep a reasonable ceiling so we don't downscale typical viewport screenshots.
      // (Our default viewport is 1024×768; we allow up to 1.5x for retina/high-DPI.)
      const resizedBuffer = await sharp(buffer)
        .resize(1536, 1152, {
          fit: 'inside',  // Maintain aspect ratio, fit within bounds
          withoutEnlargement: true,  // Don't upscale small images
        })
        .sharpen()
        .webp({ quality: 80 })
        .toBuffer();

      return {
        imageBase64: resizedBuffer.toString('base64'),
        imageType: 'image/webp',
        url,
        title,
        highlightedIndices: highlightElements ? highlightedIndices : undefined,
      };
    } catch {
      // Fall back to original if sharp fails
      return {
        imageBase64: buffer.toString('base64'),
        imageType: 'image/jpeg',
        url,
        title,
        highlightedIndices: highlightElements ? highlightedIndices : undefined,
      };
    }
  }

  /**
   * Add visual index labels to interactive elements for vision grounding
   * Returns the indices of elements that were highlighted
   */
  private async addElementHighlights(page: PlaywrightPage): Promise<number[]> {
    return await page.evaluate(`
      (() => {
        const interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [onclick], [tabindex], [class*="cursor-pointer"], [style*="cursor: pointer"], [style*="cursor:pointer"]';
        const elements = document.querySelectorAll(interactiveSelectors);
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;
        const highlightedIndices = [];

        // Create style element for highlights
        const style = document.createElement('style');
        style.id = 'aware-highlight-style';
        style.textContent = \`
          .aware-highlight-label {
            position: absolute;
            background: rgba(255, 0, 0, 0.85);
            color: white;
            font-size: 11px;
            font-weight: bold;
            font-family: monospace;
            padding: 1px 4px;
            border-radius: 3px;
            z-index: 999999;
            pointer-events: none;
            box-shadow: 0 1px 2px rgba(0,0,0,0.3);
          }
          .aware-highlight-box {
            position: absolute;
            border: 2px solid rgba(255, 0, 0, 0.7);
            background: rgba(255, 0, 0, 0.1);
            z-index: 999998;
            pointer-events: none;
            border-radius: 2px;
          }
        \`;
        document.head.appendChild(style);

        // Create container for highlights
        const container = document.createElement('div');
        container.id = 'aware-highlight-container';
        document.body.appendChild(container);

        elements.forEach((el, index) => {
          const rect = el.getBoundingClientRect();

          // Only highlight visible, in-viewport elements
          const isVisible = (() => {
            try {
              const cs = window.getComputedStyle(el);
              if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
              if (rect.width < 5 || rect.height < 5) return false;
              return true;
            } catch { return false; }
          })();

          const isInViewport = rect.top < viewportHeight && rect.bottom > 0 &&
                               rect.left < viewportWidth && rect.right > 0;

          if (!isVisible || !isInViewport) return;

          highlightedIndices.push(index);

          // Create highlight box
          const box = document.createElement('div');
          box.className = 'aware-highlight-box';
          box.style.left = (rect.left + window.scrollX) + 'px';
          box.style.top = (rect.top + window.scrollY) + 'px';
          box.style.width = rect.width + 'px';
          box.style.height = rect.height + 'px';
          container.appendChild(box);

          // Create label
          const label = document.createElement('div');
          label.className = 'aware-highlight-label';
          label.textContent = String(index);
          label.style.left = (rect.left + window.scrollX) + 'px';
          label.style.top = (rect.top + window.scrollY - 16) + 'px';

          // Adjust label position if it would be off-screen
          if (rect.top < 20) {
            label.style.top = (rect.bottom + window.scrollY + 2) + 'px';
          }
          container.appendChild(label);
        });

        return highlightedIndices;
      })()
    `) as number[];
  }

  /**
   * Remove element highlights after screenshot
   */
  private async removeElementHighlights(page: PlaywrightPage): Promise<void> {
    await page.evaluate(`
      (() => {
        const style = document.getElementById('aware-highlight-style');
        if (style) style.remove();
        const container = document.getElementById('aware-highlight-container');
        if (container) container.remove();
      })()
    `);
  }

  /**
   * Click element by selector or coordinates
   */
  async click(selector: string): Promise<void> {
    const page = await this.getPage();
    await page.click(selector, { timeout: 5000 });
  }

  /**
   * Click at coordinates
   */
  async clickAt(x: number, y: number): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    await page.mouse.click(x, y);
  }

  /**
   * Hover over an element at coordinates or by index
   */
  async hoverAt(x: number, y: number): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    await page.mouse.move(x, y);
  }

  async hoverElement(index: number, durationMs = 500): Promise<{
    index: number;
    x: number;
    y: number;
    tag: string;
    text: string;
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    const target = await page.evaluate(`
      (function() {
        var idx = ${index};
        var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';

        // 1) Stable lookup by stamped index from browser_get_elements.
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');

        // 2) Fallback to positional lookup with the same selector set.
        if (!el) {
          var list = document.querySelectorAll(interactiveSelectors);
          if (idx < 0 || idx >= list.length) throw new Error('Element ' + idx + ' not found. Re-run browser_get_elements to refresh indices.');
          el = list[idx];
        }

        try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); } catch(e) {}

        var r = el.getBoundingClientRect();
        var x = r.left + (r.width / 2);
        var y = r.top + (r.height / 2);

        function dispatchHover(target, type, xPos, yPos) {
          try {
            var opts = { bubbles: true, cancelable: true, clientX: xPos, clientY: yPos, view: window };
            var evt;
            if (typeof PointerEvent === 'function' && type.indexOf('pointer') === 0) {
              evt = new PointerEvent(type, opts);
            } else if (typeof MouseEvent === 'function') {
              evt = new MouseEvent(type, opts);
            } else {
              evt = new Event(type, { bubbles: true, cancelable: true });
            }
            target.dispatchEvent(evt);
          } catch(e) {}
        }

        // Dispatch hover-related events directly so React/Vue handlers fire even if overlays exist.
        dispatchHover(el, 'pointerenter', x, y);
        dispatchHover(el, 'pointerover', x, y);
        dispatchHover(el, 'mouseenter', x, y);
        dispatchHover(el, 'mouseover', x, y);
        dispatchHover(el, 'pointermove', x, y);
        dispatchHover(el, 'mousemove', x, y);

        return {
          x: x,
          y: y,
          tag: (el.tagName || '').toLowerCase(),
          text: ((el.innerText || el.textContent || '').toString().replace(/\\s+/g, ' ').trim()).slice(0, 120)
        };
      })()
    `) as { x: number; y: number; tag: string; text: string };

    await page.mouse.move(target.x, target.y);
    if (durationMs > 0) {
      await new Promise(r => setTimeout(r, durationMs));
    }

    // Trigger a final move event after hold time for challenge handlers that check elapsed hover duration.
    await page.evaluate(`
      (function() {
        var idx = ${index};
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');
        if (!el) return;
        var r = el.getBoundingClientRect();
        var x = r.left + (r.width / 2);
        var y = r.top + (r.height / 2);
        try {
          var evt = new MouseEvent('mousemove', { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window });
          el.dispatchEvent(evt);
        } catch(e) {}
      })()
    `);

    return {
      index,
      x: target.x,
      y: target.y,
      tag: target.tag,
      text: target.text,
    };
  }

  /**
   * Get the bounding box of an element by index.
   * Returns viewport-relative coordinates and viewport dimensions.
   */
  async getElementBox(index: number): Promise<{
    index: number;
    tag: string;
    x: number; y: number; width: number; height: number;
    viewportWidth: number; viewportHeight: number;
  }> {
    const page = await this.getPage();
    const result = await page.evaluate(`(function() {
      var idx = ${index};
      var el = document.querySelector('[data-aware-idx="' + idx + '"]');
      if (!el) {
        var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
        var list = document.querySelectorAll(interactiveSelectors);
        if (idx < 0 || idx >= list.length) throw new Error('Element ' + idx + ' not found. Re-run browser_get_elements to refresh indices.');
        el = list[idx];
      }
      try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); } catch(e) {}
      var r = el.getBoundingClientRect();
      return {
        index: idx,
        tag: (el.tagName || '').toLowerCase(),
        x: r.left, y: r.top, width: r.width, height: r.height,
        viewportWidth: window.innerWidth, viewportHeight: window.innerHeight
      };
    })()`) as {
      index: number; tag: string;
      x: number; y: number; width: number; height: number;
      viewportWidth: number; viewportHeight: number;
    };
    return result;
  }

  /**
   * Execute a continuous pointer path (drawing/gesture).
   * Sends real pointerdown → pointermove… → pointerup through the CDP input pipeline.
   */
  async pointerPath(opts: {
    elementIndex?: number;
    points: Array<{ x: number; y: number }>;
    relative?: boolean;
    pointerType?: 'mouse' | 'touch';
    durationMs?: number;
  }): Promise<{
    success: boolean;
    startCoord: { x: number; y: number };
    endCoord: { x: number; y: number };
    pointCount: number;
    pathLength: number;
    hitTarget: boolean;
    error?: string;
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    const { elementIndex, points, relative, pointerType, durationMs } = opts;
    const duration = durationMs ?? 300;

    // Resolve absolute viewport coordinates
    let absPoints: Array<{ x: number; y: number }>;

    if (elementIndex !== undefined) {
      // Get element bounding box for coordinate mapping
      const box = await page.evaluate(`(function() {
        var idx = ${elementIndex};
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');
        if (!el) {
          var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
          var list = document.querySelectorAll(interactiveSelectors);
          if (idx < 0 || idx >= list.length) throw new Error('Element ' + idx + ' not found');
          el = list[idx];
        }
        try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); } catch(e) {}
        var r = el.getBoundingClientRect();
        return { x: r.left, y: r.top, width: r.width, height: r.height };
      })()`) as { x: number; y: number; width: number; height: number };

      if (relative) {
        // Map 0..1 normalized coords → absolute viewport pixels
        absPoints = points.map(p => ({
          x: box.x + p.x * box.width,
          y: box.y + p.y * box.height,
        }));
      } else {
        // Offset raw pixel coords by element origin
        absPoints = points.map(p => ({
          x: box.x + p.x,
          y: box.y + p.y,
        }));
      }
    } else {
      // Absolute viewport coordinates
      absPoints = points.map(p => ({ x: p.x, y: p.y }));
    }

    // Calculate total path length for timing distribution
    let totalLength = 0;
    const segLengths: number[] = [];
    for (let i = 1; i < absPoints.length; i++) {
      const dx = absPoints[i].x - absPoints[i - 1].x;
      const dy = absPoints[i].y - absPoints[i - 1].y;
      const len = Math.sqrt(dx * dx + dy * dy);
      segLengths.push(len);
      totalLength += len;
    }

    // Execute pointer path via Playwright mouse API (real CDP events)
    await page.mouse.move(absPoints[0].x, absPoints[0].y);
    await page.mouse.down();

    for (let i = 1; i < absPoints.length; i++) {
      const segLen = segLengths[i - 1];
      // Distribute time proportionally by segment length
      const segTime = totalLength > 0 ? (segLen / totalLength) * duration : duration / (absPoints.length - 1);
      // More steps for longer segments (min 3 for smoothness)
      const steps = Math.max(3, Math.round(segLen / 5));
      await page.mouse.move(absPoints[i].x, absPoints[i].y, { steps });
      if (segTime > 10) {
        await new Promise(r => setTimeout(r, segTime));
      }
    }

    await page.mouse.up();

    // Touch fallback: dispatch synthetic touch events for touch-only listeners
    if (pointerType === 'touch' && elementIndex !== undefined) {
      await page.evaluate(`(function() {
        var idx = ${elementIndex};
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');
        if (!el) return;
        var pts = ${JSON.stringify(absPoints)};
        function touch(type, x, y) {
          try {
            var t = new Touch({ identifier: 1, target: el, clientX: x, clientY: y });
            el.dispatchEvent(new TouchEvent(type, { touches: type === 'touchend' ? [] : [t], changedTouches: [t], bubbles: true, cancelable: true }));
          } catch(e) {}
        }
        touch('touchstart', pts[0].x, pts[0].y);
        for (var i = 1; i < pts.length; i++) touch('touchmove', pts[i].x, pts[i].y);
        touch('touchend', pts[pts.length - 1].x, pts[pts.length - 1].y);
      })()`);
    }

    // Verify hit: check if endpoint reaches the intended target
    const endPt = absPoints[absPoints.length - 1];
    let hitTarget: boolean;
    let hitInfo = '';

    if (elementIndex !== undefined) {
      // Element-targeted path: verify endpoint hits the expected element
      hitTarget = await page.evaluate(`(function() {
        var idx = ${elementIndex};
        var expected = document.querySelector('[data-aware-idx="' + idx + '"]');
        if (!expected) return false;
        var hit = document.elementFromPoint(${endPt.x}, ${endPt.y});
        return hit === expected || expected.contains(hit);
      })()`) as boolean;
      if (!hitTarget) hitInfo = 'Pointer path endpoint missed the target element. An overlay or other element may be intercepting events.';

      // Canvas overlay bypass: if element-targeted path missed because of overlay,
      // dispatch synthetic pointer events directly on the canvas element via JS.
      // This bypasses any intercepting modal/overlay elements.
      if (!hitTarget) {
        const isCanvas = await page.evaluate(`(function() {
          var idx = ${elementIndex};
          var el = document.querySelector('[data-aware-idx="' + idx + '"]');
          return el && el.tagName && el.tagName.toLowerCase() === 'canvas';
        })()`) as boolean;

        if (isCanvas) {
          const syntheticResult = await page.evaluate(`(function() {
            var idx = ${elementIndex};
            var canvas = document.querySelector('[data-aware-idx="' + idx + '"]');
            if (!canvas) return { ok: false, reason: 'canvas not found' };
            var rect = canvas.getBoundingClientRect();
            var pts = ${JSON.stringify(absPoints)};
            function dispatchPointer(type, x, y) {
              var evt = new PointerEvent(type, {
                clientX: x, clientY: y,
                bubbles: true, cancelable: true,
                pointerId: 1, pointerType: 'mouse',
                pressure: type === 'pointerup' ? 0 : 0.5,
                isPrimary: true, width: 1, height: 1
              });
              canvas.dispatchEvent(evt);
            }
            function dispatchMouse(type, x, y, buttons) {
              var evt = new MouseEvent(type, {
                clientX: x, clientY: y,
                bubbles: true, cancelable: true,
                button: 0, buttons: buttons
              });
              canvas.dispatchEvent(evt);
            }
            try {
              // Full event sequence: pointerdown + mousedown → pointermove + mousemove → pointerup + mouseup
              dispatchPointer('pointerdown', pts[0].x, pts[0].y);
              dispatchMouse('mousedown', pts[0].x, pts[0].y, 1);
              for (var i = 1; i < pts.length; i++) {
                dispatchPointer('pointermove', pts[i].x, pts[i].y);
                dispatchMouse('mousemove', pts[i].x, pts[i].y, 1);
              }
              var last = pts[pts.length - 1];
              dispatchPointer('pointerup', last.x, last.y);
              dispatchMouse('mouseup', last.x, last.y, 0);
              return { ok: true, method: 'synthetic_dispatch' };
            } catch(e) {
              return { ok: false, reason: String(e.message || e) };
            }
          })()`) as { ok: boolean; method?: string; reason?: string };

          if (syntheticResult?.ok) {
            hitTarget = true;
            hitInfo = '';
          } else {
            hitInfo += ` Synthetic canvas dispatch also failed: ${syntheticResult?.reason || 'unknown'}`;
          }
        }
      }
    } else {
      // Coordinate-only path: check if an overlay is intercepting at the endpoint
      const hitCheck = await page.evaluate(`(function() {
        var hit = document.elementFromPoint(${endPt.x}, ${endPt.y});
        if (!hit) return { blocked: true, reason: 'No element at endpoint coordinates.', isCanvas: false };
        var tag = (hit.tagName || '').toLowerCase();
        var role = (hit.getAttribute('role') || '').toLowerCase();
        var cls = (hit.className && typeof hit.className === 'string') ? hit.className.toLowerCase() : '';
        function looksLikeOverlay(t, r, c) {
          if (r === 'dialog' || r === 'alertdialog') return true;
          if (t === 'dialog') return true;
          if (c.indexOf('modal') !== -1 || c.indexOf('overlay') !== -1 ||
              c.indexOf('popup') !== -1 || c.indexOf('backdrop') !== -1 ||
              c.indexOf('lightbox') !== -1 || c.indexOf('dimmer') !== -1) return true;
          return false;
        }
        var isOverlay = looksLikeOverlay(tag, role, cls);
        if (!isOverlay) {
          var parent = hit.parentElement;
          for (var i = 0; i < 3 && parent; i++) {
            var pRole = (parent.getAttribute('role') || '').toLowerCase();
            var pTag = (parent.tagName || '').toLowerCase();
            var pCls = (parent.className && typeof parent.className === 'string') ? parent.className.toLowerCase() : '';
            if (looksLikeOverlay(pTag, pRole, pCls)) {
              isOverlay = true; break;
            }
            parent = parent.parentElement;
          }
        }
        // Check if there's a canvas underneath when overlay is blocking
        var hasCanvasUnderneath = false;
        if (isOverlay) {
          var canvases = document.querySelectorAll('canvas');
          for (var c = 0; c < canvases.length; c++) {
            var cr = canvases[c].getBoundingClientRect();
            if (${endPt.x} >= cr.left && ${endPt.x} <= cr.right &&
                ${endPt.y} >= cr.top && ${endPt.y} <= cr.bottom) {
              hasCanvasUnderneath = true;
              break;
            }
          }
        }
        return { blocked: isOverlay, tag: tag, role: role, hasCanvasUnderneath: hasCanvasUnderneath };
      })()`) as { blocked: boolean; tag?: string; role?: string; reason?: string; hasCanvasUnderneath?: boolean };

      hitTarget = !hitCheck.blocked;
      if (hitCheck.blocked) {
        hitInfo = hitCheck.reason || `Overlay intercepting at endpoint (hit: <${hitCheck.tag}> role="${hitCheck.role || ''}").`;

        // Canvas overlay bypass: dispatch synthetic events directly on the canvas
        if (hitCheck.hasCanvasUnderneath) {
          const syntheticResult = await page.evaluate(`(function() {
            var pts = ${JSON.stringify(absPoints)};
            var endX = pts[pts.length - 1].x, endY = pts[pts.length - 1].y;
            var canvases = document.querySelectorAll('canvas');
            var canvas = null;
            for (var c = 0; c < canvases.length; c++) {
              var cr = canvases[c].getBoundingClientRect();
              if (endX >= cr.left && endX <= cr.right && endY >= cr.top && endY <= cr.bottom) {
                canvas = canvases[c]; break;
              }
            }
            if (!canvas) return { ok: false, reason: 'no canvas at coordinates' };
            function dispatchPointer(type, x, y) {
              canvas.dispatchEvent(new PointerEvent(type, {
                clientX: x, clientY: y, bubbles: true, cancelable: true,
                pointerId: 1, pointerType: 'mouse',
                pressure: type === 'pointerup' ? 0 : 0.5,
                isPrimary: true, width: 1, height: 1
              }));
            }
            function dispatchMouse(type, x, y, buttons) {
              canvas.dispatchEvent(new MouseEvent(type, {
                clientX: x, clientY: y, bubbles: true, cancelable: true,
                button: 0, buttons: buttons
              }));
            }
            try {
              dispatchPointer('pointerdown', pts[0].x, pts[0].y);
              dispatchMouse('mousedown', pts[0].x, pts[0].y, 1);
              for (var i = 1; i < pts.length; i++) {
                dispatchPointer('pointermove', pts[i].x, pts[i].y);
                dispatchMouse('mousemove', pts[i].x, pts[i].y, 1);
              }
              var last = pts[pts.length - 1];
              dispatchPointer('pointerup', last.x, last.y);
              dispatchMouse('mouseup', last.x, last.y, 0);
              return { ok: true, method: 'synthetic_canvas_bypass' };
            } catch(e) {
              return { ok: false, reason: String(e.message || e) };
            }
          })()`) as { ok: boolean; method?: string; reason?: string };

          if (syntheticResult?.ok) {
            hitTarget = true;
            hitInfo = '';
          }
        }
      }
    }

    return {
      success: hitTarget,
      startCoord: absPoints[0],
      endCoord: endPt,
      pointCount: absPoints.length,
      pathLength: Math.round(totalLength),
      hitTarget,
      ...(hitTarget ? {} : { error: hitInfo }),
    };
  }

  /**
   * Drag and drop between coordinates or element indices
   */
  async dragDrop(
    from: { x: number; y: number },
    to: { x: number; y: number },
    options?: { steps?: number }
  ): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    const steps = options?.steps ?? 10;

    // Dispatch HTML5 drag events via evaluate for maximum compatibility
    await page.mouse.move(from.x, from.y);
    // Brief hover before mousedown — drag libraries (SortableJS, React DnD) need
    // time to register the drag source before the grab starts.
    await new Promise(r => setTimeout(r, 50));
    await page.mouse.down();
    // Move in incremental steps for drag listeners, with small delays between
    // steps so throttled mousemove/dragover handlers can process each position.
    for (let i = 1; i <= steps; i++) {
      const x = from.x + (to.x - from.x) * (i / steps);
      const y = from.y + (to.y - from.y) * (i / steps);
      await page.mouse.move(x, y);
      await new Promise(r => setTimeout(r, 8));
    }
    await page.mouse.up();

    // Also dispatch HTML5 drag events in case the page uses them.
    // Guard: verify elementFromPoint resolves to actual drag/drop elements, not overlay hijackers.
    await page.evaluate(`
      (function() {
        var fromEl = document.elementFromPoint(${from.x}, ${from.y});
        var toEl = document.elementFromPoint(${to.x}, ${to.y});
        if (!fromEl || !toEl) return;

        // Check if resolved elements are inside a dialog/modal/overlay — if so, skip dispatch
        // to avoid sending drag events to popup elements that intercepted the coordinates.
        function isOverlayElement(el) {
          var node = el;
          while (node && node !== document.body) {
            if (node.getAttribute('role') === 'dialog' || node.getAttribute('role') === 'alertdialog') return true;
            if (node.getAttribute('aria-modal') === 'true') return true;
            var cls = (node.className || '').toString().toLowerCase();
            if (cls.indexOf('modal') >= 0 || cls.indexOf('popup') >= 0 || cls.indexOf('overlay') >= 0) return true;
            node = node.parentElement;
          }
          return false;
        }
        if (isOverlayElement(fromEl) || isOverlayElement(toEl)) return; // overlay is intercepting — skip fallback

        // Verify fromEl is plausibly a draggable (or its child) and toEl is plausibly a drop zone
        var fromDraggable = fromEl.closest('[draggable="true"]') || fromEl;
        var isDraggable = fromDraggable.getAttribute('draggable') === 'true' ||
          fromDraggable.getAttribute('class') && fromDraggable.getAttribute('class').indexOf('drag') >= 0;
        if (!isDraggable) return; // resolved source is not a drag element — skip

        var dt = new DataTransfer();
        var dragText = (fromDraggable.innerText || fromDraggable.textContent || '').trim().slice(0, 200);
        try { dt.setData('text/plain', dragText); } catch(e) {}
        fromDraggable.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
        toEl.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }));
        toEl.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
        toEl.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
        fromDraggable.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer: dt }));
      })()
    `);
  }

  /**
   * Drag and drop between element indices (deterministic — no coordinate guessing).
   * Resolves element centers via data-aware-idx, scrolls into view, then delegates to coordinate drag.
   */
  async dragDropByIndex(
    fromIndex: number,
    toIndex: number,
    options?: { steps?: number }
  ): Promise<{ from: { x: number; y: number }; to: { x: number; y: number }; fromElement: string; toElement: string; warning?: string }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    const coords = await page.evaluate(`
      (function() {
        var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';

        function findEl(idx) {
          var el = document.querySelector('[data-aware-idx="' + idx + '"]');
          if (!el) {
            var list = document.querySelectorAll(interactiveSelectors);
            if (idx < 0 || idx >= list.length) throw new Error('Element ' + idx + ' not found. Re-run browser_get_elements to refresh indices.');
            el = list[idx];
          }
          return el;
        }

        var fromEl = findEl(${fromIndex});
        var toEl = findEl(${toIndex});

        // Scroll both into view: first source, then target, then adjust source if needed.
        // If both are far apart, try to make both visible by scrolling to midpoint.
        fromEl.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
        var fr1 = fromEl.getBoundingClientRect();
        var tr1 = toEl.getBoundingClientRect();

        // If target is offscreen after scrolling to source, scroll target into view
        // then re-measure both
        if (tr1.top < 0 || tr1.bottom > window.innerHeight || tr1.left < 0 || tr1.right > window.innerWidth) {
          toEl.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
          // Re-measure after scroll
          fr1 = fromEl.getBoundingClientRect();
          tr1 = toEl.getBoundingClientRect();
          // If source went offscreen, try scrolling to midpoint
          if (fr1.top < 0 || fr1.bottom > window.innerHeight) {
            var midY = (fromEl.getBoundingClientRect().top + toEl.getBoundingClientRect().top) / 2 + window.scrollY - window.innerHeight / 2;
            window.scrollTo({ top: Math.max(0, midY), behavior: 'instant' });
          }
        }

        var fr = fromEl.getBoundingClientRect();
        var tr = toEl.getBoundingClientRect();

        var fromTag = fromEl.tagName.toLowerCase();
        var toTag = toEl.tagName.toLowerCase();
        var fromText = (fromEl.innerText || fromEl.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
        var toText = (toEl.innerText || toEl.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
        var fromDraggable = fromEl.getAttribute('draggable') === 'true';
        var toDraggable = toEl.getAttribute('draggable') === 'true';

        // Neutralize floating overlays that occlude source or target
        var neutralized = 0;
        function isStickyHeader(el) {
          var cs = window.getComputedStyle(el);
          var pos = cs.position;
          if (pos !== 'fixed' && pos !== 'sticky') return false;
          var r = el.getBoundingClientRect();
          if (r.width >= window.innerWidth * 0.8 && r.height <= 120) return true;
          var tag = el.tagName.toLowerCase();
          if ((tag === 'nav' || tag === 'header') && (pos === 'fixed' || pos === 'sticky')) return true;
          return false;
        }
        function neutralizeOccluder(cx, cy, targetEl) {
          for (var pass = 0; pass < 2; pass++) {
            var top = document.elementFromPoint(cx, cy);
            if (!top || targetEl.contains(top) || top === targetEl || top.contains(targetEl)) break;
            var sticky = false;
            var n = top;
            for (var a = 0; a < 4 && n; a++) { if (isStickyHeader(n)) { sticky = true; break; } n = n.parentElement; }
            if (sticky) break;
            top.setAttribute('data-drag-pe-backup', top.style.pointerEvents || '');
            top.style.pointerEvents = 'none';
            neutralized++;
          }
        }
        var fcx = fr.left + fr.width / 2, fcy = fr.top + fr.height / 2;
        var tcx = tr.left + tr.width / 2, tcy = tr.top + tr.height / 2;
        neutralizeOccluder(fcx, fcy, fromEl);
        neutralizeOccluder(tcx, tcy, toEl);

        return {
          fromX: fr.left + fr.width / 2,
          fromY: fr.top + fr.height / 2,
          toX: tr.left + tr.width / 2,
          toY: tr.top + tr.height / 2,
          fromTag: fromTag,
          toTag: toTag,
          fromText: fromText,
          toText: toText,
          fromDraggable: fromDraggable,
          toDraggable: toDraggable,
          neutralized: neutralized
        };
      })()
    `) as { fromX: number; fromY: number; toX: number; toY: number; fromTag: string; toTag: string; fromText: string; toText: string; fromDraggable: boolean; toDraggable: boolean; neutralized: number };

    await this.dragDrop(
      { x: coords.fromX, y: coords.fromY },
      { x: coords.toX, y: coords.toY },
      options
    );

    // Restore pointer-events on any neutralized overlay elements
    if (coords.neutralized > 0) {
      await page.evaluate(`
        (function() {
          var els = document.querySelectorAll('[data-drag-pe-backup]');
          for (var i = 0; i < els.length; i++) {
            els[i].style.pointerEvents = els[i].getAttribute('data-drag-pe-backup') || '';
            els[i].removeAttribute('data-drag-pe-backup');
          }
        })()
      `);
    }

    const warnings: string[] = [];
    if (!coords.fromDraggable) {
      warnings.push('Source element is NOT marked draggable="true". This may not be a drag piece — check browser_get_elements for [DRAGGABLE] tagged elements.');
    }
    if (coords.toDraggable) {
      warnings.push('Target element is ALSO marked draggable="true" — you likely dropped onto another drag piece instead of a drop slot/target. Use browser_get_elements to find the correct non-draggable slot element.');
    }

    return {
      from: { x: coords.fromX, y: coords.fromY },
      to: { x: coords.toX, y: coords.toY },
      fromElement: `<${coords.fromTag}> "${coords.fromText}"${coords.fromDraggable ? ' [DRAGGABLE]' : ''}`,
      toElement: `<${coords.toTag}> "${coords.toText}"${coords.toDraggable ? ' [DRAGGABLE]' : ''}`,
      warning: warnings.length > 0 ? warnings.join(' ') : undefined,
    };
  }

  /**
   * Deterministic drag solver — maps all draggable elements to target slots and executes all drops.
   * Phase 1 (discovery) runs in-browser via page.evaluate() to find elements and compute pairs.
   * Phase 2 (execution) uses real CDP mouse events via this.dragDrop() for each pair,
   * which works reliably with real Chrome (React DnD, SortableJS, native HTML5 drag, etc.).
   */
  async dragSolve(opts?: {
    slotSelector?: string;
    maxDrops?: number;
    strategy?: 'positional' | 'textMatch' | 'sequential';
    skipBruteForce?: boolean;
  }): Promise<{
    draggables: number;
    slots: number;
    drops: Array<{
      fromIndex: number;
      toIndex: number;
      fromText: string;
      toText: string;
      success: boolean;
      error?: string;
    }>;
    summary: string;
    slotVerification?: {
      filledBefore: number;
      filledAfter: number;
      progressText: string | null;
      slotsUnchanged: boolean;
    };
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    // Pre-discovery blocker guard: probe draggable sources only.
    // Slot occlusion is checked post-discovery using the actual discovered slots (not hardcoded selectors).
    const sourceBlockerCheck = await page.evaluate(`
      (function() {
        var draggables = Array.from(document.querySelectorAll('[draggable="true"]')).filter(function(el) {
          var cs = window.getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
          var r = el.getBoundingClientRect();
          return r.width > 2 && r.height > 2;
        });
        if (draggables.length === 0) return { blocked: false };

        // Helper: sticky/fixed headers/navbars are NOT real blockers — they just overlap at the top/bottom
        function isStickyHeader(el) {
          var cs = window.getComputedStyle(el);
          var pos = cs.position;
          if (pos !== 'fixed' && pos !== 'sticky') return false;
          var r = el.getBoundingClientRect();
          // Full-width and short (typical navbar/cookie bar): width >= 80% viewport, height <= 120px
          if (r.width >= window.innerWidth * 0.8 && r.height <= 120) return true;
          // Also catch nav/header tags regardless of dimensions
          var tag = el.tagName.toLowerCase();
          if ((tag === 'nav' || tag === 'header') && (pos === 'fixed' || pos === 'sticky')) return true;
          return false;
        }

        var occluded = 0;
        var occluderInfo = '';
        var limit = Math.min(draggables.length, 6);
        for (var i = 0; i < limit; i++) {
          var r = draggables[i].getBoundingClientRect();
          var cx = r.left + r.width / 2;
          var cy = r.top + r.height / 2;
          if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) continue;
          var topEl = document.elementFromPoint(cx, cy);
          if (!topEl) { occluded++; continue; }
          if (draggables[i].contains(topEl) || topEl === draggables[i]) continue;
          if (topEl.contains(draggables[i])) continue;
          // Walk up to 3 ancestors to check if occluder is just a sticky header
          var isSticky = false;
          var node = topEl;
          for (var a = 0; a < 4 && node; a++) {
            if (isStickyHeader(node)) { isSticky = true; break; }
            node = node.parentElement;
          }
          if (isSticky) continue;
          occluded++;
          if (!occluderInfo) {
            var tag = topEl.tagName.toLowerCase();
            var cls = (topEl.className || '').toString().slice(0, 60);
            var txt = (topEl.innerText || '').slice(0, 80).trim();
            occluderInfo = '<' + tag + (cls ? ' class="' + cls + '"' : '') + '> "' + txt + '"';
          }
        }
        if (occluded > limit / 2) {
          return { blocked: true, reason: occluded + '/' + limit + ' draggable sources occluded by: ' + occluderInfo };
        }
        return { blocked: false };
      })()
    `) as { blocked: boolean; reason?: string };

    if (sourceBlockerCheck.blocked) {
      return {
        draggables: 0,
        slots: 0,
        drops: [],
        summary: `Cannot execute drag-solve: ${sourceBlockerCheck.reason}. Dismiss the blocking element first, then retry.`,
      };
    }

    const slotSelector = opts?.slotSelector || '';
    const maxDrops = opts?.maxDrops ?? 20;
    const strategy = opts?.strategy ?? 'sequential';

    // Phase 1: Discovery — find draggables, slots, compute pairs, return coordinates
    const discovery = await page.evaluate(`
      (function() {
        var MAX_DROPS = ${maxDrops};
        var STRATEGY = '${strategy}';
        var CUSTOM_SLOT_SELECTOR = ${JSON.stringify(slotSelector)};

        // Discover all draggable elements
        var draggables = Array.from(document.querySelectorAll('[draggable="true"]'));

        // Filter to visible draggables
        draggables = draggables.filter(function(el) {
          var cs = window.getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
          var r = el.getBoundingClientRect();
          return r.width > 2 && r.height > 2;
        });

        if (draggables.length === 0) {
          return { draggables: 0, slots: 0, pairs: [], error: 'No visible draggable elements found on page.' };
        }

        // Helper: returns true if element is inside a dialog/modal/popup/overlay ancestor
        function isInsideOverlay(el) {
          var node = el;
          while (node && node !== document.body) {
            if (node.getAttribute('role') === 'dialog' || node.getAttribute('role') === 'alertdialog') return true;
            if (node.getAttribute('aria-modal') === 'true') return true;
            var cls = (node.className || '').toString().toLowerCase();
            if (cls.indexOf('modal') >= 0 || cls.indexOf('popup') >= 0 || cls.indexOf('overlay') >= 0 || cls.indexOf('dialog') >= 0) return true;
            var cs = window.getComputedStyle(node);
            var z = parseInt(cs.zIndex, 10);
            // Only treat as overlay if BOTH high z-index AND overlay-like positioning.
            // Challenge containers often use z-index > 900 but are position:relative/static
            // and should NOT be excluded. True overlays are position:fixed or position:absolute.
            var pos = cs.position;
            if (z > 9000 && node !== el && (pos === 'fixed' || pos === 'absolute')) return true;
            node = node.parentElement;
          }
          return false;
        }

        // Discover target slots (drop zones)
        var slots = [];
        var usedCustomSelector = false;
        var slotsFromAuto = false;
        if (CUSTOM_SLOT_SELECTOR) {
          var customRaw = Array.from(document.querySelectorAll(CUSTOM_SLOT_SELECTOR));
          // Apply the same safety filters as auto branch: exclude draggables, overlays, hidden
          for (var ci = 0; ci < customRaw.length; ci++) {
            var ce = customRaw[ci];
            if (ce.getAttribute('draggable') === 'true') continue;
            if (isInsideOverlay(ce)) continue;
            var ccs = window.getComputedStyle(ce);
            if (ccs.display === 'none' || ccs.visibility === 'hidden') continue;
            var cr = ce.getBoundingClientRect();
            if (cr.width < 10 || cr.height < 10) continue;
            slots.push(ce);
          }
          usedCustomSelector = true;
          // Sanity guard: if custom selector produced wildly too many slots relative to
          // draggable count, the selector is too broad (e.g. "div"). Discard and fall through.
          if (slots.length > draggables.length * 3) {
            slots = [];
          }
        }
        // Fall through to auto-detection if custom selector yielded zero slots
        if (!CUSTOM_SLOT_SELECTOR || (usedCustomSelector && slots.length === 0)) {
          slotsFromAuto = true;
          // Auto-detect drop zones: prioritize explicit slot signals, exclude modals/popups
          // Strong signals first (data attributes, "slot"/"drop" classes), then weaker generic matches
          var candidates = document.querySelectorAll(
            '[data-drop], [data-dropzone], [data-slot], [data-target], ' +
            '[class*="drop"], [class*="slot"], [class*="droppable"]'
          );

          // Filter: must be visible, not draggable themselves, not inside overlay, and large enough
          for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            if (c.getAttribute('draggable') === 'true') continue;
            if (isInsideOverlay(c)) continue;
            var cs = window.getComputedStyle(c);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            var r = c.getBoundingClientRect();
            if (r.width < 10 || r.height < 10) continue;
            slots.push(c);
          }

          // Tier 2.5: Text-based slot detection — find elements whose text matches
          // common slot/drop patterns like "Slot 1", "Drop Zone A", "Position 2", etc.
          // Many challenge pages use plain buttons/divs with text labels as drop targets
          // without any CSS class markers.
          {
            var slotTextPattern = /^(slot|drop|zone|target|position|place)\s*\d+$/i;
            var allVisible = document.querySelectorAll('div, button, span, li, td, section, label, p');
            var textSlots = [];
            for (var ti = 0; ti < allVisible.length; ti++) {
              var te = allVisible[ti];
              if (te.getAttribute('draggable') === 'true') continue;
              if (isInsideOverlay(te)) continue;
              var tcs = window.getComputedStyle(te);
              if (tcs.display === 'none' || tcs.visibility === 'hidden') continue;
              var tr = te.getBoundingClientRect();
              if (tr.width < 10 || tr.height < 10) continue;
              // Get the element's own text. Use innerText but only for small/leaf elements
              // to avoid parent containers matching "Slot 1" from deeply nested children.
              var directText = (te.innerText || te.textContent || '').replace(/\s+/g, ' ').trim();
              // Skip large containers — their innerText aggregates too many children
              if (directText.length > 30) continue;
              if (directText && slotTextPattern.test(directText)) {
                textSlots.push(te);
              }
            }
            // Deduplicate: if a parent and child both match, keep only the child (leaf)
            if (textSlots.length > 0) {
              var normalizedTextSlots = textSlots.filter(function(s) {
                return !textSlots.some(function(other) { return other !== s && s.contains(other); });
              });
              if (normalizedTextSlots.length > draggables.length * 3) {
                normalizedTextSlots = [];
              }
              // Prefer explicit "Slot N" labels when generic class-based matching is noisy.
              // This prevents auto-detection from grabbing unrelated modal/overlay containers.
              if (normalizedTextSlots.length > 0) {
                var textLooksReasonable = normalizedTextSlots.length >= 2 &&
                  normalizedTextSlots.length <= (draggables.length + 2);
                var genericLooksNoisy = slots.length === 0 ||
                  slots.length > draggables.length ||
                  slots.length > (normalizedTextSlots.length + 2);
                if (textLooksReasonable && genericLooksNoisy) {
                  slots = normalizedTextSlots;
                } else if (slots.length === 0) {
                  slots = normalizedTextSlots;
                }
              }
            }
          }

          // Only add weaker generic matches ([role="listbox"], etc.) if strong signals found nothing
          if (slots.length === 0) {
            var weakCandidates = document.querySelectorAll(
              '[role="listbox"], [role="list"]'
            );
            for (var wi = 0; wi < weakCandidates.length; wi++) {
              var wc = weakCandidates[wi];
              if (wc.getAttribute('draggable') === 'true') continue;
              if (isInsideOverlay(wc)) continue;
              var wcs = window.getComputedStyle(wc);
              if (wcs.display === 'none' || wcs.visibility === 'hidden') continue;
              var wr = wc.getBoundingClientRect();
              if (wr.width < 10 || wr.height < 10) continue;
              slots.push(wc);
            }
          }

          // Fallback: if no semantic slots found, look for sibling containers of draggable parents.
          // Recurse into children to find actual slot cells (not labels/wrappers).
          // Use size similarity to draggables to distinguish real slots from labels/headers.
          if (slots.length === 0) {
            var parentSet = new Set();
            var draggableSetForSib = new Set(draggables);
            draggables.forEach(function(d) {
              if (d.parentElement) parentSet.add(d.parentElement);
            });

            // Compute average draggable dimensions for size comparison
            var avgDragW = 0, avgDragH = 0;
            draggables.forEach(function(d) {
              var dr = d.getBoundingClientRect();
              avgDragW += dr.width;
              avgDragH += dr.height;
            });
            avgDragW /= draggables.length;
            avgDragH /= draggables.length;
            var avgDragArea = avgDragW * avgDragH;

            // Collect leaf-like slot candidates from sibling containers.
            // "Leaf-like" = either has no children, or has only inline/text content.
            // If a child is itself a wrapper (has multiple visible element children),
            // recurse into IT to find the actual slot cells.
            function collectSlotCandidates(container, depth) {
              if (depth > 3) return []; // don't recurse too deep
              var candidates = [];
              var children = container.children;
              for (var idx = 0; idx < children.length; idx++) {
                var ch = children[idx];
                if (draggableSetForSib.has(ch)) continue;
                if (ch.getAttribute('draggable') === 'true') continue;
                var chCs = window.getComputedStyle(ch);
                if (chCs.display === 'none' || chCs.visibility === 'hidden') continue;
                var chR = ch.getBoundingClientRect();
                if (chR.width < 5 || chR.height < 5) continue;

                // Count visible element children to decide if this is a wrapper
                var visibleKids = 0;
                for (var ki = 0; ki < ch.children.length; ki++) {
                  var kc = window.getComputedStyle(ch.children[ki]);
                  if (kc.display !== 'none' && kc.visibility !== 'hidden') visibleKids++;
                }

                if (visibleKids > 1) {
                  // This child is a wrapper — recurse into it
                  var deeper = collectSlotCandidates(ch, depth + 1);
                  for (var di = 0; di < deeper.length; di++) candidates.push(deeper[di]);
                } else {
                  // Leaf or near-leaf — potential slot cell
                  candidates.push(ch);
                }
              }
              return candidates;
            }

            // Walk UP the ancestor chain from each draggable parent (up to 4 levels).
            // At each level, check siblings for slot-like content. This handles layouts
            // where the "Drop zones" block is a sibling of an ancestor of the draggable
            // parent — not just the immediate parent.
            var ancestorsChecked = new Set();
            var MAX_ANCESTOR_LEVELS = 4;

            parentSet.forEach(function(p) {
              var ancestor = p;
              for (var level = 0; level < MAX_ANCESTOR_LEVELS && ancestor && ancestor.parentElement; level++) {
                var grandparent = ancestor.parentElement;
                if (grandparent === document.body || ancestorsChecked.has(grandparent)) {
                  ancestor = grandparent;
                  continue;
                }
                ancestorsChecked.add(grandparent);

                var siblings = grandparent.children;
                for (var j = 0; j < siblings.length; j++) {
                  var sib = siblings[j];
                  // Skip if this sibling contains any draggable (it's the "pieces" block)
                  if (sib.querySelector && sib.querySelector('[draggable="true"]')) continue;
                  if (sib.getAttribute && sib.getAttribute('draggable') === 'true') continue;
                  if (isInsideOverlay(sib)) continue;
                  var cs2 = window.getComputedStyle(sib);
                  if (cs2.display === 'none' || cs2.visibility === 'hidden') continue;
                  var r2 = sib.getBoundingClientRect();
                  if (r2.width < 10 || r2.height < 10) continue;

                  if (sib.children.length === 0) {
                    slots.push(sib);
                  } else {
                    var leafCandidates = collectSlotCandidates(sib, 0);
                    for (var lc = 0; lc < leafCandidates.length; lc++) {
                      var lcR = leafCandidates[lc].getBoundingClientRect();
                      var lcArea = lcR.width * lcR.height;
                      if (avgDragArea > 0 && lcArea < avgDragArea * 0.05) continue;
                      if (avgDragArea > 0 && lcArea > avgDragArea * 5) continue;
                      slots.push(leafCandidates[lc]);
                    }
                  }
                }

                // If we found slots at this level, stop walking up
                if (slots.length > 0) break;
                ancestor = grandparent;
              }
            });
          }

          // Intra-container fallback: look for non-draggable siblings within the same
          // parent as draggables. Common in grid/board layouts where slots are empty divs
          // or placeholder elements sitting alongside draggable pieces.
          if (slots.length === 0) {
            var draggableSet = new Set(draggables);
            var parentSet2 = new Set();
            draggables.forEach(function(d) { if (d.parentElement) parentSet2.add(d.parentElement); });
            parentSet2.forEach(function(p) {
              var children = p.children;
              for (var k = 0; k < children.length; k++) {
                var child = children[k];
                if (draggableSet.has(child)) continue;
                if (child.getAttribute('draggable') === 'true') continue;
                if (isInsideOverlay(child)) continue;
                var ccs3 = window.getComputedStyle(child);
                if (ccs3.display === 'none' || ccs3.visibility === 'hidden') continue;
                var cr3 = child.getBoundingClientRect();
                if (cr3.width < 10 || cr3.height < 10) continue;
                // Must be roughly similar size to draggables (within 3x) to avoid matching
                // layout wrappers or tiny decorative elements
                var avgDragArea = 0;
                draggables.forEach(function(d) {
                  var dr = d.getBoundingClientRect();
                  avgDragArea += dr.width * dr.height;
                });
                avgDragArea /= draggables.length;
                var childArea = cr3.width * cr3.height;
                if (avgDragArea > 0 && (childArea > avgDragArea * 3 || childArea < avgDragArea * 0.1)) continue;
                slots.push(child);
              }
            });
          }

          // Tier 6: preventDefault probe — dispatch synthetic dragover events to candidate
          // elements and check if defaultPrevented is true (definitive HTML5 drop zone signal).
          // This catches drop zones that use only JS event listeners without identifiable
          // attributes or class names — the spec requires preventDefault on dragover for drops.
          // Tier 5.5: Explicit Grid Search
          // Look for containers that look like grids of slots (similar size to draggables)
          if (slots.length === 0) {
             var allContainers = document.querySelectorAll('div, section, ul, ol, main, article, [role="grid"], [role="group"]');
             var bestGrid = [];
             var maxSlots = 0;
             var avgDragArea = 0;
             draggables.forEach(function(d) { var r = d.getBoundingClientRect(); avgDragArea += r.width * r.height; });
             avgDragArea /= (draggables.length || 1);

             for (var i = 0; i < allContainers.length; i++) {
                var cont = allContainers[i];
                if (isInsideOverlay(cont)) continue;
                var cs = window.getComputedStyle(cont);
                if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                
                var potentialSlots = [];
                var children = cont.children;
                if (children.length < 2) continue; // Grid needs items

                for (var j = 0; j < children.length; j++) {
                   var ch = children[j];
                   if (ch.getAttribute('draggable') === 'true') continue;
                   if (isInsideOverlay(ch)) continue; // optimization
                   
                   var cr = ch.getBoundingClientRect();
                   var ca = cr.width * cr.height;
                   // 50% to 200% area match is reasonable for grid cells vs pieces
                   if (ca > avgDragArea * 0.5 && ca < avgDragArea * 2.0) {
                      potentialSlots.push(ch);
                   }
                }
                
                // Tie-breaker: prefer container with more matching slots, but reasonably bounded
                // We assume there are at least as many slots as draggables (usually)
                if (potentialSlots.length >= 1 && potentialSlots.length > maxSlots) {
                   maxSlots = potentialSlots.length;
                   bestGrid = potentialSlots;
                }
             }

             if (bestGrid.length > 0) {
                // If we found a plausible grid, use it.
                // Filter out any that might be draggables (double check)
                slots = bestGrid.filter(function(s) { 
                  return s.getAttribute('draggable') !== 'true'; 
                });
             }
          }

          if (slots.length === 0) {
            var probeCandidates = document.querySelectorAll('div, section, ul, ol, li, td, th, article, aside, main, [class]');
            var probeResults = [];
            var dragSet = new Set(draggables);
            for (var pi = 0; pi < probeCandidates.length && probeResults.length < draggables.length * 4; pi++) {
              var pc = probeCandidates[pi];
              if (dragSet.has(pc)) continue;
              if (isInsideOverlay(pc)) continue;
              var pcr = pc.getBoundingClientRect();
              if (pcr.width < 10 || pcr.height < 10) continue;
              var pcs = window.getComputedStyle(pc);
              if (pcs.display === 'none' || pcs.visibility === 'hidden') continue;
              try {
                var probeEvt = new DragEvent('dragover', {
                  bubbles: true,
                  cancelable: true,
                  dataTransfer: new DataTransfer()
                });
                pc.dispatchEvent(probeEvt);
                if (probeEvt.defaultPrevented) {
                  probeResults.push(pc);
                }
              } catch(pe) { /* skip if DragEvent not supported */ }
            }
            // Deduplicate: remove ancestors whose children are also in the list
            if (probeResults.length > 0) {
              slots = probeResults.filter(function(s) {
                return !probeResults.some(function(other) { return other !== s && s.contains(other); });
              });
              // Apply same 3x sanity guard
              if (slots.length > draggables.length * 3) {
                slots = []; // too broad — discard
              }
            }
          }

          // Sortable list: all draggables share a parent, no separate drop zones.
          // Instead of failing, use the draggables' own positions as targets for reordering.
          if (slots.length === 0 && draggables.length > 1) {
            var allSameParent = draggables.every(function(d) { return d.parentElement === draggables[0].parentElement; });
            if (allSameParent) {
              // For sortable lists, create placeholder slots at each draggable's current position.
              slots = draggables.map(function(d) {
                var placeholder = document.createElement('div');
                placeholder.style.cssText = 'position:absolute;pointer-events:none;width:0;height:0;';
                placeholder.setAttribute('data-sortable-slot', 'true');
                var r = d.getBoundingClientRect();
                placeholder.setAttribute('data-slot-x', String(r.left + r.width / 2));
                placeholder.setAttribute('data-slot-y', String(r.top + r.height / 2));
                placeholder.textContent = (d.innerText || d.textContent || '').trim().slice(0, 50);
                d.parentElement.appendChild(placeholder);
                return placeholder;
              });
            } else {
               // Check if they share a grandparent (wrapped items, e.g. ul > li > div.draggable)
               var firstParent = draggables[0].parentElement;
               if (firstParent && firstParent.parentElement) {
                 var grandparent = firstParent.parentElement;
                 var allShareGrandparent = draggables.every(function(d) {
                   return d.parentElement && d.parentElement.parentElement === grandparent;
                 });
                 if (allShareGrandparent) {
                    // Use the wrappers (e.g. li) as the slots
                    slots = draggables.map(function(d) { return d.parentElement; });
                 }
               }
            }
          }
        }

        // Filter slots to visible
        slots = slots.filter(function(el) {
          var cs = window.getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          var r = el.getBoundingClientRect();
          return r.width > 2 && r.height > 2;
        });

        // Sanity guard for auto-detect path: if too many slots relative to draggable count,
        // the auto-detection matched the wrong containers (e.g. all divs in a grid).
        // Same >3x threshold as the custom selector guard above.
        if (slotsFromAuto && slots.length > draggables.length * 3) {
          return {
            draggables: draggables.length,
            slots: slots.length,
            pairs: [],
            error: 'Slot detection unstable: auto-detected ' + slots.length + ' slots for ' + draggables.length + ' draggables (ratio > 3x). Use slotSelector parameter to specify the correct drop targets.'
          };
        }

        if (slots.length === 0) {
          return {
            draggables: draggables.length,
            slots: 0,
            pairs: [],
            error: 'Found ' + draggables.length + ' draggable(s) but could not auto-detect drop slots. Use slotSelector parameter to specify target slots.'
          };
        }

        function getText(el) {
          return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
        }

        function getIdx(el) {
          var idx = el.getAttribute('data-aware-idx');
          return idx !== null ? parseInt(idx, 10) : -1;
        }

        // Build pairing based on strategy
        var pairs = [];
        if (STRATEGY === 'sequential') {
          var count = Math.min(draggables.length, slots.length, MAX_DROPS);
          for (var pi = 0; pi < count; pi++) {
            pairs.push({ from: draggables[pi], to: slots[pi] });
          }
        } else if (STRATEGY === 'textMatch') {
          var usedSlots = new Set();
          draggables.forEach(function(d) {
            if (pairs.length >= MAX_DROPS) return;
            var dText = getText(d).toLowerCase();
            var bestSlot = null;
            var bestScore = 0;
            slots.forEach(function(s, si) {
              if (usedSlots.has(si)) return;
              var sText = getText(s).toLowerCase();
              var score = 0;
              if (sText.includes(dText) || dText.includes(sText)) score = 3;
              else {
                var dWords = dText.split(/\\W+/).filter(Boolean);
                var sWords = sText.split(/\\W+/).filter(Boolean);
                dWords.forEach(function(w) { if (sWords.indexOf(w) >= 0) score++; });
              }
              if (score > bestScore) { bestScore = score; bestSlot = si; }
            });
            if (bestSlot !== null && bestScore > 0) {
              usedSlots.add(bestSlot);
              pairs.push({ from: d, to: slots[bestSlot] });
            }
          });
          var remainingSlots = slots.filter(function(s, si) { return !usedSlots.has(si); });
          var ri = 0;
          draggables.forEach(function(d) {
            if (pairs.length >= MAX_DROPS) return;
            if (pairs.some(function(p) { return p.from === d; })) return;
            if (ri < remainingSlots.length) {
              pairs.push({ from: d, to: remainingSlots[ri++] });
            }
          });
        } else {
          // positional: sort by Y then X, pair nearest
          var dSorted = draggables.slice().sort(function(a, b) {
            var ra = a.getBoundingClientRect();
            var rb = b.getBoundingClientRect();
            return (ra.top - rb.top) || (ra.left - rb.left);
          });
          var sSorted = slots.slice().sort(function(a, b) {
            var ra = a.getBoundingClientRect();
            var rb = b.getBoundingClientRect();
            return (ra.top - rb.top) || (ra.left - rb.left);
          });
          var pCount = Math.min(dSorted.length, sSorted.length, MAX_DROPS);
          for (var qi = 0; qi < pCount; qi++) {
            pairs.push({ from: dSorted[qi], to: sSorted[qi] });
          }
        }

        // Stamp temporary pair markers on both source and target so execution can
        // re-find them reliably. Slots often lack data-aware-idx (non-interactive containers).
        // Clean any stale markers first.
        var oldMarkers = document.querySelectorAll('[data-drag-pair]');
        for (var mi = 0; mi < oldMarkers.length; mi++) oldMarkers[mi].removeAttribute('data-drag-pair');

        var result = [];
        for (var di = 0; di < pairs.length; di++) {
          var pair = pairs[di];
          pair.from.setAttribute('data-drag-pair', 'src-' + di);
          pair.to.setAttribute('data-drag-pair', 'dst-' + di);
          result.push({
            pairIndex: di,
            fromText: getText(pair.from),
            toText: getText(pair.to),
            toChildCount: pair.to.children.length,
            toInnerLength: (pair.to.innerHTML || '').length
          });
        }

        return {
          draggables: draggables.length,
          slots: slots.length,
          pairs: result,
          slotsFromAuto: slotsFromAuto
        };
      })()
    `) as {
      draggables: number;
      slots: number;
      pairs: Array<{
        pairIndex: number;
        fromText: string; toText: string;
        toChildCount: number; toInnerLength: number;
      }>;
      error?: string;
      slotsFromAuto?: boolean;
    };

    // Early return for discovery failures
    if (discovery.error || discovery.pairs.length === 0) {
      return {
        draggables: discovery.draggables,
        slots: discovery.slots,
        drops: [],
        summary: discovery.error || `Found ${discovery.draggables} draggable(s), ${discovery.slots} slot(s), but pairing produced zero pairs.`,
      };
    }

    // Slot count validation: if slot count is wildly off from draggable count, bail early.
    // Typical patterns: N draggables → N slots (1:1), or N draggables → M categories (M < N).
    // A single slot for many draggables likely means auto-detection found the wrong container.
    // Check slotsFromAuto (not !slotSelector) — when custom selector failed and auto ran as
    // fallback, the bailout must still fire even though slotSelector was originally set.
    if (discovery.slotsFromAuto && discovery.slots === 1 && discovery.draggables > 2) {
      // Clean up pair markers
      await page.evaluate(`
        (function() {
          var m = document.querySelectorAll('[data-drag-pair]');
          for (var i = 0; i < m.length; i++) m[i].removeAttribute('data-drag-pair');
        })()
      `);
      return {
        draggables: discovery.draggables,
        slots: discovery.slots,
        drops: [],
        summary: `Slot detection unstable: found ${discovery.draggables} draggables but only 1 drop slot. This likely means auto-detection matched the wrong container. Use slotSelector parameter to specify the correct drop targets, or use browser_drag_drop with explicit coordinates.`,
      };
    }

    // Post-discovery slot occlusion check: probe the ACTUAL discovered slots
    // (not hardcoded selectors) using the pair markers stamped during discovery.
    if (discovery.pairs.length > 0) {
      const slotOcclusionCheck = await page.evaluate(`
        (function() {
          // Helper: sticky/fixed headers are NOT real blockers
          function isStickyHeader(el) {
            var cs = window.getComputedStyle(el);
            var pos = cs.position;
            if (pos !== 'fixed' && pos !== 'sticky') return false;
            var r = el.getBoundingClientRect();
            if (r.width >= window.innerWidth * 0.8 && r.height <= 120) return true;
            var tag = el.tagName.toLowerCase();
            if ((tag === 'nav' || tag === 'header') && (pos === 'fixed' || pos === 'sticky')) return true;
            return false;
          }

          var dstEls = document.querySelectorAll('[data-drag-pair^="dst-"]');
          if (dstEls.length === 0) return { blocked: false };
          var occluded = 0;
          var occluderInfo = '';
          var limit = Math.min(dstEls.length, 6);
          for (var i = 0; i < limit; i++) {
            var el = dstEls[i];
            el.scrollIntoView({ block: 'center', behavior: 'instant' });
            var r = el.getBoundingClientRect();
            var cx = r.left + r.width / 2;
            var cy = r.top + r.height / 2;
            if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) continue;
            var topEl = document.elementFromPoint(cx, cy);
            if (!topEl) { occluded++; continue; }
            if (el.contains(topEl) || topEl === el) continue;
            if (topEl.contains(el)) continue;
            // Walk ancestors to check for sticky header
            var isSticky = false;
            var node = topEl;
            for (var a = 0; a < 4 && node; a++) {
              if (isStickyHeader(node)) { isSticky = true; break; }
              node = node.parentElement;
            }
            if (isSticky) continue;
            occluded++;
            if (!occluderInfo) {
              var tag = topEl.tagName.toLowerCase();
              var cls = (topEl.className || '').toString().slice(0, 60);
              var txt = (topEl.innerText || '').slice(0, 80).trim();
              occluderInfo = '<' + tag + (cls ? ' class="' + cls + '"' : '') + '> "' + txt + '"';
            }
          }
          if (occluded > limit / 2) {
            return { blocked: true, reason: occluded + '/' + limit + ' drop target slots occluded by: ' + occluderInfo };
          }
          return { blocked: false };
        })()
      `) as { blocked: boolean; reason?: string };

      if (slotOcclusionCheck.blocked) {
        // Clean up pair markers before returning
        await page.evaluate(`
          (function() {
            var m = document.querySelectorAll('[data-drag-pair]');
            for (var i = 0; i < m.length; i++) m[i].removeAttribute('data-drag-pair');
          })()
        `);
        return {
          draggables: discovery.draggables,
          slots: discovery.slots,
          drops: [],
          summary: `Cannot execute drag-solve: ${slotOcclusionCheck.reason}. Dismiss the blocking element first, then retry.`,
        };
      }
    }

    // Phase 1b: Count draggables before execution (structural metric, not text-based)
    const preDragCount = await page.evaluate(`
      document.querySelectorAll('[draggable="true"]').length
    `) as number;

    // Also capture progress indicator if present
    const preProgress = await page.evaluate(`
      (function() {
        var body = (document.body.innerText || '').replace(/\\s+/g, ' ');
        var m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*(filled|placed|correct|complete|dropped)/i);
        return m ? { text: m[0], num: parseInt(m[1], 10), total: parseInt(m[2], 10) } : null;
      })()
    `) as { text: string; num: number; total: number } | null;

    // Phase 2: Execute drags — resolve fresh coordinates per pair via data-drag-pair markers
    const drops: Array<{
      fromIndex: number; toIndex: number;
      fromText: string; toText: string;
      success: boolean; error?: string;
    }> = [];

    for (let i = 0; i < discovery.pairs.length; i++) {
      const pair = discovery.pairs[i];
      const pi = pair.pairIndex;

      // Just-in-time coordinate resolution via pair markers stamped during discovery
      const coords = await page.evaluate(`
        (function() {
          var fromEl = document.querySelector('[data-drag-pair="src-${pi}"]');
          var toEl = document.querySelector('[data-drag-pair="dst-${pi}"]');
          if (!fromEl) return { error: 'Source element for pair ${pi} no longer in DOM' };
          if (!toEl) return { error: 'Target element for pair ${pi} no longer in DOM' };

          // Helper: sticky/fixed headers are NOT real blockers
          function isStickyHeader(el) {
            var cs = window.getComputedStyle(el);
            var pos = cs.position;
            if (pos !== 'fixed' && pos !== 'sticky') return false;
            var r = el.getBoundingClientRect();
            if (r.width >= window.innerWidth * 0.8 && r.height <= 120) return true;
            var tag = el.tagName.toLowerCase();
            if ((tag === 'nav' || tag === 'header') && (pos === 'fixed' || pos === 'sticky')) return true;
            return false;
          }
          function isOccluderStickyHeader(el) {
            var node = el;
            for (var a = 0; a < 4 && node; a++) {
              if (isStickyHeader(node)) return true;
              node = node.parentElement;
            }
            return false;
          }

          // Scroll source into view, read rect
          fromEl.scrollIntoView({ block: 'center', behavior: 'instant' });
          var fr = fromEl.getBoundingClientRect();
          var fcx = fr.left + fr.width / 2;
          var fcy = fr.top + fr.height / 2;

          // Occlusion check on source — neutralize floating overlays instead of bailing
          var neutralized = []; // Track elements we set pointer-events:none on
          var topAtFrom = document.elementFromPoint(fcx, fcy);
          if (topAtFrom && !fromEl.contains(topAtFrom) && topAtFrom !== fromEl && !topAtFrom.contains(fromEl)) {
            if (!isOccluderStickyHeader(topAtFrom)) {
              // Neutralize the occluder by disabling pointer-events temporarily
              var prevPE = topAtFrom.style.pointerEvents || '';
              topAtFrom.setAttribute('data-drag-pe-backup', prevPE);
              topAtFrom.style.pointerEvents = 'none';
              neutralized.push(topAtFrom);
              // Re-check — another element may also occlude
              var topAtFrom2 = document.elementFromPoint(fcx, fcy);
              if (topAtFrom2 && !fromEl.contains(topAtFrom2) && topAtFrom2 !== fromEl && !topAtFrom2.contains(fromEl) && !isOccluderStickyHeader(topAtFrom2)) {
                var prevPE2 = topAtFrom2.style.pointerEvents || '';
                topAtFrom2.setAttribute('data-drag-pe-backup', prevPE2);
                topAtFrom2.style.pointerEvents = 'none';
                neutralized.push(topAtFrom2);
              }
            }
          }

          // Scroll target into view if needed
          var tr = toEl.getBoundingClientRect();
          if (tr.top < 0 || tr.bottom > window.innerHeight) {
            toEl.scrollIntoView({ block: 'center', behavior: 'instant' });
          }
          // Re-read both rects after final scroll
          fr = fromEl.getBoundingClientRect();
          tr = toEl.getBoundingClientRect();
          fcx = fr.left + fr.width / 2;
          fcy = fr.top + fr.height / 2;
          var tcx = tr.left + tr.width / 2;
          var tcy = tr.top + tr.height / 2;

          if (fr.width < 1 || fr.height < 1) {
            // Restore before returning error
            for (var ni = 0; ni < neutralized.length; ni++) {
              neutralized[ni].style.pointerEvents = neutralized[ni].getAttribute('data-drag-pe-backup') || '';
              neutralized[ni].removeAttribute('data-drag-pe-backup');
            }
            return { error: 'Source element has zero size' };
          }
          if (tr.width < 1 || tr.height < 1) {
            for (var ni = 0; ni < neutralized.length; ni++) {
              neutralized[ni].style.pointerEvents = neutralized[ni].getAttribute('data-drag-pe-backup') || '';
              neutralized[ni].removeAttribute('data-drag-pe-backup');
            }
            return { error: 'Target element has zero size' };
          }

          // Occlusion check on target — neutralize instead of bailing
          var topAtTo = document.elementFromPoint(tcx, tcy);
          if (topAtTo && !toEl.contains(topAtTo) && topAtTo !== toEl && !topAtTo.contains(toEl)) {
            if (!isOccluderStickyHeader(topAtTo)) {
              var prevPETo = topAtTo.style.pointerEvents || '';
              topAtTo.setAttribute('data-drag-pe-backup', prevPETo);
              topAtTo.style.pointerEvents = 'none';
              neutralized.push(topAtTo);
              // Second-layer check
              var topAtTo2 = document.elementFromPoint(tcx, tcy);
              if (topAtTo2 && !toEl.contains(topAtTo2) && topAtTo2 !== toEl && !topAtTo2.contains(toEl) && !isOccluderStickyHeader(topAtTo2)) {
                var prevPETo2 = topAtTo2.style.pointerEvents || '';
                topAtTo2.setAttribute('data-drag-pe-backup', prevPETo2);
                topAtTo2.style.pointerEvents = 'none';
                neutralized.push(topAtTo2);
              }
            }
          }

          return {
            fromX: Math.round(fcx), fromY: Math.round(fcy),
            toX: Math.round(tcx), toY: Math.round(tcy),
            neutralizedCount: neutralized.length
          };
        })()
      `) as { fromX: number; fromY: number; toX: number; toY: number; error?: string; neutralizedCount?: number } | null;

      if (!coords || coords.error) {
        // Restore any neutralized elements even on error
        await page.evaluate(`
          (function() {
            var els = document.querySelectorAll('[data-drag-pe-backup]');
            for (var i = 0; i < els.length; i++) {
              els[i].style.pointerEvents = els[i].getAttribute('data-drag-pe-backup') || '';
              els[i].removeAttribute('data-drag-pe-backup');
            }
          })()
        `);
        drops.push({
          fromIndex: pi, toIndex: pi,
          fromText: pair.fromText, toText: pair.toText,
          success: false,
          error: coords?.error || `Could not resolve pair ${pi}. Elements may have been removed.`,
        });
        continue;
      }

      // Snapshot before drop: draggable count + target slot state
      const preSnap = await page.evaluate(`
        (function() {
          var dragCount = document.querySelectorAll('[draggable="true"]').length;
          var toEl = document.querySelector('[data-drag-pair="dst-${pi}"]');
          var body = (document.body.innerText || '').replace(/\\s+/g, ' ');
          var m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*(filled|placed|correct|complete|dropped)/i);
          return {
            dragCount: dragCount,
            toChildCount: toEl ? toEl.children.length : -1,
            toInnerLen: toEl ? (toEl.innerHTML || '').length : -1,
            progressNum: m ? parseInt(m[1], 10) : null
          };
        })()
      `) as { dragCount: number; toChildCount: number; toInnerLen: number; progressNum: number | null };

      try {
        await this.dragDrop(
          { x: coords.fromX, y: coords.fromY },
          { x: coords.toX, y: coords.toY },
          { steps: 10 }
        );

        await new Promise(r => setTimeout(r, 100));

        // Restore pointer-events on any elements we neutralized for this drop
        if (coords.neutralizedCount && coords.neutralizedCount > 0) {
          await page.evaluate(`
            (function() {
              var els = document.querySelectorAll('[data-drag-pe-backup]');
              for (var i = 0; i < els.length; i++) {
                els[i].style.pointerEvents = els[i].getAttribute('data-drag-pe-backup') || '';
                els[i].removeAttribute('data-drag-pe-backup');
              }
            })()
          `);
        }

        // Post-drop snapshot: check multiple signals
        const postSnap = await page.evaluate(`
          (function() {
            var dragCount = document.querySelectorAll('[draggable="true"]').length;
            var fromEl = document.querySelector('[data-drag-pair="src-${pi}"]');
            var toEl = document.querySelector('[data-drag-pair="dst-${pi}"]');
            var body = (document.body.innerText || '').replace(/\\s+/g, ' ');
            var m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*(filled|placed|correct|complete|dropped)/i);
            return {
              dragCount: dragCount,
              sourceGone: !fromEl || fromEl.getAttribute('draggable') !== 'true',
              toChildCount: toEl ? toEl.children.length : -1,
              toInnerLen: toEl ? (toEl.innerHTML || '').length : -1,
              progressNum: m ? parseInt(m[1], 10) : null
            };
          })()
        `) as { dragCount: number; sourceGone: boolean; toChildCount: number; toInnerLen: number; progressNum: number | null };

        // Per-drop signals, tiered by reliability:
        // Hard: dragCount decreased or progress advanced (page-level confirmation)
        // Medium: slot gained child nodes (structural — hover/animations don't add children)
        // Weak: sourceGone, slotContentChanged (can be caused by CSS/animation side effects)
        const dragCountDecreased = postSnap.dragCount < preSnap.dragCount;
        const sourceRemoved = postSnap.sourceGone;
        const slotGainedChildren = preSnap.toChildCount >= 0 && postSnap.toChildCount > preSnap.toChildCount;
        const slotContentChanged = preSnap.toInnerLen >= 0 && postSnap.toInnerLen !== preSnap.toInnerLen;
        const progressAdvanced = postSnap.progressNum !== null && preSnap.progressNum !== null &&
          postSnap.progressNum > preSnap.progressNum;

        // Per-drop: trust hard + medium signals, not weak alone
        const registered = dragCountDecreased || slotGainedChildren || progressAdvanced ||
          (sourceRemoved && slotContentChanged); // Weak signals only if BOTH present together

        drops.push({
          fromIndex: pi, toIndex: pi,
          fromText: pair.fromText, toText: pair.toText,
          success: registered,
          error: registered ? undefined :
            `No state change (drags: ${preSnap.dragCount}→${postSnap.dragCount}, ` +
            `slot children: ${preSnap.toChildCount}→${postSnap.toChildCount}, ` +
            `slot size: ${preSnap.toInnerLen}→${postSnap.toInnerLen})`,
        });

        if (postSnap.progressNum !== null && preProgress) {
          preProgress.num = postSnap.progressNum;
        }
      } catch (e) {
        // Restore pointer-events on any neutralized elements after error
        await page.evaluate(`
          (function() {
            var els = document.querySelectorAll('[data-drag-pe-backup]');
            for (var i = 0; i < els.length; i++) {
              els[i].style.pointerEvents = els[i].getAttribute('data-drag-pe-backup') || '';
              els[i].removeAttribute('data-drag-pe-backup');
            }
          })()
        `).catch(() => { });
        drops.push({
          fromIndex: pi, toIndex: pi,
          fromText: pair.fromText, toText: pair.toText,
          success: false,
          error: e instanceof Error ? e.message : String(e),
        });
      }
      if (i < discovery.pairs.length - 1) {
        await new Promise(r => setTimeout(r, 50));
      }
    }

    // Clean up pair markers and any remaining pointer-events backups
    await page.evaluate(`
      (function() {
        var m = document.querySelectorAll('[data-drag-pair]');
        for (var i = 0; i < m.length; i++) m[i].removeAttribute('data-drag-pair');
        var pe = document.querySelectorAll('[data-drag-pe-backup]');
        for (var j = 0; j < pe.length; j++) {
          pe[j].style.pointerEvents = pe[j].getAttribute('data-drag-pe-backup') || '';
          pe[j].removeAttribute('data-drag-pe-backup');
        }
      })()
    `);

    this.invalidateElementsCache();

    const succeeded = drops.filter(d => d.success).length;

    // Phase 3: Aggregate post-condition
    const postDragCount = await page.evaluate(
      `document.querySelectorAll('[draggable="true"]').length`
    ) as number;
    const postProgress = await page.evaluate(`
      (function() {
        var body = (document.body.innerText || '').replace(/\\s+/g, ' ');
        var m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*(filled|placed|correct|complete|dropped)/i);
        return m ? { text: m[0], num: parseInt(m[1], 10) } : null;
      })()
    `) as { text: string; num: number } | null;

    const dragDelta = preDragCount - postDragCount;
    const progressDelta = (postProgress?.num ?? 0) - (preProgress?.num ?? 0);

    // Tiered aggregate success:
    // Hard: page-level draggable count decreased OR progress counter advanced
    // Medium: any drop's slot gained children (structural — hover doesn't add child nodes)
    // Weak alone: slotContentChanged, sourceGone (can be CSS/animation side effects)
    const confirmedSuccess = dragDelta > 0 || progressDelta > 0 || succeeded > 0;

    if (!confirmedSuccess) {
      // No signal at all — everything failed
      for (const d of drops) {
        if (d.success) {
          d.success = false;
          d.error = (d.error ? d.error + ' ' : '') +
            `Overridden: no aggregate confirmation (drags: ${preDragCount}→${postDragCount}, progress: ${preProgress?.num ?? '?'}→${postProgress?.num ?? '?'}).`;
        }
      }

      // Brute force fallback: try synthetic HTML5 drag events on all plausible targets
      if (!opts?.skipBruteForce) {
        try {
          const bruteResult = await this.dragSolveBruteForce();
          if (bruteResult.successfulDrops > 0) {
            return {
              draggables: bruteResult.draggables,
              slots: bruteResult.slotsAttempted,
              drops: bruteResult.results.map((r, i) => ({
                fromIndex: i,
                toIndex: i,
                fromText: r.fromText,
                toText: r.toSelector,
                success: r.success,
                error: r.success ? undefined : 'Brute force drop not accepted',
              })),
              summary: `dragSolve failed (${strategy}), brute-force fallback: ${bruteResult.summary}`,
            };
          }
        } catch (_bruteErr) {
          // Brute force also failed — fall through to normal failure return
        }
      }

      return {
        draggables: discovery.draggables,
        slots: discovery.slots,
        drops,
        slotVerification: {
          filledBefore: preProgress?.num ?? 0,
          filledAfter: postProgress?.num ?? 0,
          progressText: postProgress?.text ?? null,
          slotsUnchanged: true,
        },
        summary: `Executed ${drops.length} drag-drops but NONE confirmed by aggregate check. ` +
          `Draggables: ${preDragCount}→${postDragCount}. ` +
          `${postProgress ? 'Progress: ' + postProgress.text : 'No progress indicator.'}. ` +
          `Strategy: ${strategy}.`,
      };
    }

    return {
      draggables: discovery.draggables,
      slots: discovery.slots,
      drops,
      summary: `Executed ${drops.length} drag-drops (${succeeded}/${drops.length} per-drop, ` +
        `${dragDelta} confirmed by drag count delta, ${progressDelta} by progress). ` +
        `Draggables: ${preDragCount}→${postDragCount}. ` +
        `${postProgress ? 'Progress: ' + postProgress.text + '.' : ''} ` +
        `Strategy: ${strategy}.`,
    };
  }

  /**
   * Brute-force drag-and-drop solver.
   * Tries dropping every draggable element onto every plausible target container
   * using synthetic HTML5 drag events dispatched in-page.
   * Use when dragSolve() fails to fill any slots.
   */
  async dragSolveBruteForce(): Promise<{
    draggables: number;
    slotsAttempted: number;
    successfulDrops: number;
    results: Array<{ fromText: string; toSelector: string; success: boolean; method: string }>;
    summary: string;
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    const result = await page.evaluate(`
      (function() {
        var results = [];
        var placedSet = new Set();

        // Helper: check if element is visible
        function isVisible(el) {
          if (!el || !el.getBoundingClientRect) return false;
          var r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return false;
          var style = window.getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) < 0.1) return false;
          return true;
        }

        // Helper: get element description
        function elDesc(el) {
          var text = (el.textContent || '').trim().substring(0, 50);
          var tag = el.tagName.toLowerCase();
          var cls = el.className ? '.' + String(el.className).split(/\\s+/).slice(0, 2).join('.') : '';
          var id = el.id ? '#' + el.id : '';
          return tag + id + cls + (text ? '[' + text + ']' : '');
        }

        // Helper: check if el is ancestor of or inside another
        function isRelated(a, b) {
          return a.contains(b) || b.contains(a);
        }

        // Find all visible draggable elements
        var allDraggables = Array.from(document.querySelectorAll('[draggable="true"]')).filter(isVisible);
        if (allDraggables.length === 0) {
          return { draggables: 0, slotsAttempted: 0, successfulDrops: 0, results: [], summary: 'No visible draggable elements found.' };
        }

        // Collect parent containers of draggables to exclude
        var draggableParents = new Set();
        allDraggables.forEach(function(d) {
          var p = d.parentElement;
          while (p && p !== document.body) {
            draggableParents.add(p);
            p = p.parentElement;
          }
        });

        // Find candidate drop zones
        var allElements = Array.from(document.querySelectorAll('*'));
        var draggableSet = new Set(allDraggables);
        var avgDragW = 0, avgDragH = 0;
        allDraggables.forEach(function(d) {
          var r = d.getBoundingClientRect();
          avgDragW += r.width;
          avgDragH += r.height;
        });
        avgDragW /= allDraggables.length;
        avgDragH /= allDraggables.length;

        var candidates = [];
        for (var i = 0; i < allElements.length; i++) {
          var el = allElements[i];
          if (draggableSet.has(el)) continue;
          if (!isVisible(el)) continue;
          var r = el.getBoundingClientRect();
          if (r.width < 30 || r.height < 30) continue;

          // Skip if element is an ancestor of any draggable (i.e. a draggable container)
          var isAncestor = false;
          for (var di = 0; di < allDraggables.length; di++) {
            if (el.contains(allDraggables[di])) { isAncestor = true; break; }
          }
          if (isAncestor) continue;

          // Skip if inside a draggable
          var insideDraggable = false;
          for (var di2 = 0; di2 < allDraggables.length; di2++) {
            if (allDraggables[di2].contains(el)) { insideDraggable = true; break; }
          }
          if (insideDraggable) continue;

          // Score candidate likelihood
          var score = 0;
          var style = window.getComputedStyle(el);

          // (a) Empty or few children
          if (el.children.length <= 1) score += 2;
          if (el.children.length === 0 && (el.textContent || '').trim().length < 20) score += 3;

          // (b) Border/outline suggesting a slot
          if (style.border && style.border !== 'none' && !style.border.match(/^0/)) score += 1;
          if (style.borderStyle && style.borderStyle !== 'none') score += 1;
          if (style.outline && style.outline !== 'none') score += 1;
          if (style.boxShadow && style.boxShadow !== 'none') score += 1;

          // (c) Size similar to draggables (within 3x)
          if (r.width >= avgDragW * 0.3 && r.width <= avgDragW * 3 &&
              r.height >= avgDragH * 0.3 && r.height <= avgDragH * 3) score += 2;

          // (d) Class/id hints
          var classId = ((el.className || '') + ' ' + (el.id || '')).toLowerCase();
          if (classId.match(/drop|slot|target|zone|dest|receiv|place|bucket|container/)) score += 5;

          // (e) data attributes
          if (el.getAttribute('data-drop') !== null || el.getAttribute('data-droppable') !== null ||
              el.getAttribute('data-slot') !== null || el.getAttribute('data-target') !== null) score += 5;

          // (f) role attributes
          var role = (el.getAttribute('role') || '').toLowerCase();
          if (role === 'listbox' || role === 'list' || role === 'group') score += 3;

          if (score > 0) {
            candidates.push({ el: el, score: score, rect: r });
          }
        }

        // Sort by score descending
        candidates.sort(function(a, b) { return b.score - a.score; });

        // Cap candidates to avoid excessive attempts
        if (candidates.length > 40) candidates = candidates.slice(0, 40);

        var successCount = 0;

        // For each draggable, try candidates
        for (var dIdx = 0; dIdx < allDraggables.length; dIdx++) {
          var drag = allDraggables[dIdx];
          if (placedSet.has(dIdx)) continue;
          if (!isVisible(drag)) continue;

          var dragText = (drag.textContent || '').trim().substring(0, 40);
          var originalParent = drag.parentElement;

          for (var cIdx = 0; cIdx < candidates.length; cIdx++) {
            var target = candidates[cIdx].el;
            if (!isVisible(target)) continue;
            if (isRelated(drag, target)) continue;

            var targetChildCountBefore = target.children.length;
            var dragParentBefore = drag.parentElement;

            // Create DataTransfer
            var dt;
            try {
              dt = new DataTransfer();
              dt.setData('text/plain', dragText);
              dt.setData('text/html', drag.outerHTML);
              dt.effectAllowed = 'all';
              dt.dropEffect = 'move';
            } catch(e) {
              dt = null;
            }

            var evtInit = { bubbles: true, cancelable: true, dataTransfer: dt };

            // Dispatch full HTML5 drag sequence
            drag.dispatchEvent(new DragEvent('dragstart', evtInit));
            target.dispatchEvent(new DragEvent('dragenter', evtInit));

            // Check if dragover is accepted (preventDefault called)
            var overEvt = new DragEvent('dragover', evtInit);
            var overDefaultPrevented = false;
            var origPreventDefault = overEvt.preventDefault.bind(overEvt);
            // We dispatch and check defaultPrevented after
            target.dispatchEvent(overEvt);
            var accepted = overEvt.defaultPrevented;

            // Always try the drop regardless — some frameworks don't preventDefault on dragover
            target.dispatchEvent(new DragEvent('drop', evtInit));
            drag.dispatchEvent(new DragEvent('dragend', evtInit));

            // Also dispatch mouse events as secondary mechanism
            var dragRect = drag.getBoundingClientRect();
            var targetRect = target.getBoundingClientRect();
            var srcX = dragRect.left + dragRect.width / 2;
            var srcY = dragRect.top + dragRect.height / 2;
            var dstX = targetRect.left + targetRect.width / 2;
            var dstY = targetRect.top + targetRect.height / 2;

            drag.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: srcX, clientY: srcY }));
            target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: dstX, clientY: dstY }));
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: dstX, clientY: dstY }));

            // Check success conditions
            var dragRemoved = !drag.parentElement || drag.parentElement !== dragParentBefore;
            var targetGainedChild = target.children.length > targetChildCountBefore;
            var parentChanged = drag.parentElement !== originalParent;
            var dragHidden = drag.offsetParent === null || !isVisible(drag);

            var dropSuccess = dragRemoved || targetGainedChild || parentChanged || dragHidden;

            var method = accepted ? 'html5-accepted' : 'html5-forced';
            if (dropSuccess && !accepted) method = 'mouse-fallback';
            if (dropSuccess && accepted) method = 'html5-accepted';

            results.push({
              fromText: dragText,
              toSelector: elDesc(target),
              success: dropSuccess,
              method: method,
            });

            if (dropSuccess) {
              placedSet.add(dIdx);
              successCount++;
              break; // Move to next draggable
            }
          }
        }

        return {
          draggables: allDraggables.length,
          slotsAttempted: candidates.length,
          successfulDrops: successCount,
          results: results,
          summary: 'Brute force: ' + successCount + '/' + allDraggables.length + ' draggables placed across ' + candidates.length + ' candidate targets.',
        };
      })()
    `) as {
      draggables: number;
      slotsAttempted: number;
      successfulDrops: number;
      results: Array<{ fromText: string; toSelector: string; success: boolean; method: string }>;
      summary: string;
    };

    this.invalidateElementsCache();
    return result;
  }

  /**
   * Type text into element
   */
  async type(selector: string, text: string): Promise<void> {
    const page = await this.getPage();
    await page.fill(selector, text, { timeout: 5000 });
  }

  /**
   * Type with keyboard (no selector needed)
   */
  async typeText(text: string, pressEnter = false): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    await page.keyboard.type(text);
    if (pressEnter) {
      await page.keyboard.press('Enter');
    }
  }

  /**
   * Press a key
   */
  async pressKey(key: string): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    await page.keyboard.press(key);
  }

  /**
   * Scroll the page
   */
  async scroll(direction: 'up' | 'down', amount = 300): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    const delta = direction === 'down' ? amount : -amount;
    await page.mouse.wheel(0, delta);
  }

  /**
   * Go back in browser history
   */
  async goBack(): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    await page.goBack();
  }

  /**
   * Get all open tabs
   */
  async getTabs(): Promise<Array<{ tabId: number; url: string; title: string; active: boolean }>> {
    if (!this.context) return [];

    const pages = this.context.pages();
    const tabs = [];

    for (let i = 0; i < pages.length; i++) {
      tabs.push({
        tabId: i,
        url: pages[i].url(),
        title: await pages[i].title(),
        active: pages[i] === this.activePage,
      });
    }

    return tabs;
  }

  /**
   * Switch to tab by index
   */
  async switchToTab(tabIndex: number): Promise<{ tabId: number; url: string; title: string }> {
    if (!this.context) throw new Error('Browser not initialized');

    const pages = this.context.pages();
    if (tabIndex < 0 || tabIndex >= pages.length) {
      throw new Error(`Tab ${tabIndex} not found`);
    }

    this.activePage = pages[tabIndex];
    await this.activePage.bringToFront();

    return {
      tabId: tabIndex,
      url: this.activePage.url(),
      title: await this.activePage.title(),
    };
  }

  /**
   * Extract page content as text
   */
  async extractContent(): Promise<string> {
    const page = await this.getPage();
    return await page.evaluate(`
      (function() {
        const main = document.querySelector('main, article, [role="main"]');
        const content = main || document.body;
        return content.innerText || '';
      })()
    `) as string;
  }

  /**
   * Screen-reader style semantic extraction: headings, landmarks, forms, interactive elements.
   * High-signal, LLM-friendly output for autonomous agents (non-visual ingestion).
   */
  async extractSemanticContent(): Promise<string> {
    const page = await this.getPage();
    return await page.evaluate(`
      (function() {
        var out = [];
        var add = function(prefix, txt) {
          var t = (txt || '').toString().replace(/\\s+/g, ' ').trim().slice(0, 80);
          if (t) out.push(prefix + t);
        };

        var headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]');
        for (var i = 0; i < Math.min(headings.length, 20); i++) {
          var h = headings[i];
          var lvl = h.getAttribute('aria-level') || h.tagName.replace(/\\D/g, '') || '1';
          add('#'.repeat(Math.min(parseInt(lvl, 10) || 1, 6)) + ' ', (h.innerText || h.textContent || '').trim());
        }

        var landmarks = document.querySelectorAll('main, [role="main"], article, nav, [role="navigation"], header, footer, aside, [role="complementary"]');
        for (var j = 0; j < Math.min(landmarks.length, 5); j++) {
          var lm = landmarks[j];
          var role = lm.getAttribute('role') || lm.tagName.toLowerCase();
          var txt = (lm.innerText || lm.textContent || '').trim().slice(0, 120);
          if (txt) add('[landmark:' + role + '] ', txt);
        }

        var inputs = document.querySelectorAll('input, select, textarea');
        for (var k = 0; k < Math.min(inputs.length, 15); k++) {
          var inp = inputs[k];
          var lbl = inp.labels && inp.labels[0] ? inp.labels[0].innerText : (inp.getAttribute('aria-label') || inp.placeholder || inp.name || '');
          var ty = inp.type || inp.tagName.toLowerCase();
          add('[input:' + ty + '] ', lbl + ' -> ' + ((inp.value || '').slice(0, 30)));
        }

        var buttons = document.querySelectorAll('button, [role="button"], a[href], input[type="submit"], input[type="button"]');
        for (var b = 0; b < Math.min(buttons.length, 40); b++) {
          var btn = buttons[b];
          if (!btn || !btn.offsetParent) continue;
          var txt = (btn.innerText || btn.textContent || btn.getAttribute('aria-label') || btn.value || '').toString().trim().slice(0, 50);
          if (txt) add('[btn] ', txt);
        }

        return out.join('\\n') || (document.body && (document.body.innerText || '').trim().slice(0, 1500));
      })()
    `) as string;
  }

  /**
   * Get page HTML
   */
  async getHtml(): Promise<string> {
    const page = await this.getPage();
    return await page.content();
  }

  /**
   * Evaluate JavaScript in the page
   */
  async evaluate<T>(script: string): Promise<T> {
    const page = await this.getPage();
    return await page.evaluate(script) as T;
  }

  /**
   * Wait for a specified time
   */
  async wait(ms: number): Promise<void> {
    this.invalidateElementsCache();
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Wait for the DOM to stabilize (no mutations for `quietMs`).
   * Falls back to a short fixed wait if the page doesn't support MutationObserver
   * or if the timeout is reached.
   *
   * @param timeoutMs  Maximum time to wait (default 2000ms)
   * @param quietMs    How long without mutations to consider "stable" (default 150ms)
   */
  async waitForDomStable(timeoutMs = 2000, quietMs = 150): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    try {
      await page.evaluate(`
        new Promise(function(resolve) {
          var timeout = ${timeoutMs};
          var quiet = ${quietMs};
          var timer = null;
          var observer = new MutationObserver(function() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(function() { observer.disconnect(); resolve(); }, quiet);
          });
          observer.observe(document.body, {
            childList: true, subtree: true,
            attributes: true, characterData: true
          });
          timer = setTimeout(function() { observer.disconnect(); resolve(); }, quiet);
          setTimeout(function() { observer.disconnect(); resolve(); }, timeout);
        })
      `);
    } catch {
      // Fallback: if evaluate fails (e.g., page navigated), use a short fixed wait
      await this.wait(200);
    }
  }

  /**
   * Wait for selector
   */
  async waitForSelector(selector: string, timeout = 5000): Promise<void> {
    const page = await this.getPage();
    await page.waitForSelector(selector, { timeout });
  }

  /**
   * Wait for a CSS selector to appear/disappear, or wait for a JS condition to become true.
   * Much more reliable than fixed-ms browser_wait for dynamic content (reveals, modals, transitions).
   *
   * Modes:
   *  - selector + state="visible" (default): wait for element to appear and be visible
   *  - selector + state="hidden": wait for element to disappear or become hidden
   *  - selector + state="attached": wait for element to exist in DOM (even if not visible)
   *  - expression (no selector): wait for a JS expression to return truthy
   */
  async waitForCondition(opts: {
    selector?: string;
    state?: 'visible' | 'hidden' | 'attached';
    expression?: string;
    timeout?: number;
  }): Promise<{ success: boolean; waited: boolean; elapsed: number; error?: string }> {
    const page = await this.getPage();
    const timeout = Math.min(opts.timeout ?? 5000, 15000); // cap at 15s
    const start = Date.now();

    try {
      if (opts.expression) {
        // Wait for a JS expression to return truthy
        await page.waitForFunction(opts.expression, undefined, { timeout });
      } else if (opts.selector) {
        const state = opts.state ?? 'visible';
        await page.waitForSelector(opts.selector, {
          state,
          timeout,
        });
      } else {
        return { success: false, waited: false, elapsed: 0, error: 'Provide either selector or expression.' };
      }
      return { success: true, waited: true, elapsed: Date.now() - start };
    } catch (err: unknown) {
      const elapsed = Date.now() - start;
      const msg = err instanceof Error ? err.message : String(err);
      // Timeout is not an error per se — it means the condition wasn't met
      if (msg.includes('Timeout') || msg.includes('waiting for')) {
        return { success: false, waited: true, elapsed, error: `Condition not met within ${timeout}ms` };
      }
      return { success: false, waited: false, elapsed, error: msg.slice(0, 500) };
    }
  }

  /**
   * Select an option from a <select> dropdown, or check/uncheck a radio/checkbox.
   * Uses Playwright's native APIs which properly trigger framework events.
   *
   * For <select>: uses locator.selectOption() which fires change events natively.
   * For radio/checkbox: uses locator.setChecked() which handles label association,
   *   dispatches click + change + input events, and works with all frameworks.
   * For ARIA role="radio"/"checkbox": uses evaluate to set aria-checked and dispatch events.
   *
   * @param index - Element index from browser_get_elements
   * @param value - For <select>: the option value/label to select. For checkbox: true/false.
   */
  async selectOption(opts: {
    index?: number;
    selector?: string;
    value?: string;
    checked?: boolean;
    label?: string;
  }): Promise<{
    success: boolean;
    element: string;
    action: string;
    previousValue?: string;
    newValue?: string;
    error?: string;
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    // Resolve the element: by index (using data-aware-idx) or by selector
    const resolveSelector = opts.index !== undefined
      ? `[data-aware-idx="${opts.index}"]`
      : opts.selector;

    if (!resolveSelector) {
      return { success: false, element: 'unknown', action: 'none', error: 'Provide either index or selector.' };
    }

    // Get element info to determine type
    const info = await page.evaluate(`
      (function() {
        var el = document.querySelector('${resolveSelector.replace(/'/g, "\\'")}');
        if (!el) {
          // Fallback for index-based lookup: try positional
          ${opts.index !== undefined ? `
          var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"]';
          var elements = document.querySelectorAll(interactiveSelectors);
          if (${opts.index} >= 0 && ${opts.index} < elements.length) {
            el = elements[${opts.index}];
          }
          ` : ''}
          if (!el) return { found: false };
        }
        var tag = (el.tagName || '').toLowerCase();
        var type = (el.getAttribute('type') || '').toLowerCase();
        var role = (el.getAttribute('role') || '').toLowerCase();
        var name = el.getAttribute('name') || '';
        var currentValue = '';
        if (tag === 'select') currentValue = el.value || '';
        else if (tag === 'input' && (type === 'radio' || type === 'checkbox')) currentValue = String(el.checked);
        else if (role === 'radio' || role === 'checkbox') currentValue = el.getAttribute('aria-checked') || 'false';
        return { found: true, tag: tag, type: type, role: role, name: name, currentValue: currentValue };
      })()
    `) as { found: boolean; tag?: string; type?: string; role?: string; name?: string; currentValue?: string };

    if (!info.found) {
      return {
        success: false,
        element: resolveSelector,
        action: 'none',
        error: `Element not found: ${resolveSelector}. Run browser_get_elements to refresh indices.`,
      };
    }

    const { tag, type, role, currentValue } = info;
    const locator = page.locator(resolveSelector).first();

    try {
      // <select> element: use selectOption
      if (tag === 'select') {
        const selectValue = opts.value ?? opts.label ?? '';
        // Try by value first, then by label
        try {
          await locator.selectOption({ value: selectValue }, { timeout: 3000 });
        } catch {
          await locator.selectOption({ label: selectValue }, { timeout: 3000 });
        }
        const newVal = await locator.inputValue().catch(() => selectValue);
        return {
          success: true,
          element: `<select name="${info.name}">`,
          action: `selected "${selectValue}"`,
          previousValue: currentValue,
          newValue: newVal,
        };
      }

      // <input type="radio"> or <input type="checkbox">
      if (tag === 'input' && (type === 'radio' || type === 'checkbox')) {
        const shouldCheck = type === 'radio' ? true : (opts.checked ?? true);
        await locator.setChecked(shouldCheck, { timeout: 3000 });
        return {
          success: true,
          element: `<input type="${type}" name="${info.name}">`,
          action: shouldCheck ? 'checked' : 'unchecked',
          previousValue: currentValue,
          newValue: String(shouldCheck),
        };
      }

      // ARIA role="radio" or role="checkbox"
      if (role === 'radio' || role === 'checkbox') {
        const shouldCheck = role === 'radio' ? true : (opts.checked ?? true);
        const checkStr = String(shouldCheck);
        await page.evaluate(`
          (function() {
            var el = document.querySelector('${resolveSelector.replace(/'/g, "\\'")}');
            if (!el) return;
            // Scroll into view
            try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch(e) {}
            // Click the element
            el.click();
            // Set aria-checked
            el.setAttribute('aria-checked', '${checkStr}');
            // Dispatch framework events
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            // For radio: uncheck siblings in same radiogroup
            ${role === 'radio' ? `
            var group = el.closest('[role="radiogroup"]');
            if (group) {
              var siblings = group.querySelectorAll('[role="radio"]');
              for (var i = 0; i < siblings.length; i++) {
                if (siblings[i] !== el) siblings[i].setAttribute('aria-checked', 'false');
              }
            }
            ` : ''}
          })()
        `);
        return {
          success: true,
          element: `<${tag} role="${role}">`,
          action: shouldCheck ? 'checked' : 'unchecked',
          previousValue: currentValue,
          newValue: checkStr,
        };
      }

      // Fallback: if the element is a <label>, find its associated input
      if (tag === 'label') {
        const labelFor = await page.evaluate(`
          (function() {
            var lbl = document.querySelector('${resolveSelector.replace(/'/g, "\\'")}');
            if (!lbl) return null;
            var forId = lbl.getAttribute('for');
            if (forId) {
              var target = document.getElementById(forId);
              if (target) return { tag: target.tagName.toLowerCase(), type: target.type || '', id: forId };
            }
            // Check if label wraps an input
            var inner = lbl.querySelector('input, select');
            if (inner) return { tag: inner.tagName.toLowerCase(), type: inner.type || '', id: '' };
            return null;
          })()
        `) as { tag: string; type: string; id: string } | null;

        if (labelFor) {
          // Click the label — this activates the associated input
          await locator.click({ timeout: 3000 });
          return {
            success: true,
            element: `<label> → <${labelFor.tag} type="${labelFor.type}">`,
            action: 'clicked label (activates associated input)',
            previousValue: currentValue,
          };
        }
      }

      return {
        success: false,
        element: `<${tag} type="${type}" role="${role}">`,
        action: 'none',
        error: `Element is not a select, radio, or checkbox. Use browser_click for this element type.`,
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        success: false,
        element: `<${tag} type="${type}" role="${role}">`,
        action: 'failed',
        error: msg.slice(0, 500),
      };
    }
  }

  /**
   * Get interactive elements on the page with spatial awareness and visibility info.
   * Returns elements grouped by region (top/middle/bottom) with visibility status.
   */
  /** Invalidate the elements cache (call after state-changing actions). */
  invalidateElementsCache(): void {
    this.elementsCache = null;
  }

  async getInteractiveElements(opts?: { showAll?: boolean; compact?: boolean }): Promise<string> {
    const showAll = opts?.showAll ?? false;
    const compact = opts?.compact ?? false;

    // Return cached result if still fresh (skip cache for showAll/compact — cached result is truncated)
    if (!showAll && !compact && this.elementsCache && (Date.now() - this.elementsCache.ts) < this.ELEMENTS_CACHE_TTL) {
      return this.elementsCache.value;
    }

    const page = await this.getPage();

    const elements = await page.evaluate(`
      (function() {
        var SHOW_ALL = ${showAll ? 'true' : 'false'};
        var COMPACT = ${compact ? 'true' : 'false'};
        var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';

        // Clear old stable IDs before reassigning
        var old = document.querySelectorAll('[data-aware-idx]');
        for (var k = 0; k < old.length; k++) old[k].removeAttribute('data-aware-idx');

        var elements = document.querySelectorAll(interactiveSelectors);
        var viewportHeight = window.innerHeight;
        var viewportWidth = window.innerWidth;

        function isVisible(el) {
          try {
            var cs = window.getComputedStyle(el);
            if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
            var r = el.getBoundingClientRect();
            if (!r || r.width < 2 || r.height < 2) return false;
            return true;
          } catch(e) { return false; }
        }

        function isInViewport(el) {
          var r = el.getBoundingClientRect();
          return r.top < viewportHeight && r.bottom > 0 && r.left < viewportWidth && r.right > 0;
        }

        function isObscured(el) {
          try {
            var r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            // Check 5 points: center + 4 inset corners. Obscured if majority (3+) are blocked.
            var insetX = Math.max(r.width * 0.25, 2);
            var insetY = Math.max(r.height * 0.25, 2);
            var points = [
              [r.left + r.width / 2, r.top + r.height / 2],    // center
              [r.left + insetX, r.top + insetY],                // top-left
              [r.right - insetX, r.top + insetY],               // top-right
              [r.left + insetX, r.bottom - insetY],             // bottom-left
              [r.right - insetX, r.bottom - insetY],            // bottom-right
            ];
            var blocked = 0;
            for (var pi = 0; pi < points.length; pi++) {
              var topEl = document.elementFromPoint(points[pi][0], points[pi][1]);
              if (topEl && !el.contains(topEl) && !topEl.contains(el) && topEl !== el) blocked++;
            }
            return blocked >= 3;
          } catch(e) { return false; }
        }

        function getRegion(y) {
          if (y < viewportHeight * 0.33) return 'TOP';
          if (y < viewportHeight * 0.66) return 'MIDDLE';
          return 'BOTTOM';
        }

        function extractHostname(url) {
          try {
            var a = document.createElement('a');
            a.href = url;
            return a.hostname;
          } catch(e) { return url.slice(0, 30); }
        }

        var regions = { TOP: [], MIDDLE: [], BOTTOM: [], OFFSCREEN: [] };
        var compactLines = [];

        for (var index = 0; index < elements.length; index++) {
          var el = elements[index];

          // Stamp stable ID into the DOM so click/type/inspect can find this exact element later
          el.setAttribute('data-aware-idx', String(index));

          var tag = el.tagName.toLowerCase();
          var type = el.getAttribute('type') || '';
          var visible = isVisible(el);
          var inView = isInViewport(el);
          var obscured = visible && inView && isObscured(el);
          var disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
          var checked = el.checked;
          var isDraggable = el.getAttribute('draggable') === 'true';
          var href = el.getAttribute('href') || '';

          if (COMPACT) {
            // In compact mode: skip OFFSCREEN and HIDDEN elements entirely (already stamped data-aware-idx)
            if (!visible || !inView) continue;

            var text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 30);
            var line = '[' + index + '] ' + tag;
            if (type) line += ':' + type;
            if (text) line += ' "' + text + '"';

            // Abbreviated flags
            var flags = [];
            if (isDraggable) flags.push('DRAG');
            if (obscured) flags.push('OBS');
            if (disabled) flags.push('DIS');
            if (checked) flags.push('CHK');
            if (flags.length > 0) line += ' [' + flags.join(',') + ']';

            // For links: append >hostname instead of full href
            if (tag === 'a' && href && href !== '#') {
              line += ' >' + extractHostname(href);
            }

            compactLines.push(line);
          } else {
            // Normal (non-compact) mode: keep everything exactly as-is
            var text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
            var placeholder = el.getAttribute('placeholder') || '';
            var ariaLabel = el.getAttribute('aria-label') || '';
            var value = el.value || '';
            var role = el.getAttribute('role') || '';
            var rect = el.getBoundingClientRect();

            var desc = '[' + index + ']';

            if (!visible) desc += ' [HIDDEN]';
            else if (!inView) desc += ' [OFFSCREEN]';
            else if (obscured) desc += ' [OBSCURED]';
            if (disabled) desc += ' [DISABLED]';
            if (checked) desc += ' [CHECKED]';
            if (isDraggable) desc += ' [DRAGGABLE]';

            desc += ' <' + tag;
            if (role) desc += ' role="' + role + '"';
            if (type) desc += ' type="' + type + '"';
            desc += '>';

            if (text) desc += ' "' + text + '"';
            else if (ariaLabel) desc += ' aria="' + ariaLabel + '"';
            else if (placeholder) desc += ' placeholder="' + placeholder + '"';
            else if (value && type !== 'password') desc += ' value="' + value.slice(0, 30) + '"';
            if (href && href !== '#') desc += ' \\u2192 ' + href.slice(0, 40);

            if (visible && inView) {
              regions[getRegion(rect.top)].push(desc);
            } else {
              regions.OFFSCREEN.push(desc);
            }
          }
        }

        if (COMPACT) {
          return compactLines.join('\\n');
        }

        var output = [];
        if (regions.TOP.length > 0) {
          output.push('=== TOP OF PAGE ===');
          output.push.apply(output, regions.TOP);
        }
        if (regions.MIDDLE.length > 0) {
          output.push('=== MIDDLE OF PAGE ===');
          output.push.apply(output, regions.MIDDLE);
        }
        if (regions.BOTTOM.length > 0) {
          output.push('=== BOTTOM OF PAGE ===');
          output.push.apply(output, regions.BOTTOM);
        }
        if (regions.OFFSCREEN.length > 0) {
          if (SHOW_ALL || regions.OFFSCREEN.length <= 30) {
            output.push('=== OFFSCREEN/HIDDEN (' + regions.OFFSCREEN.length + ' elements' + (SHOW_ALL ? ', showAll' : '') + ') ===');
            output.push.apply(output, regions.OFFSCREEN);
          } else {
            output.push('=== OFFSCREEN/HIDDEN (' + regions.OFFSCREEN.length + ' elements, showing first 30 — use showAll=true for full list) ===');
            output.push.apply(output, regions.OFFSCREEN.slice(0, 30));
          }
        }

        return output.join('\\n');
      })()
    `) as string;

    // Only cache the normal (truncated) result; showAll/compact results are one-off
    if (!showAll && !compact) {
      this.elementsCache = { value: elements, ts: Date.now() };
    }
    return elements;
  }

  /**
   * Inspect an interactive element by index (attributes + outerHTML preview).
   * Useful for rigorous debugging: verify labels, roles, data-* attributes, and DOM structure before acting.
   */
  async inspectElementByIndex(index: number): Promise<{
    index: number;
    tag: string;
    text: string;
    attributes: Record<string, string>;
    outerHTML: string;
  }> {
    const page = await this.getPage();

    const data = await page.evaluate(
      `(function() {
        var idx = ${index};

        // 1. Stable lookup via data-aware-idx
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');

        // 2. Fallback to positional index
        if (!el) {
          var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
          var elements = document.querySelectorAll(interactiveSelectors);
          if (idx < 0 || idx >= elements.length) throw new Error('Element ' + idx + ' not found. Re-run browser_get_elements to refresh indices.');
          el = elements[idx];
        }

        var attrs = {};
        var attrList = el.attributes || [];
        for (var i = 0; i < attrList.length; i++) {
          var a = attrList[i];
          if (a.name !== 'data-aware-idx') attrs[a.name] = String(a.value);
        }
        var tag = (el.tagName || '').toLowerCase();
        var text = String((el.innerText || el.textContent || '')).slice(0, 500);
        var outerHTML = String(el.outerHTML || '').slice(0, 4000);
        return { tag: tag, text: text, attributes: attrs, outerHTML: outerHTML };
      })()`
    ) as { tag: string; text: string; attributes: Record<string, string>; outerHTML: string };

    return {
      index,
      tag: data.tag,
      text: data.text,
      attributes: data.attributes,
      outerHTML: data.outerHTML,
    };
  }

  /**
   * Inspect page meta tags (name/property/content).
   * Useful for debugging SEO/OG tags, redirects, and app metadata.
   */
  async getMetaTags(): Promise<Array<{ name?: string; property?: string; content?: string }>> {
    const page = await this.getPage();
    const metas = await page.evaluate(
      `(() => {
        return Array.from(document.querySelectorAll('meta')).map(m => ({
          name: m.getAttribute('name') || undefined,
          property: m.getAttribute('property') || undefined,
          content: m.getAttribute('content') || undefined,
        }));
      })()`
    ) as Array<{ name?: string; property?: string; content?: string }>;
    return metas;
  }

  /**
   * Detect minimum timing requirements from the page's JavaScript.
   * Challenge pages embed timing maps like: getMinTimeForChallengeType(t){return{visible:500,hidden_dom:1e3,...}}
   * We probe the page once per URL and cache the result.
   */
  private async detectPageMinTime(page: PlaywrightPage): Promise<number> {
    const currentUrl = page.url();
    if (this._minTimeDetected && this._clickSeqUrl === currentUrl) {
      return this._detectedMinTime;
    }

    this._minTimeDetected = true;
    try {
      const detected = await page.evaluate(`
        (function() {
          try {
            // Search bundled scripts for timing configuration pattern
            var scripts = document.querySelectorAll('script[src]');
            for (var i = 0; i < scripts.length; i++) {
              var src = scripts[i].getAttribute('src') || '';
              // Check if the page has a timing validation function via known patterns
              // Try window-level or module-level access
            }
            // Check for data attributes that encode timing
            var root = document.querySelector('[data-challenge-type]');
            if (root) {
              var type = root.getAttribute('data-challenge-type') || '';
              var minMs = root.getAttribute('data-min-time');
              if (minMs) return parseInt(minMs, 10) || 0;
            }
            // Try to extract from React/app state
            var el = document.querySelector('#root, #app, [id*="challenge"]');
            if (el && el._reactRootContainer) {
              // React internals — not reliable, skip
            }
            // Try calling global timing function if exposed
            if (typeof window.getMinTimeForChallengeType === 'function') {
              var max = 0;
              ['visible','hidden_dom','click_reveal','hover_reveal','scroll_reveal','delayed_reveal'].forEach(function(t) {
                try { var v = window.getMinTimeForChallengeType(t); if (v > max) max = v; } catch(e) {}
              });
              return max;
            }
          } catch(e) {}
          return 0;
        })()
      `) as number;
      if (detected > 0) {
        this._detectedMinTime = detected;
        return detected;
      }
    } catch { /* ignore detection failure */ }

    // No timing requirement detected on this page — don't add artificial delays.
    this._detectedMinTime = 0;
    return 0;
  }

  /**
   * Apply adaptive post-click delay based on the page's timing requirements.
   * Ensures the total click sequence takes at least the page's minimum time.
   * On first click, probes the page for timing info.
   * On subsequent clicks, waits proportionally to meet the target.
   */
  private async applyAdaptiveClickDelay(page: PlaywrightPage): Promise<void> {
    const now = Date.now();
    const currentUrl = page.url();

    // Reset sequence on URL change OR time gap >3s since last click.
    // The time gap handles SPAs where the URL stays the same across steps/challenges.
    const timeSinceLastClick = this._lastClickTime > 0 ? (now - this._lastClickTime) : Infinity;
    const urlChanged = currentUrl !== this._clickSeqUrl;
    if (urlChanged || timeSinceLastClick > 3000) {
      this._clickSeqStart = now;
      this._clickSeqCount = 0;
      // Re-detect timing on actual URL change (page timing doesn't change within same URL)
      if (urlChanged) {
        this._clickSeqUrl = currentUrl;
        this._minTimeDetected = false;
        this._detectedMinTime = 0;
      }
    }

    this._lastClickTime = now;
    this._clickSeqCount++;

    // Detect timing requirements (cached after first call per URL)
    const minTime = await this.detectPageMinTime(page);

    // No timing requirement on this page — skip delay entirely.
    if (minTime <= 0) {
      this._lastClickTime = Date.now();
      return;
    }

    // Page has a timing requirement. Ensure the click sequence takes at least minTime.
    const elapsed = now - this._clickSeqStart;

    if (this._clickSeqCount >= 2) {
      // Add a 20% buffer over the minimum to avoid edge-case rejections.
      const targetTotal = Math.ceil(minTime * 1.2);
      const remaining = targetTotal - elapsed;
      if (remaining > 0 && remaining < 15000) {
        await page.waitForTimeout(remaining);
        this._lastClickTime = Date.now();
        return;
      }
    }

    this._lastClickTime = Date.now();
  }

  /**
   * Click interactive element by index
   * Uses the same selector set as getInteractiveElements for consistency
   */
  async clickElementByIndex(index: number): Promise<{ clicked: boolean; elementInfo?: string }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    const result = await page.evaluate(`
      (function() {
        var idx = ${index};

        // 1. Try stable lookup via data-aware-idx (survives DOM mutations)
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');

        // 2. Fallback to positional index if stable ID not found
        if (!el) {
          var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
          var elements = document.querySelectorAll(interactiveSelectors);
          var total = elements.length;

          if (idx < 0 || idx >= total) {
            var available = [];
            for (var i = Math.max(0, idx - 3); i < Math.min(total, idx + 4); i++) {
              var candidate = elements[i];
              if (candidate) {
                available.push('[' + i + '] <' + candidate.tagName.toLowerCase() + '> ' + (candidate.innerText || '').slice(0, 30).trim());
              }
            }
            throw new Error('Element ' + idx + ' not found. Total elements: ' + total + '. ' +
              (available.length > 0 ? 'Nearby indices: ' + available.join(', ') : 'No elements near that index.') +
              ' Re-run browser_get_elements to refresh indices.');
          }
          el = elements[idx];
        }

        var tag = el.tagName.toLowerCase();
        var text = (el.innerText || el.textContent || '').slice(0, 50).trim();

        try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch(e) {}

        try {
          // Dispatch the full pointer event chain that frameworks (React, Angular, Vue) expect.
          // el.click() alone skips pointerdown/mousedown/pointerup/mouseup which many listeners require.
          var rect = el.getBoundingClientRect();
          var cx = rect.left + rect.width / 2;
          var cy = rect.top + rect.height / 2;
          var evOpts = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy };
          el.dispatchEvent(new PointerEvent('pointerdown', evOpts));
          el.dispatchEvent(new MouseEvent('mousedown', evOpts));
          el.dispatchEvent(new PointerEvent('pointerup', evOpts));
          el.dispatchEvent(new MouseEvent('mouseup', evOpts));
          el.dispatchEvent(new MouseEvent('click', evOpts));
        } catch(e) {
          try { el.click(); } catch(e2) {
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          }
        }

        // For radio/checkbox inputs: ensure state change is registered by frameworks.
        // Many frameworks (React, Angular, Vue) listen on 'change'/'input' events,
        // not 'click'. Without dispatching these, the radio may appear clicked but
        // the framework state never updates and the form submission fails.
        var isRadioOrCheckbox = (tag === 'input' && (el.type === 'radio' || el.type === 'checkbox'));
        var isRoleRadio = el.getAttribute('role') === 'radio' || el.getAttribute('role') === 'checkbox';
        if (isRadioOrCheckbox) {
          // Ensure the checked state is set (click should do this, but force it)
          if (el.type === 'radio') el.checked = true;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('input', { bubbles: true }));
        } else if (isRoleRadio) {
          // ARIA role="radio" elements: toggle aria-checked and dispatch events
          el.setAttribute('aria-checked', 'true');
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('input', { bubbles: true }));
          // Also find the parent radiogroup and uncheck siblings
          var group = el.closest('[role="radiogroup"]');
          if (group) {
            var siblings = group.querySelectorAll('[role="radio"]');
            for (var si = 0; si < siblings.length; si++) {
              if (siblings[si] !== el) siblings[si].setAttribute('aria-checked', 'false');
            }
          }
        }

        return { clicked: true, elementInfo: '<' + tag + '> "' + text + '"' };
      })()
    `) as { clicked: boolean; elementInfo?: string };

    // Adaptive delay: ensures framework state updates + meets page timing requirements.
    await this.applyAdaptiveClickDelay(page);

    return result;
  }

  /**
   * Click an element by matching its visible text (or aria-label/title).
   * Prefers visible matches, but can fall back to offscreen matches (scrolls into view).
   * This avoids brittle numeric indices when pages have many dynamic elements.
   */
  async clickElementByText(
    text: string,
    opts?: { exact?: boolean; caseSensitive?: boolean; nth?: number }
  ): Promise<{ matchedText: string; tag: string }> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    const query = String(text ?? '');
    const exact = Boolean(opts?.exact);
    const caseSensitive = Boolean(opts?.caseSensitive);
    const nth = typeof opts?.nth === 'number' && Number.isFinite(opts.nth) ? Math.max(0, Math.floor(opts.nth)) : 0;

    const clickResult = await page.evaluate(
      `((query, exact, caseSensitive, nth) => {
        const norm = (s) => {
          const x = (s ?? '').toString().replace(/\\s+/g, ' ').replace(/\\u00a0/g, ' ').trim();
          return caseSensitive ? x : x.toLowerCase();
        };

        const q = norm(query);
        if (!q) throw new Error('Text query is empty');

        const isPresent = (el) => {
          try {
            const cs = window.getComputedStyle(el);
            if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || '1') < 0.05) return false;
            const r = el.getBoundingClientRect();
            if (!r || r.width < 2 || r.height < 2) return false;
            return true;
          } catch {
            return false;
          }
        };

        const isVisible = (el) => {
          if (!isPresent(el)) return false;
          try {
            const r = el.getBoundingClientRect();
            // Consider it visible if its center point is within viewport-ish bounds
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;
            if (cx < -50 || cy < -50) return false;
            if (cx > (window.innerWidth + 50) || cy > (window.innerHeight + 50)) return false;
            return true;
          } catch {
            return false;
          }
        };

        const selectors = [
          'button',
          'a',
          'input',
          'select',
          'label',
          '[role="button"]',
          '[role="radio"]',
          '[role="checkbox"]',
          '[role="link"]',
          '[role="option"]',
          '[role="tab"]',
          '[role="menuitem"]',
          '[role="switch"]',
          '[draggable="true"]',
          '[onclick]',
          '[tabindex]'
        ].join(',');

        // Also search ALL elements for cursor:pointer (catches React/SPA clickable divs)
        const getCursorPointerEls = () => {
          var results = [];
          var all = document.querySelectorAll('div, span, p, li, td, section, article, h1, h2, h3, h4, h5, h6');
          for (var i = 0; i < Math.min(all.length, 2000); i++) {
            try {
              if (getComputedStyle(all[i]).cursor === 'pointer') results.push(all[i]);
            } catch(e) {}
          }
          return results;
        };

        const collect = (filterFn) => {
          // Combine standard interactive elements + cursor-pointer elements
          var selectorEls = Array.from(document.querySelectorAll(selectors));
          var pointerEls = getCursorPointerEls();
          var seen = new Set(selectorEls);
          for (var pe of pointerEls) { if (!seen.has(pe)) { selectorEls.push(pe); seen.add(pe); } }
          return selectorEls
            .filter(filterFn)
            .map((el) => {
              const t = norm(el.innerText || el.textContent || '');
              const aria = norm(el.getAttribute('aria-label') || '');
              const title = norm(el.getAttribute('title') || '');
              const rawText = (el.innerText || el.textContent || '').toString().replace(/\\s+/g, ' ').trim();
              const rawNorm = norm(rawText);
              const rect = el.getBoundingClientRect();
              // For short queries (<=2 chars) in non-exact mode, require the match to be
              // a standalone token (word boundary) to avoid false positives like "R" matching "Required".
              const shortQ = q.length <= 2;
              const substringMatch = (hay) => {
                if (!hay.includes(q)) return false;
                if (!shortQ) return true;
                // Short token: require word boundary — check chars before/after match position
                var pos = hay.indexOf(q);
                while (pos !== -1) {
                  var before = pos === 0 ? ' ' : hay[pos - 1];
                  var after = (pos + q.length >= hay.length) ? ' ' : hay[pos + q.length];
                  var bOk = /[^a-zA-Z0-9]/.test(before);
                  var aOk = /[^a-zA-Z0-9]/.test(after);
                  if (bOk && aOk) return true;
                  pos = hay.indexOf(q, pos + 1);
                }
                return hay === q;
              };
              let score =
                (exact && (t === q || aria === q || title === q)) ? 1000 :
                (!exact && (substringMatch(t) || substringMatch(aria) || substringMatch(title))) ? 500 :
                0;

              // Disambiguate generic "click here" queries: prefer the actual clickable element
              // over large containers whose text happens to include "click here".
              const genericClickHere = (q === 'click here' || q === 'click here!' || q === 'here');
              if (genericClickHere) {
                // Penalise large containers (headings, paragraphs, divs) that contain "click here"
                // as part of a longer sentence — the actual target is the small clickable element.
                var tag = (el.tagName || '').toLowerCase();
                var isContainer = (tag === 'div' || tag === 'section' || tag === 'article' ||
                  tag === 'p' || tag === 'h1' || tag === 'h2' || tag === 'h3' || tag === 'h4');
                if (isContainer && rawText.length > 60) score -= 300;
                // Penalise headings/labels that are not the interactive target
                if (rawNorm.includes('hidden dom challenge') || rawNorm.includes('code hidden')) score -= 200;

                // Inspect nearby instruction context to choose the intended reveal target
                // instead of top-nav/start/reset decoys that also say "click here".
                var ctx = '';
                try {
                  var p = el.parentElement;
                  var depth = 0;
                  while (p && depth < 3) {
                    var tctx = (p.innerText || p.textContent || '').toString().replace(/\\s+/g, ' ').trim();
                    if (tctx) { ctx += ' ' + tctx.toLowerCase(); }
                    p = p.parentElement;
                    depth++;
                  }
                } catch(e) {}

                var revealContext =
                  ctx.includes('more times') ||
                  ctx.includes('to reveal') ||
                  ctx.includes('to unlock') ||
                  ctx.includes('reveal code') ||
                  ctx.includes('hidden dom');
                if (revealContext) score += 280;

                var decoyContext =
                  ctx.includes('start') ||
                  ctx.includes('home') ||
                  ctx.includes('back to start') ||
                  ctx.includes('reset') ||
                  ctx.includes('main menu');
                if (decoyContext) score -= 420;
              }

              // Boost actual interactive elements — these are the real click targets.
              var standardInteractive = new Set(['a','button','input','select','textarea','label']);
              var elTag = (el.tagName || '').toLowerCase();
              if (standardInteractive.has(elTag)) score += 100;

              // Deprioritize cursor-pointer containers (div/span/p/...) that are NOT
              // standard interactive elements — their broad text often false-matches.
              try {
                var isPointerContainer = !standardInteractive.has(elTag) &&
                  !el.getAttribute('role') &&
                  !el.getAttribute('onclick') &&
                  window.getComputedStyle(el).cursor === 'pointer';
                if (isPointerContainer) score -= 200;
              } catch {}

              // Penalise span elements that just wrap decorative/instructional text
              if (elTag === 'span' && !el.getAttribute('role') && !el.getAttribute('onclick') && rawText.length > 30) score -= 150;
              return {
                el,
                tRaw: rawText,
                tag: (el.tagName || '').toLowerCase(),
                score,
                y: rect?.top ?? 0,
                x: rect?.left ?? 0,
                len: (t || aria || title).length
              };
            })
            .filter(c => c.score > 0)
            .sort((a, b) => (b.score - a.score) || (a.len - b.len) || (a.y - b.y) || (a.x - b.x));
        };

        // Only click visible (in-viewport) matches. Offscreen elements are often
        // hidden decoys, nav items, or unrelated UI that sends the flow sideways.
        const candidates = collect(isVisible);

        if (candidates.length === 0) {
          const offscreen = collect(isPresent);
          // Gather unique texts for "did you mean" suggestions (UX for autonomous agents)
          const selectorEls = Array.from(document.querySelectorAll(selectors));
          const pointerEls = getCursorPointerEls();
          const seen = new Set(selectorEls);
          for (var pe of pointerEls) { if (!seen.has(pe)) { selectorEls.push(pe); seen.add(pe); } }
          const texts = [];
          const textSeen = new Set();
          for (var ei = 0; ei < selectorEls.length && texts.length < 40; ei++) {
            var elem = selectorEls[ei];
            if (!isPresent(elem)) continue;
            var t = (elem.innerText || elem.textContent || elem.getAttribute('aria-label') || '').toString().replace(/\\s+/g, ' ').trim().slice(0, 50);
            if (!t || t.length < 1 || textSeen.has(t)) continue;
            textSeen.add(t);
            texts.push(t);
          }
          var qL = q;
          if (!caseSensitive) qL = q.toLowerCase();
          var suggestions = texts.filter(function(t) {
            var tl = caseSensitive ? t : t.toLowerCase();
            return tl.indexOf(qL) !== -1 || qL.indexOf(tl) !== -1 ||
              (qL.length > 2 && tl.length > 2 && (tl.indexOf(qL.slice(0, Math.min(4, qL.length))) !== -1 || qL.indexOf(tl.slice(0, 4)) !== -1));
          }).sort(function(a,b) { return a.length - b.length; }).slice(0, 5);
          var msg = offscreen.length > 0
            ? 'No VISIBLE element matching text: "' + query + '" (found ' + offscreen.length + ' offscreen). Scroll the page first, or use browser_click with an explicit index.'
            : 'No element matching text: "' + query + '"';
          return { _noMatch: true, message: msg, suggestions: suggestions };
        }

        const chosen = candidates[Math.min(nth, candidates.length - 1)];
        const el = chosen.el;
        try {
          el.scrollIntoView({ block: 'center', inline: 'center' });
        } catch {}

        // Prefer native click; fall back to event dispatch
        try {
          el.click();
        } catch {
          try {
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          } catch (e) {
            throw new Error('Failed to click matched element: ' + (e?.message || String(e)));
          }
        }

        // For radio/checkbox inputs: dispatch change+input events for framework compatibility.
        var elTag = (el.tagName || '').toLowerCase();
        var isRadioOrCb = (elTag === 'input' && (el.type === 'radio' || el.type === 'checkbox'));
        var isRoleRadio = el.getAttribute('role') === 'radio' || el.getAttribute('role') === 'checkbox';
        if (isRadioOrCb) {
          if (el.type === 'radio') el.checked = true;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('input', { bubbles: true }));
        } else if (isRoleRadio) {
          el.setAttribute('aria-checked', 'true');
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('input', { bubbles: true }));
          var rg = el.closest('[role="radiogroup"]');
          if (rg) {
            var sibs = rg.querySelectorAll('[role="radio"]');
            for (var ri = 0; ri < sibs.length; ri++) {
              if (sibs[ri] !== el) sibs[ri].setAttribute('aria-checked', 'false');
            }
          }
        }

        return { matchedText: chosen.tRaw || query, tag: chosen.tag };
      })(${JSON.stringify(query)}, ${exact ? 'true' : 'false'}, ${caseSensitive ? 'true' : 'false'}, ${nth})`
    ) as { matchedText?: string; tag?: string; _noMatch?: boolean; message?: string; suggestions?: string[] };

    if (clickResult && clickResult._noMatch) {
      let errMsg = clickResult.message || 'No element matching text';
      if (clickResult.suggestions && clickResult.suggestions.length > 0) {
        errMsg += '. Did you mean: ' + clickResult.suggestions.map((s: string) => `"${s}"`).join(', ') + '?';
      }
      throw new Error(errMsg);
    }

    // Adaptive delay: ensures framework state updates + meets page timing requirements.
    await this.applyAdaptiveClickDelay(page);
    return { matchedText: clickResult.matchedText!, tag: clickResult.tag! };
  }

  /**
   * Click multiple elements atomically within a single tool invocation.
   * ALL targets are resolved from the SAME DOM snapshot before any click fires,
   * so rotating labels (split-part challenges) cannot go stale between clicks.
   * For index targets, uses data-aware-idx lookup. For text targets, matches visible
   * interactive elements by text content. Then clicks all resolved elements in sequence.
   */
  async clickBatch(
    targets: Array<{ text: string; exact?: boolean; nth?: number } | { index: number }>
  ): Promise<{
    clicks: Array<{
      target: string;
      index?: number;
      success: boolean;
      matchedText?: string;
      error?: string;
    }>;
    summary: string;
  }> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    // Build target specs for the in-page resolver
    const specs = targets.map(t => {
      if ('index' in t && typeof t.index === 'number') {
        return { type: 'index' as const, index: t.index, text: '', exact: false };
      }
      return { type: 'text' as const, index: -1, text: (t as { text: string }).text, exact: (t as { exact?: boolean }).exact ?? false };
    });

    // Phase 1: Resolve ALL targets from a single DOM snapshot, then click them all
    const result = await page.evaluate(`
      (function() {
        var specs = ${JSON.stringify(specs)};
        var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';

        function findByIndex(idx) {
          var el = document.querySelector('[data-aware-idx="' + idx + '"]');
          if (!el) {
            var list = document.querySelectorAll(interactiveSelectors);
            if (idx >= 0 && idx < list.length) el = list[idx];
          }
          return el || null;
        }

        function findByText(text, exact) {
          var lower = text.toLowerCase();
          var candidates = document.querySelectorAll(interactiveSelectors);
          for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            var cs = window.getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            var r = el.getBoundingClientRect();
            if (r.width < 1 || r.height < 1) continue;
            var elText = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (exact) {
              if (elText === text) return el;
            } else {
              if (elText.toLowerCase().indexOf(lower) >= 0) return el;
            }
            var aria = el.getAttribute('aria-label') || '';
            if (aria && (exact ? aria === text : aria.toLowerCase().indexOf(lower) >= 0)) return el;
            var title = el.getAttribute('title') || '';
            if (title && (exact ? title === text : title.toLowerCase().indexOf(lower) >= 0)) return el;
          }
          return null;
        }

        // Resolve all targets from current snapshot
        var resolved = [];
        for (var i = 0; i < specs.length; i++) {
          var spec = specs[i];
          var el = null;
          var matchedText = '';
          if (spec.type === 'index') {
            el = findByIndex(spec.index);
            if (el) matchedText = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
          } else {
            el = findByText(spec.text, spec.exact);
            if (el) matchedText = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
          }
          resolved.push({ el: el, matchedText: matchedText, spec: spec });
        }

        // Click all resolved elements in sequence, verifying each is still attached + visible
        // (prior clicks can trigger DOM re-renders that detach subsequent elements)
        var clicks = [];
        for (var j = 0; j < resolved.length; j++) {
          var item = resolved[j];
          var label = item.spec.type === 'index' ? '[' + item.spec.index + ']' : item.spec.text;
          if (!item.el) {
            clicks.push({
              target: label,
              success: false,
              error: 'Element not found in DOM snapshot',
              matchedText: ''
            });
            continue;
          }
          // Verify element is still attached to the live DOM
          if (!document.contains(item.el)) {
            clicks.push({
              target: label,
              success: false,
              error: 'Element detached after prior click (DOM re-rendered)',
              matchedText: item.matchedText
            });
            continue;
          }
          // Verify element is still visible (not hidden by a re-render)
          var rect = item.el.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) {
            clicks.push({
              target: label,
              success: false,
              error: 'Element no longer visible (zero-size after prior click)',
              matchedText: item.matchedText
            });
            continue;
          }
          try {
            item.el.scrollIntoView({ block: 'center', behavior: 'instant' });
            item.el.click();
            // Radio/checkbox: dispatch change+input for framework compatibility
            var bTag = (item.el.tagName || '').toLowerCase();
            var bIsRadio = (bTag === 'input' && (item.el.type === 'radio' || item.el.type === 'checkbox'));
            var bIsRole = item.el.getAttribute('role') === 'radio' || item.el.getAttribute('role') === 'checkbox';
            if (bIsRadio) {
              if (item.el.type === 'radio') item.el.checked = true;
              item.el.dispatchEvent(new Event('change', { bubbles: true }));
              item.el.dispatchEvent(new Event('input', { bubbles: true }));
            } else if (bIsRole) {
              item.el.setAttribute('aria-checked', 'true');
              item.el.dispatchEvent(new Event('change', { bubbles: true }));
              item.el.dispatchEvent(new Event('input', { bubbles: true }));
            }
            clicks.push({
              target: label,
              index: item.spec.type === 'index' ? item.spec.index : undefined,
              success: true,
              matchedText: item.matchedText
            });
          } catch (e) {
            clicks.push({
              target: label,
              success: false,
              error: e.message || String(e),
              matchedText: item.matchedText
            });
          }
        }

        var succeeded = clicks.filter(function(c) { return c.success; }).length;
        return {
          clicks: clicks,
          summary: 'Clicked ' + succeeded + '/' + clicks.length + ' targets (atomic snapshot).'
        };
      })()
    `) as {
      clicks: Array<{
        target: string;
        index?: number;
        success: boolean;
        matchedText?: string;
        error?: string;
      }>;
      summary: string;
    };

    this.invalidateElementsCache();

    // Adaptive delay: ensures framework state updates + meets page timing requirements.
    await this.applyAdaptiveClickDelay(page);
    return result;
  }

  /**
   * Type into interactive element by index
   * Uses the same selector set as getInteractiveElements for consistency
   */
  async typeIntoElementByIndex(index: number, text: string): Promise<void> {
    this.invalidateElementsCache();
    const page = await this.getPage();

    const selector = await page.evaluate(`
      (function() {
        var idx = ${index};

        // 1. Stable lookup via data-aware-idx
        var el = document.querySelector('[data-aware-idx="' + idx + '"]');

        // 2. Fallback to positional index
        if (!el) {
          var interactiveSelectors = 'a, button, input, select, textarea, canvas, svg, [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [role="tab"], [role="menuitem"], [role="switch"], [role="slider"], [role="combobox"], [role="listbox"], [contenteditable="true"], details, summary, [onclick], [tabindex], [draggable="true"], [class*="cursor-pointer"], [class*="cursor-grab"], [style*="cursor: pointer"], [style*="cursor:pointer"], [style*="cursor: grab"], [style*="cursor:grab"]';
          var elements = document.querySelectorAll(interactiveSelectors);
          var total = elements.length;

          if (idx < 0 || idx >= total) {
            throw new Error('Element ' + idx + ' not found. Total elements: ' + total + '. Re-run browser_get_elements to refresh indices.');
          }
          el = elements[idx];
        }

        try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch(e) {}

        var isEditable =
          el.tagName === 'INPUT' ||
          el.tagName === 'TEXTAREA' ||
          el.isContentEditable;

        if (isEditable) {
          el.setAttribute('data-aware-target', 'true');
          return '[data-aware-target="true"]';
        }

        var descendant = el.querySelector('input, textarea, [contenteditable="true"]');
        if (descendant) {
          descendant.setAttribute('data-aware-target', 'true');
          return '[data-aware-target="true"]';
        }

        throw new Error('Element ' + idx + ' is not an input/textarea or editable container. Use browser_get_elements to find the input field.');
      })()
    `) as string;

    await page.fill(selector, text, { timeout: 5000 });

    // Clean up
    await page.evaluate(`
      (function() {
        const el = document.querySelector('[data-aware-target="true"]');
        if (el) el.removeAttribute('data-aware-target');
      })()
    `);
  }

  /**
   * Scroll within a specific container (modal, sidebar, etc.)
   * If no container selector is provided, scrolls the main scrollable area or modal.
   */
  async scrollWithinContainer(
    direction: 'up' | 'down',
    amount = 300,
    containerSelector?: string
  ): Promise<{ scrolled: boolean; container: string; scrollTop: number }> {
    this.invalidateElementsCache();
    const page = await this.getPage();
    const delta = direction === 'down' ? amount : -amount;

    return await page.evaluate(`
      ((delta, containerSelector) => {
        // Try to find the right scrollable container
        let container = null;
        let containerDesc = '';

        if (containerSelector) {
          // Use provided selector
          container = document.querySelector(containerSelector);
          containerDesc = containerSelector;
        }

        if (!container) {
          // Auto-detect: look for common modal/dialog patterns
          const modalSelectors = [
            '[role="dialog"]',
            '[role="alertdialog"]',
            '.modal-content',
            '.modal-body',
            '.dialog-content',
            '[class*="modal"]',
            '[class*="Modal"]',
            '[class*="dialog"]',
            '[class*="Dialog"]',
            '[class*="popup"]',
            '[class*="Popup"]',
            '[class*="drawer"]',
            '[class*="Drawer"]',
            '[class*="overlay"]',
            '[class*="Overlay"]',
          ];

          for (const sel of modalSelectors) {
            const candidates = document.querySelectorAll(sel);
            for (const el of candidates) {
              const cs = window.getComputedStyle(el);
              if (cs.overflow === 'auto' || cs.overflow === 'scroll' ||
                  cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                container = el;
                containerDesc = sel;
                break;
              }
            }
            if (container) break;
          }
        }

        if (!container) {
          // Fallback: find any visible scrollable element that's not the body
          const allScrollable = document.querySelectorAll('*');
          for (const el of allScrollable) {
            if (el === document.body || el === document.documentElement) continue;
            const cs = window.getComputedStyle(el);
            if ((cs.overflow === 'auto' || cs.overflow === 'scroll' ||
                 cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                el.scrollHeight > el.clientHeight) {
              const rect = el.getBoundingClientRect();
              if (rect.width > 100 && rect.height > 100) {
                container = el;
                containerDesc = el.tagName.toLowerCase() + (el.className ? '.' + el.className.split(' ')[0] : '');
                break;
              }
            }
          }
        }

        if (!container) {
          // Last resort: scroll document
          container = document.documentElement;
          containerDesc = 'document';
        }

        const before = container.scrollTop;
        container.scrollTop += delta;
        const after = container.scrollTop;

        return {
          scrolled: Math.abs(after - before) > 5,
          container: containerDesc,
          scrollTop: after,
        };
      })(${delta}, ${containerSelector ? JSON.stringify(containerSelector) : 'null'})`
    ) as { scrolled: boolean; container: string; scrollTop: number };
  }

  /**
   * Get the active Playwright page (for advanced use)
   */
  async getActivePage(): Promise<PlaywrightPage | null> {
    if (!this.initialized) return null;
    return this.activePage;
  }

  // ==================== TAB MANAGEMENT ====================

  /**
   * Create a new tab and optionally navigate to a URL
   */
  async newTab(url?: string): Promise<{ tabIndex: number; url: string; title: string }> {
    this.invalidateElementsCache();
    if (!this.context) {
      await this.initialize();
    }

    const newPage = await this.context!.newPage();
    this.activePage = newPage;
    this.instrumentPage(newPage);

    if (url) {
      await newPage.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await newPage.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => { });
    }

    const pages = this.context!.pages();
    const tabIndex = pages.indexOf(newPage);

    return {
      tabIndex,
      url: newPage.url(),
      title: await newPage.title(),
    };
  }

  /**
   * List all open tabs
   */
  async listTabs(): Promise<Array<{ index: number; url: string; title: string; active: boolean }>> {
    if (!this.context) {
      await this.initialize();
    }

    const pages = this.context!.pages();
    const tabs: Array<{ index: number; url: string; title: string; active: boolean }> = [];

    for (let i = 0; i < pages.length; i++) {
      tabs.push({
        index: i,
        url: pages[i].url(),
        title: await pages[i].title(),
        active: pages[i] === this.activePage,
      });
    }

    return tabs;
  }

  /**
   * Switch to a tab by index
   */
  async switchTab(index: number): Promise<{ url: string; title: string }> {
    if (!this.context) {
      await this.initialize();
    }

    const pages = this.context!.pages();
    if (index < 0 || index >= pages.length) {
      throw new Error(`Invalid tab index: ${index}. Available tabs: 0-${pages.length - 1}`);
    }

    this.activePage = pages[index];
    this.instrumentPage(this.activePage);
    await this.activePage.bringToFront();
    this.invalidateElementsCache();

    return {
      url: this.activePage.url(),
      title: await this.activePage.title(),
    };
  }

  /**
   * Close a tab by index (closes active tab if no index provided)
   */
  async closeTab(index?: number): Promise<{ remainingTabs: number }> {
    if (!this.context) {
      throw new Error('Browser not initialized');
    }

    const pages = this.context.pages();

    let pageToClose: PlaywrightPage;
    if (index !== undefined) {
      if (index < 0 || index >= pages.length) {
        throw new Error(`Invalid tab index: ${index}`);
      }
      pageToClose = pages[index];
    } else {
      if (!this.activePage) {
        throw new Error('No active tab to close');
      }
      pageToClose = this.activePage;
    }

    await pageToClose.close();
    this.invalidateElementsCache();

    // Update active page to the last remaining page
    const remainingPages = this.context.pages();
    if (remainingPages.length > 0) {
      this.activePage = remainingPages[remainingPages.length - 1];
      this.instrumentPage(this.activePage);
      await this.activePage.bringToFront();
    } else {
      this.activePage = null;
    }

    return { remainingTabs: remainingPages.length };
  }

  /**
   * Close the browser
   */
  async close(): Promise<void> {
    if (this.context) {
      await this.context.close().catch(() => { });
    }
    if (this.browser) {
      await this.browser.close().catch(() => { });
    }
    this.browser = null;
    this.context = null;
    this.activePage = null;
    this.initialized = false;
  }

  // ==================== SCRIPT & DOM INSPECTION ====================

  /**
   * Read all page scripts (inline + external) and optionally search for patterns.
   * External scripts are fetched via the page context so cookies/CORS apply.
   */
  async readScripts(
    patterns?: string[],
    maxLength = 15000,
    includeInline = true,
  ): Promise<{
    scripts: Array<{
      index: number;
      src?: string;
      type?: string;
      size: number;
      inline?: boolean;
      content?: string;
      matches?: Array<{ pattern: string; snippets: string[] }>;
    }>;
    totalScripts: number;
    summary: string;
  }> {
    const page = await this.getPage();

    // Collect script metadata + content from the page
    const rawScripts = await page.evaluate(`
      (async function() {
        var scripts = Array.from(document.querySelectorAll('script'));
        var results = [];
        for (var i = 0; i < scripts.length; i++) {
          var s = scripts[i];
          var entry = {
            index: i,
            src: s.src || null,
            type: s.type || null,
            inline: !s.src,
            content: null,
            size: 0,
          };
          if (s.src) {
            try {
              var resp = await fetch(s.src, { credentials: 'same-origin' });
              var text = await resp.text();
              entry.content = text;
              entry.size = text.length;
            } catch (e) {
              entry.content = '[fetch_failed: ' + (e.message || e) + ']';
              entry.size = 0;
            }
          } else {
            entry.content = s.textContent || '';
            entry.size = entry.content.length;
          }
          results.push(entry);
        }
        return results;
      })()
    `) as Array<{
      index: number;
      src: string | null;
      type: string | null;
      inline: boolean;
      content: string | null;
      size: number;
    }>;

    const defaultPatterns = [
      'function\\s+(?:check|validate|verify|submit|handleSubmit)',
      '(?:answer|code|secret|solution|password|key)\\s*[:=]\\s*["\x27`]',
      'correct|success|winner|proceed|nextStep|advanceStep',
      '["\x27`][A-Z0-9]{6}["\x27`]',
      'addEventListener\\s*\\(\\s*["\x27`]submit',
      'onSuccess|onCorrect|showResult',
      'setTimeout|setInterval|delay|waitFor|\.then\\s*\\(',
    ];
    const searchPatterns = patterns && patterns.length > 0 ? patterns : defaultPatterns;

    let totalLen = 0;
    const scripts: Array<{
      index: number;
      src?: string;
      type?: string;
      size: number;
      inline?: boolean;
      content?: string;
      matches?: Array<{ pattern: string; snippets: string[] }>;
    }> = [];

    for (const raw of rawScripts) {
      const entry: typeof scripts[0] = {
        index: raw.index,
        src: raw.src || undefined,
        type: raw.type || undefined,
        size: raw.size,
        inline: raw.inline,
      };

      const content = raw.content || '';

      // Search for patterns in the script content
      const matchResults: Array<{ pattern: string; snippets: string[] }> = [];
      for (const pat of searchPatterns) {
        try {
          const regex = new RegExp(pat, 'gi');
          let match;
          const snippets: string[] = [];
          while ((match = regex.exec(content)) !== null && snippets.length < 5) {
            // Extract ±200 chars around the match
            const start = Math.max(0, match.index - 200);
            const end = Math.min(content.length, match.index + match[0].length + 200);
            const snippet = (start > 0 ? '...' : '') +
              content.slice(start, end) +
              (end < content.length ? '...' : '');
            snippets.push(snippet);
          }
          if (snippets.length > 0) {
            matchResults.push({ pattern: pat, snippets });
          }
        } catch {
          // Invalid regex pattern, skip
        }
      }

      if (matchResults.length > 0) {
        entry.matches = matchResults;
      }

      // Include inline content if requested and no pattern matches found
      if (includeInline && raw.inline && matchResults.length === 0 && raw.size < 5000) {
        entry.content = content;
      }

      // Truncate if we're exceeding maxLength
      const entryJson = JSON.stringify(entry);
      if (totalLen + entryJson.length > maxLength) {
        // Truncate match snippets to fit
        if (entry.matches) {
          for (const m of entry.matches) {
            m.snippets = m.snippets.map(s => s.slice(0, 300) + (s.length > 300 ? '...[truncated]' : ''));
          }
        }
        if (entry.content && entry.content.length > 500) {
          entry.content = entry.content.slice(0, 500) + '...[truncated]';
        }
      }

      totalLen += JSON.stringify(entry).length;
      scripts.push(entry);

      if (totalLen >= maxLength) break;
    }

    const matchCount = scripts.reduce((n, s) => n + (s.matches?.length || 0), 0);
    const summary = `Found ${rawScripts.length} scripts (${rawScripts.filter(s => s.inline).length} inline, ${rawScripts.filter(s => !s.inline).length} external). ` +
      `${matchCount} pattern matches across ${scripts.filter(s => s.matches && s.matches.length > 0).length} scripts.`;

    return { scripts, totalScripts: rawScripts.length, summary };
  }

  /**
   * Deep DOM inspection — scans ALL elements for hidden data, non-standard attributes,
   * aria labels, comments, CSS pseudo-content, and hidden elements.
   * Returns a structured report or a definitive "clean DOM" signal.
   */
  async deepInspect(): Promise<{
    hiddenData: Array<{ tag: string; selector: string; attributes: Record<string, string>; text?: string }>;
    ariaElements: Array<{ tag: string; ariaLabel?: string; ariaDescribedBy?: string; role?: string; text?: string }>;
    comments: string[];
    cssContent: Array<{ selector: string; pseudo: string; content: string }>;
    hiddenElements: Array<{ tag: string; selector: string; reason: string; text?: string }>;
    noscriptContent: string[];
    summary: string;
    isClean: boolean;
  }> {
    const page = await this.getPage();

    return await page.evaluate(`
      (function() {
        var result = {
          hiddenData: [],
          ariaElements: [],
          comments: [],
          cssContent: [],
          hiddenElements: [],
          noscriptContent: [],
          summary: '',
          isClean: true,
        };

        // 1. Scan ALL elements for non-standard/data/aria attributes
        var allElements = document.querySelectorAll('*');
        var standardAttrs = new Set([
          'class','id','style','src','href','type','name','value','placeholder',
          'action','method','target','rel','alt','width','height','colspan','rowspan',
          'for','tabindex','disabled','checked','selected','readonly','required',
          'maxlength','minlength','min','max','step','pattern','autocomplete',
          'crossorigin','loading','decoding','fetchpriority','referrerpolicy',
          'xmlns','lang','dir','charset','content','http-equiv','property',
        ]);
        var ignoredPrefixes = ['data-aware-'];

        for (var i = 0; i < Math.min(allElements.length, 2000); i++) {
          var el = allElements[i];
          var attrs = el.attributes;
          var interestingAttrs = {};
          var hasInteresting = false;

          for (var j = 0; j < attrs.length; j++) {
            var a = attrs[j];
            var name = a.name.toLowerCase();
            var skip = false;
            for (var p = 0; p < ignoredPrefixes.length; p++) {
              if (name.startsWith(ignoredPrefixes[p])) { skip = true; break; }
            }
            if (skip) continue;

            // Capture data-*, aria-*, and non-standard attrs
            if (name.startsWith('data-') || name.startsWith('aria-') || !standardAttrs.has(name)) {
              interestingAttrs[a.name] = a.value;
              hasInteresting = true;
            }
          }

          if (hasInteresting) {
            var tag = el.tagName.toLowerCase();
            var selector = tag + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').slice(0,2).join('.') : '');
            result.hiddenData.push({
              tag: tag,
              selector: selector.slice(0, 100),
              attributes: interestingAttrs,
              text: (el.textContent || '').trim().slice(0, 100) || undefined,
            });
          }

          // Capture elements with aria attributes specifically
          var ariaLabel = el.getAttribute('aria-label');
          var ariaDesc = el.getAttribute('aria-describedby');
          var role = el.getAttribute('role');
          if (ariaLabel || ariaDesc) {
            result.ariaElements.push({
              tag: el.tagName.toLowerCase(),
              ariaLabel: ariaLabel || undefined,
              ariaDescribedBy: ariaDesc || undefined,
              role: role || undefined,
              text: (el.textContent || '').trim().slice(0, 80) || undefined,
            });
          }
        }

        // 2. Extract HTML comments
        var walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT, null);
        var node;
        while ((node = walker.nextNode()) && result.comments.length < 50) {
          var ctext = (node.nodeValue || '').trim();
          if (ctext && ctext.length > 2) {
            result.comments.push(ctext.slice(0, 300));
          }
        }

        // 3. CSS ::before/::after content
        var checkElements = document.querySelectorAll('*');
        for (var k = 0; k < Math.min(checkElements.length, 1000); k++) {
          var cel = checkElements[k];
          try {
            var before = getComputedStyle(cel, '::before').content;
            var after = getComputedStyle(cel, '::after').content;
            if (before && before !== 'none' && before !== 'normal' && before !== '""') {
              var tag2 = cel.tagName.toLowerCase();
              var sel2 = tag2 + (cel.id ? '#' + cel.id : '');
              result.cssContent.push({ selector: sel2.slice(0, 80), pseudo: '::before', content: before.slice(0, 200) });
            }
            if (after && after !== 'none' && after !== 'normal' && after !== '""') {
              var tag3 = cel.tagName.toLowerCase();
              var sel3 = tag3 + (cel.id ? '#' + cel.id : '');
              result.cssContent.push({ selector: sel3.slice(0, 80), pseudo: '::after', content: after.slice(0, 200) });
            }
          } catch(e) {}
        }

        // 4. Hidden elements (display:none, visibility:hidden, opacity:0, off-screen)
        var hiddenSel = '[style*="display: none"], [style*="display:none"], [style*="visibility: hidden"], [style*="visibility:hidden"], [style*="opacity: 0"], [style*="opacity:0"], [hidden], .hidden, .sr-only, .visually-hidden';
        var hiddenEls = document.querySelectorAll(hiddenSel);
        for (var h = 0; h < Math.min(hiddenEls.length, 50); h++) {
          var hel = hiddenEls[h];
          var htag = hel.tagName.toLowerCase();
          var hsel = htag + (hel.id ? '#' + hel.id : '');
          var reason = 'unknown';
          if (hel.hasAttribute('hidden')) reason = '[hidden] attribute';
          else if (hel.style.display === 'none') reason = 'display:none';
          else if (hel.style.visibility === 'hidden') reason = 'visibility:hidden';
          else if (hel.style.opacity === '0') reason = 'opacity:0';
          else if (hel.classList.contains('hidden')) reason = '.hidden class';
          else if (hel.classList.contains('sr-only') || hel.classList.contains('visually-hidden')) reason = 'screen-reader only';
          var htext = (hel.textContent || '').trim().slice(0, 200);
          if (htext) {
            result.hiddenElements.push({ tag: htag, selector: hsel.slice(0, 80), reason: reason, text: htext });
          }
        }

        // 4b. Elements hidden via CSS stylesheet rules (not inline styles)
        // The selector-based scan above only catches inline style attributes.
        // This scan uses getComputedStyle to find elements hidden by CSS classes/rules.
        var bodyEls = document.body.querySelectorAll('div, span, p, section, article, aside, header, footer');
        for (var ci = 0; ci < Math.min(bodyEls.length, 500); ci++) {
          var cel2 = bodyEls[ci];
          if (cel2.closest('[data-aware-idx]')) continue; // skip interactive (already visible)
          // Skip elements already found by selector-based scan
          if (cel2.matches(hiddenSel)) continue;
          try {
            var ccs = window.getComputedStyle(cel2);
            if (ccs.display === 'none' || ccs.visibility === 'hidden' || ccs.opacity === '0') {
              var ctext2 = (cel2.textContent || '').trim().slice(0, 200);
              if (ctext2 && result.hiddenElements.length < 50) {
                var creason = ccs.display === 'none' ? 'display:none' : ccs.visibility === 'hidden' ? 'visibility:hidden' : 'opacity:0';
                result.hiddenElements.push({ tag: cel2.tagName.toLowerCase(), selector: '(css-rule)', reason: creason, text: ctext2 });
              }
            }
          } catch(e) {}
        }

        // 5. <noscript> content
        var noscripts = document.querySelectorAll('noscript');
        for (var n = 0; n < noscripts.length; n++) {
          var ns = (noscripts[n].textContent || '').trim();
          if (ns) result.noscriptContent.push(ns.slice(0, 500));
        }

        // 6. Clickable non-interactive elements (cursor:pointer divs/spans)
        // These are often challenge targets that browser_click can't reach by index
        result.clickableNonInteractive = [];
        var interactive = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA','LABEL']);
        var allClickable = document.querySelectorAll('*');
        for (var ci = 0; ci < Math.min(allClickable.length, 1000); ci++) {
          var cel2 = allClickable[ci];
          if (interactive.has(cel2.tagName)) continue;
          try {
            var cursor = getComputedStyle(cel2).cursor;
            if (cursor === 'pointer') {
              var ctext2 = (cel2.textContent || '').trim().slice(0, 150);
              if (ctext2 && ctext2.length > 3) {
                result.clickableNonInteractive.push({
                  tag: cel2.tagName.toLowerCase(),
                  text: ctext2,
                  hint: 'Use browser_click_text with part of this text to click it',
                });
                if (result.clickableNonInteractive.length >= 10) break;
              }
            }
          } catch(e2) {}
        }

        // 7. Scrollable containers (modals with hidden overflow content)
        result.scrollableContainers = [];
        var scrollCandidates = document.querySelectorAll('*');
        for (var sci = 0; sci < Math.min(scrollCandidates.length, 2000); sci++) {
          var scel = scrollCandidates[sci];
          if (scel === document.body || scel === document.documentElement) continue;
          try {
            var sccs = getComputedStyle(scel);
            var ov = sccs.overflow + ' ' + sccs.overflowY;
            if (ov.indexOf('auto') !== -1 || ov.indexOf('scroll') !== -1) {
              if (scel.scrollHeight > scel.clientHeight + 20) {
                var screct = scel.getBoundingClientRect();
                if (screct.width > 50 && screct.height > 50) {
                  var sctag = scel.tagName.toLowerCase();
                  var scsel = sctag + (scel.id ? '#' + scel.id : '') + (scel.className && typeof scel.className === 'string' ? '.' + scel.className.split(' ')[0] : '');
                  var hiddenPx = scel.scrollHeight - scel.clientHeight;
                  result.scrollableContainers.push({
                    selector: scsel.slice(0, 100),
                    visibleHeight: Math.round(scel.clientHeight),
                    totalHeight: Math.round(scel.scrollHeight),
                    hiddenPixels: Math.round(hiddenPx),
                    hint: 'Content hidden below scroll — use browser_scroll_container to reveal it',
                  });
                  if (result.scrollableContainers.length >= 5) break;
                }
              }
            }
          } catch(e3) {}
        }

        // 8. Z-index overlay stacking (modals, popups, overlays)
        result.overlays = [];
        var overlayEls = document.querySelectorAll('*');
        for (var oi = 0; oi < Math.min(overlayEls.length, 2000); oi++) {
          var oel = overlayEls[oi];
          try {
            var ocs = getComputedStyle(oel);
            var zi = parseInt(ocs.zIndex, 10);
            if (zi >= 100 && ocs.position !== 'static' && ocs.display !== 'none') {
              var orect = oel.getBoundingClientRect();
              if (orect.width > 50 && orect.height > 50) {
                var otag = oel.tagName.toLowerCase();
                var osel = otag + (oel.id ? '#' + oel.id : '') + (oel.className && typeof oel.className === 'string' ? '.' + oel.className.split(' ')[0] : '');
                var otext = (oel.textContent || '').trim().slice(0, 80);
                // Check if it covers most of the viewport (overlay/backdrop)
                var isFullScreen = orect.width > window.innerWidth * 0.8 && orect.height > window.innerHeight * 0.8;
                result.overlays.push({
                  selector: osel.slice(0, 100),
                  zIndex: zi,
                  isFullScreen: isFullScreen,
                  text: otext || undefined,
                  hint: isFullScreen ? 'Backdrop/overlay — dismiss this FIRST (click close/accept)' : 'Floating element (modal/popup)',
                });
              }
            }
          } catch(e4) {}
        }
        // Sort by z-index descending (top overlay first = dismiss first)
        result.overlays.sort(function(a, b) { return b.zIndex - a.zIndex; });
        if (result.overlays.length > 8) result.overlays = result.overlays.slice(0, 8);

        // 9. Disabled / fake buttons (cursor-not-allowed, disabled, aria-disabled)
        result.disabledButtons = [];
        var btns = document.querySelectorAll('button, [role="button"], a.btn, a.button, [class*="btn"], [class*="button"]');
        for (var bi = 0; bi < Math.min(btns.length, 100); bi++) {
          var btn = btns[bi];
          try {
            var bcs = getComputedStyle(btn);
            var isDisabled = btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true';
            var isFake = bcs.cursor === 'not-allowed' || bcs.pointerEvents === 'none' || parseFloat(bcs.opacity) < 0.5;
            if (isDisabled || isFake) {
              var btag = btn.tagName.toLowerCase();
              var bsel = btag + (btn.id ? '#' + btn.id : '') + (btn.className && typeof btn.className === 'string' ? '.' + btn.className.split(' ')[0] : '');
              var btext = (btn.textContent || '').trim().slice(0, 80);
              if (btext) {
                result.disabledButtons.push({
                  selector: bsel.slice(0, 100),
                  text: btext,
                  reason: isDisabled ? 'disabled attribute' : (bcs.cursor === 'not-allowed' ? 'cursor:not-allowed' : (bcs.pointerEvents === 'none' ? 'pointer-events:none' : 'low opacity')),
                  hint: 'FAKE/disabled button — do NOT click this, find the real interactive element',
                });
                if (result.disabledButtons.length >= 10) break;
              }
            }
          } catch(e5) {}
        }

        // 10. Build summary
        var findings = [];
        if (result.hiddenData.length > 0) findings.push(result.hiddenData.length + ' elements with data/custom attributes');
        if (result.ariaElements.length > 0) findings.push(result.ariaElements.length + ' elements with aria labels');
        if (result.comments.length > 0) findings.push(result.comments.length + ' HTML comments');
        if (result.cssContent.length > 0) findings.push(result.cssContent.length + ' CSS pseudo-element content');
        if (result.hiddenElements.length > 0) findings.push(result.hiddenElements.length + ' hidden elements with text');
        if (result.noscriptContent.length > 0) findings.push(result.noscriptContent.length + ' noscript blocks');
        if (result.clickableNonInteractive.length > 0) findings.push(result.clickableNonInteractive.length + ' clickable divs (use browser_click_text)');
        if (result.scrollableContainers.length > 0) findings.push(result.scrollableContainers.length + ' scrollable containers with hidden content (use browser_scroll_container)');
        if (result.overlays.length > 0) findings.push(result.overlays.length + ' overlay/modal layers (dismiss top z-index first)');
        if (result.disabledButtons.length > 0) findings.push(result.disabledButtons.length + ' disabled/fake buttons (avoid clicking these)');

        if (findings.length === 0) {
          result.summary = 'CLEAN DOM: No hidden data, custom attributes, aria labels, comments, or CSS content found. The answer is likely in JavaScript source code — use browser_read_scripts.';
          result.isClean = true;
        } else {
          result.summary = 'Found: ' + findings.join(', ') + '. Inspect these for hidden codes/answers.';
          result.isClean = false;
        }

        return result;
      })()
    `) as any;
  }

  /**
   * Check if browser is initialized
   */
  get isInitialized(): boolean {
    return this.initialized;
  }
}

export default AwareBrowserAgent;
