import { X } from "lucide-react";

/**
 * Chip 过滤器（设计文档 13.7 #2）。
 * 已生效筛选的 removable chip 集合；chip = primary-50 底 primary 字，
 * x 按钮 hover 变 error 色；提供 onClearAll 时尾部渲染“清除全部”文字按钮。
 */
export interface FilterChip {
  key: string;
  label: string;
}

export interface FilterChipsProps {
  chips: FilterChip[];
  onRemove: (key: string) => void;
  onClearAll?: () => void;
}

export function FilterChips({ chips, onRemove, onClearAll }: FilterChipsProps) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="已生效筛选">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-primary-50 text-primary"
        >
          {chip.label}
          <button
            type="button"
            aria-label={`移除筛选 ${chip.label}`}
            data-dom-id={`chip-remove-${chip.key}`}
            onClick={() => onRemove(chip.key)}
            className="w-3.5 h-3.5 rounded grid place-items-center hover:bg-state-error-bg hover:text-state-error"
          >
            <X className="w-2.5 h-2.5" aria-hidden="true" />
          </button>
        </span>
      ))}
      {onClearAll != null && (
        <button
          type="button"
          data-dom-id="chips-clear-all"
          onClick={onClearAll}
          className="ml-1 text-[10px] text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          清除全部
        </button>
      )}
    </div>
  );
}
