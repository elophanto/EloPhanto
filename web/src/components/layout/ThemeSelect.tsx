import { useEffect, useRef, useState } from "react";
import { Palette, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";

/**
 * Sidebar theme picker — a dropdown of all templates with swatches.
 * Opens upward (it sits near the sidebar bottom). Collapses to just
 * the palette icon when the sidebar is collapsed.
 */
export function ThemeSelect({ collapsed }: { collapsed: boolean }) {
  const { theme, themes, themeDef, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative w-full">
      <button
        onClick={() => setOpen((v) => !v)}
        title="Select theme"
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-foreground/5",
          collapsed && "justify-center",
        )}
      >
        <Palette className="size-3.5 shrink-0" />
        {!collapsed && (
          <>
            <span className="font-mono text-[10px] uppercase tracking-[0.1em]">
              {themeDef.label}
            </span>
            <span
              className="ml-auto size-3 rounded-full border border-border/60"
              style={{ background: themeDef.swatch.accent }}
            />
          </>
        )}
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute bottom-full left-0 z-50 mb-1 w-44 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
        >
          {themes.map((t) => {
            const active = t.id === theme;
            return (
              <button
                key={t.id}
                role="option"
                aria-selected={active}
                onClick={() => {
                  setTheme(t.id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-foreground/[5%]",
                  active && "bg-foreground/[3%]",
                )}
              >
                {/* swatch */}
                <span
                  className="flex size-6 shrink-0 items-center overflow-hidden rounded-md border border-border/50"
                  style={{ background: t.swatch.bg }}
                >
                  <span
                    className="ml-1 size-2.5 rounded-full"
                    style={{ background: t.swatch.accent }}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[10px] uppercase tracking-[0.1em]">
                    {t.label}
                  </span>
                  <span className="block font-mono text-[8px] uppercase tracking-[0.1em] text-muted-foreground/50">
                    {t.mode}
                  </span>
                </span>
                {active && <Check className="size-3 shrink-0 text-primary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
