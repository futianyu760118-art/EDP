import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * 游标分页条（设计文档 13.7 #14）。
 * 视觉基线：`原型设计/pages/事件流.html` 行 529~538 ——
 * 左“显示 X–Y 条，共 N 条” + 右页码（后端 next_cursor 驱动，禁用越界）。
 */
export interface CursorPaginationProps {
  start: number;
  end: number;
  total: number;
  page: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

export function CursorPagination({
  start,
  end,
  total,
  page,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: CursorPaginationProps) {
  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";
  return (
    <div className="px-4 py-3 border-t border-border flex items-center justify-between shrink-0">
      <div className="text-xs text-muted-foreground" data-dom-id="pagination-range">
        显示 {start}–{end} 条，共 {total} 条
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="上一页"
          data-dom-id="pagination-prev"
          onClick={onPrev}
          disabled={!hasPrev}
          className={navButtonClass}
        >
          <ChevronLeft className="w-4 h-4" aria-hidden="true" />
        </button>
        <span
          className="h-8 px-3 bg-primary text-primary-foreground rounded-lg text-xs font-medium grid place-items-center"
          aria-current="page"
          data-dom-id="pagination-page"
        >
          {page}
        </span>
        <button
          type="button"
          aria-label="下一页"
          data-dom-id="pagination-next"
          onClick={onNext}
          disabled={!hasNext}
          className={navButtonClass}
        >
          <ChevronRight className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
