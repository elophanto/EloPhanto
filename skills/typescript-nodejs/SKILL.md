# TypeScript & Node.js Development

## Description

TypeScript and Node.js coding guide — covers strict TypeScript configuration, async patterns, error handling with Zod, Node.js APIs, testing with Vitest, and project structure conventions.

## Triggers

- typescript
- javascript
- node
- nodejs
- npm
- pnpm
- express
- zod
- vitest
- jest
- ts
- js

## Instructions

### 1. Before Writing Code

1. Read the project's `tsconfig.json` and `package.json` to understand config and dependencies.
2. Check existing patterns — naming conventions, module structure, export style.
3. For non-trivial features, outline the approach before implementing.
4. Identify edge cases: null/undefined inputs, network failures, type mismatches.

### 2. TypeScript Style

- Strict mode: always `"strict": true` in tsconfig
- `const` by default, `let` only when mutation is needed, never `var`
- `interface` for object shapes, `type` for unions/intersections/mapped types
- `async`/`await` over raw Promises or callbacks
- Named exports over default exports (except Next.js pages/layouts)
- Explicit return types on exported functions
- Avoid `any` — use `unknown` and narrow with type guards

```typescript
// tsconfig.json essentials
{
  "compilerOptions": {
    "strict": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true
  }
}
```

### 3. Error Handling

```typescript
// Result pattern with typed errors
type Result<T> = { success: true; data: T } | { success: false; error: string };

async function fetchData(url: string): Promise<Result<Data>> {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return { success: false, error: `HTTP ${response.status}` };
    }
    const data = await response.json();
    return { success: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return { success: false, error: message };
  }
}
```

#### Input Validation with Zod
```typescript
import { z } from "zod";

const UserSchema = z.object({
  name: z.string().min(1),
  email: z.string().email(),
  age: z.number().int().positive().optional(),
});

type User = z.infer<typeof UserSchema>;

function createUser(input: unknown): User {
  return UserSchema.parse(input); // throws ZodError on invalid input
}

// Or safe parsing (no throw)
const result = UserSchema.safeParse(input);
if (!result.success) {
  console.error(result.error.flatten());
  return;
}
const user = result.data; // fully typed
```

### 4. Node.js Patterns

```typescript
// Use node: prefix for built-in modules
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { existsSync } from "node:fs";

// Async file operations (never use sync in production)
const content = await readFile(filePath, "utf-8");
await mkdir(dirPath, { recursive: true });
await writeFile(outputPath, data, "utf-8");
```

#### Timeouts with AbortController
```typescript
async function fetchWithTimeout(url: string, ms: number): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}
```

#### Subprocess Execution
```typescript
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const { stdout, stderr } = await execFileAsync("git", ["status"], {
  cwd: projectRoot,
  timeout: 10_000,
});
```

#### Environment Variables
```typescript
// Type-safe env access
function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Missing env var: ${key}`);
  return value;
}

const port = parseInt(process.env.PORT ?? "3000", 10);
```

### 5. Project Structure

```
project/
  src/
    index.ts           # entry point
    types.ts           # shared type definitions
    utils/             # utility functions
    services/          # business logic
  test/
    *.test.ts          # test files mirror src/ structure
  package.json
  tsconfig.json
  .env.example
```

**Conventions:**
- One module per file, named after the primary export
- Barrel exports (`index.ts`) only at package boundaries, not everywhere
- Keep `types.ts` separate from implementation
- Co-locate tests next to source or in a parallel `test/` directory

### 6. Testing

```typescript
// Vitest (recommended — fast, ESM-native, Jest-compatible API)
import { describe, it, expect, vi } from "vitest";

describe("fetchData", () => {
  it("returns data on success", async () => {
    const result = await fetchData("https://api.example.com/data");
    expect(result.success).toBe(true);
  });

  it("handles network errors", async () => {
    const result = await fetchData("https://invalid.example.com");
    expect(result.success).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("mocks external dependencies", () => {
    const mockFn = vi.fn().mockReturnValue(42);
    expect(mockFn()).toBe(42);
    expect(mockFn).toHaveBeenCalledOnce();
  });
});
```

Run: `npx vitest` (watch mode) or `npx vitest run` (single pass)

### 7. Code Review Checklist

- **Types**: No `any`, strict mode passes, return types on exports
- **Null safety**: `noUncheckedIndexedAccess` enabled, null checks before access
- **Error handling**: All async operations in try-catch, errors typed not swallowed
- **Resources**: Streams/connections closed, AbortControllers cleaned up
- **Security**: Input validated (Zod), no eval(), no unescaped user input in HTML
- **Dependencies**: Minimal, well-maintained packages; lockfile committed
- **Tests**: Coverage for happy path and error cases

### 8. Common Pitfalls

- **Forgetting `await`** — an unhandled promise silently fails
- **Using `==` instead of `===`** — TypeScript catches some but not all
- **Mutating function arguments** — always return new objects/arrays
- **Circular imports** — restructure to break the cycle, or use dynamic imports
- **Large bundle size** — check with `npx bundlesize` or build analyzer
- **Sync I/O in async context** — use `fs/promises`, not `fs.readFileSync`

## Notes

For Next.js/React-specific patterns, read the `react-best-practices` and
`composition-patterns` skills instead — this skill covers pure TypeScript
and Node.js runtime patterns.
