---
title: "shadcn/ui Skills for Next.js 16"
description: "Installation, components, blocks, forms, theming, and MCP guidance for shadcn/ui in modern Next.js projects using pnpm"
keywords: ["shadcn", "ui", "Next.js", "pnpm", "blocks", "sonner", "forms", "dark-mode", "mcp"]
---

# shadcn/ui Skills

**Status:** Next.js 16 ready  
**Package Manager:** pnpm (required)  
**Official Docs:**  
- [Installation (Next.js)](https://ui.shadcn.com/docs/installation/next)  
- [Components](https://ui.shadcn.com/docs/components)  
- [Blocks](https://ui.shadcn.com/blocks)  
- [Sonner (toast replacement)](https://ui.shadcn.com/docs/components/sonner)  
- [Forms](https://ui.shadcn.com/docs/components/form)  
- [Dark Mode (Next.js)](https://ui.shadcn.com/docs/dark-mode/next)  
- [MCP Server](https://ui.shadcn.com/docs/mcp)  
- [LLM Guidelines](https://ui.shadcn.com/llms.txt)

---

## Table of Contents

1. [Installation & Setup](#installation--setup)
2. [Project Configuration (Next.js 16)](#project-configuration-nextjs-16)
3. [Components & Usage](#components--usage)
4. [Blocks](#blocks)
5. [Forms](#forms)
6. [Sonner (Toast Replacement)](#sonner-toast-replacement)
7. [Dark Mode](#dark-mode)
8. [MCP Integration](#mcp-integration)
9. [Best Practices](#best-practices)

---

## Installation & Setup

- Use pnpm for all commands.
- Scaffold shadcn/ui in an existing Next.js 16 app:
  ```bash
  pnpm dlx shadcn@latest init
  ```
  - Accept prompts for **Next.js** + **TypeScript**.
  - CLI creates `components.json` and installs required deps (Tailwind, class utilities).
- Add components when needed (keeps bundle small):
  ```bash
  pnpm dlx shadcn@latest add button card input textarea select
  # add blocks or utilities on demand
  ```
- After adding components, run:
  ```bash
  pnpm lint && pnpm test # if configured
  pnpm dev               # verify styles render
  ```

---

## Project Configuration (Next.js 16)

- Tailwind is required. Ensure `tailwind.config.(ts|js)` includes shadcn paths:
  ```ts
  // tailwind.config.ts
  import type { Config } from "tailwindcss"
  import { fontFamily } from "tailwindcss/defaultTheme"

  const config: Config = {
    darkMode: ["class"],
    content: [
      "./app/**/*.{ts,tsx}",
      "./components/**/*.{ts,tsx}",
      "./src/**/*.{ts,tsx}",
    ],
    theme: {
      extend: {
        fontFamily: {
          sans: ["var(--font-sans)", ...fontFamily.sans],
        },
      },
    },
    plugins: [require("tailwindcss-animate")],
  }

  export default config
  ```
- Use App Router and Server Components by default; mark client files with `"use client"`.
- Keep `globals.css` with CSS variables from shadcn init; do not remove the color tokens.

---

## Components & Usage

- Components live in `components/ui`. Import directly:
  ```tsx
  import { Button } from "@/components/ui/button"

  export function CTA() {
    return <Button size="lg">Get started</Button>
  }
  ```
- Many components support `asChild` to compose with links:
  ```tsx
  <Button asChild>
    <Link href="/docs">Docs</Link>
  </Button>
  ```
- Keep icons in `components/ui/icons` or use `lucide-react` (installed during init).
- Reference component docs for props and accessibility expectations.

---

## Blocks

- Blocks are higher-level page sections from [ui.shadcn.com/blocks](https://ui.shadcn.com/blocks).
- Add a block via CLI (preferred to avoid copy/paste drift):
  ```bash
  pnpm dlx shadcn@latest add blocks/application-shells/sidebar-02
  ```
- Blocks follow the same theming and Tailwind tokens as core components; adjust spacing/tokens instead of rewriting styles.
- Keep blocks in `components/blocks/*` to avoid mixing with low-level UI primitives.

---

## Forms

- Use the provided Form primitives with `react-hook-form` + `@hookform/resolvers/zod`:
  ```tsx
  "use client"

  import { zodResolver } from "@hookform/resolvers/zod"
  import { useForm } from "react-hook-form"
  import { z } from "zod"
  import { Button } from "@/components/ui/button"
  import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
  import { Input } from "@/components/ui/input"

  const schema = z.object({
    email: z.string().email(),
    name: z.string().min(2),
  })

  export function ProfileForm() {
    const form = useForm<z.infer<typeof schema>>({
      resolver: zodResolver(schema),
      defaultValues: { email: "", name: "" },
    })

    return (
      <Form {...form}>
        <form onSubmit={form.handleSubmit(console.log)} className="space-y-4">
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input placeholder="you@example.com" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit">Save</Button>
        </form>
      </Form>
    )
  }
  ```
- Keep validation schemas colocated; surface errors via `FormMessage`.

---

## Sonner (Toast Replacement)

- `toast` is **deprecated**; use Sonner.
- Add the Sonner component via CLI:
  ```bash
  pnpm dlx shadcn@latest add sonner
  ```
- Mount once in your root layout or top-level provider:
```tsx
import { Toaster } from "@/components/ui/sonner"
import { toast } from "sonner"

  export function RootProviders({ children }: { children: React.ReactNode }) {
    return (
      <>
        {children}
        <Toaster richColors position="top-right" />
      </>
    )
  }

  // usage
  toast.success("Profile saved")
  ```
- Keep Sonner provider outside `app/(marketing)` vs `app/(dashboard)` duplication to avoid multiple toasters.

---

## Dark Mode

- Use class-based theming with `next-themes`.
- Example provider (`components/theme-provider.tsx`):
  ```tsx
  "use client"

  import { ThemeProvider as NextThemesProvider } from "next-themes"

  export function ThemeProvider({ children }: { children: React.ReactNode }) {
    return (
      <NextThemesProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        {children}
      </NextThemesProvider>
    )
  }
  ```
- Wrap the App Router layout:
  ```tsx
  // app/layout.tsx
  import { ThemeProvider } from "@/components/theme-provider"

  export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
      <html lang="en" suppressHydrationWarning>
        <body>
          <ThemeProvider>{children}</ThemeProvider>
        </body>
      </html>
    )
  }
  ```
- Keep `suppressHydrationWarning` on `<html>` to avoid mismatches when switching themes.

---

## MCP Integration

- shadcn/ui ships an MCP server (see [docs](https://ui.shadcn.com/docs/mcp)) so agents can browse/add components and blocks safely.
- Register the server in your MCP client config, pointing at your project root where `components.json` lives.
- Prefer MCP-driven adds over manual copy/paste to keep component versions consistent with the catalog.

---

## Best Practices

1. **Stay modular:** Add only the components/blocks you need; trim unused files to keep bundles small.
2. **Respect tokens:** Do not hardcode colors; use the CSS variables set up by init.
3. **Accessibility:** Keep aria labels, roles, and keyboard interactions from the upstream examples.
4. **Typography:** Use CSS variables + `next/font` to load fonts; wire them into `--font-sans` in `globals.css`.
5. **LLM usage:** Follow [llms.txt](https://ui.shadcn.com/llms.txt) when generating code; prefer pnpm commands and Sonner over legacy toast.
