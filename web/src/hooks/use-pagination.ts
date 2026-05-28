import { useEffect, useMemo, useState } from "react";

export interface Pagination<T> {
  page: number;
  setPage: (p: number) => void;
  pageItems: T[];
  totalPages: number;
  total: number;
  pageSize: number;
  /** 1-based index of the first item on the current page (0 if empty). */
  from: number;
  /** 1-based index of the last item on the current page. */
  to: number;
}

/**
 * Client-side pagination over an already-filtered list.
 *
 * Resets to page 1 whenever the input length changes (e.g. the user
 * applies a search / filter) so they don't get stranded on an empty
 * trailing page. Clamps the page if the list shrinks under it.
 */
export function usePagination<T>(items: T[], pageSize = 25): Pagination<T> {
  const [page, setPage] = useState(1);
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Reset to page 1 when the result set changes size (new filter/search).
  useEffect(() => {
    setPage(1);
  }, [total]);

  // Clamp if current page fell out of range.
  const safePage = Math.min(page, totalPages);

  const pageItems = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, safePage, pageSize]);

  const from = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const to = Math.min(safePage * pageSize, total);

  return {
    page: safePage,
    setPage,
    pageItems,
    totalPages,
    total,
    pageSize,
    from,
    to,
  };
}
