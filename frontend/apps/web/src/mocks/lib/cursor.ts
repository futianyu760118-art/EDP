/** 游标分页助手：cursor = base64("offset:N")（spec §5.2）。 */
export interface PageResult<T> {
  items: T[];
  next_cursor: string | null;
  /** mock 扩展：冻结契约 Page envelope 无 total；设计 13.7 模式 14 "共 N 条" 需要，后端落地后对齐。 */
  total: number;
}

export function encodeCursor(offset: number): string {
  return btoa(`offset:${offset}`);
}

export function decodeCursor(cursor: string | null | undefined): number {
  if (!cursor) return 0;
  try {
    const m = /^offset:(\d+)$/.exec(atob(cursor));
    return m ? Number(m[1]) : 0;
  } catch {
    return 0;
  }
}

export function clampLimit(raw: string | null, fallback = 20, max = 100): number {
  const n = Number(raw ?? fallback);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(Math.max(Math.trunc(n), 1), max);
}

export function paginate<T>(all: T[], limit: number, cursor: string | null): PageResult<T> {
  const offset = decodeCursor(cursor);
  const items = all.slice(offset, offset + limit);
  return {
    items,
    next_cursor: offset + limit < all.length ? encodeCursor(offset + limit) : null,
    total: all.length,
  };
}
