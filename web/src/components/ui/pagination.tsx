import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface PaginationBarProps {
  page: number;
  totalPages: number;
  total: number;
  from: number;
  to: number;
  setPage: (p: number) => void;
  /** Singular noun for the count label, e.g. "goal" → "1–25 of 312 goals". */
  noun?: string;
  /** Explicit plural — only needed for irregulars (e.g. "company" → "companies"). */
  nounPlural?: string;
}

/**
 * Windowed page list with ellipsis: always shows first + last + a
 * window around the current page. `0` marks a gap (rendered as "…").
 * e.g. page 6 of 20 → [1, 0, 5, 6, 7, 0, 20].
 */
function pageWindow(page: number, totalPages: number): number[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const out: number[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(totalPages - 1, page + 1);
  if (start > 2) out.push(0); // leading gap
  for (let p = start; p <= end; p++) out.push(p);
  if (end < totalPages - 1) out.push(0); // trailing gap
  out.push(totalPages);
  return out;
}

/**
 * Compact pagination control — "‹ 1 … 5 6 7 … 20 ›" + count label.
 * Hides itself when everything fits on one page.
 */
export function PaginationBar({
  page,
  totalPages,
  total,
  from,
  to,
  setPage,
  noun = "item",
  nounPlural,
}: PaginationBarProps) {
  if (totalPages <= 1) return null;
  const label = total === 1 ? noun : (nounPlural ?? `${noun}s`);

  const arrowBtn =
    "flex size-6 items-center justify-center rounded-md border border-border/50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed hover:enabled:border-border hover:enabled:bg-foreground/[3%]";

  return (
    <div className="flex flex-col items-center gap-1.5 py-3">
      <div className="flex items-center gap-1">
        <button
          className={arrowBtn}
          onClick={() => setPage(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-3.5" />
        </button>

        {pageWindow(page, totalPages).map((p, i) =>
          p === 0 ? (
            <span
              key={`gap-${i}`}
              className="px-1 font-mono text-[10px] text-muted-foreground/40"
            >
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => setPage(p)}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
              className={cn(
                "flex h-6 min-w-6 items-center justify-center rounded-md border px-1.5 font-mono text-[10px] transition-colors",
                p === page
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border/50 text-muted-foreground hover:border-border hover:bg-foreground/[3%]",
              )}
            >
              {p}
            </button>
          ),
        )}

        <button
          className={arrowBtn}
          onClick={() => setPage(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
        >
          <ChevronRight className="size-3.5" />
        </button>
      </div>
      <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
        {from}–{to} of {total} {label}
      </span>
    </div>
  );
}
