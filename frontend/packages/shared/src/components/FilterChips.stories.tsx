import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { FilterChips, type FilterChip } from "./FilterChips";

const meta: Meta<typeof FilterChips> = {
  title: "Components/FilterChips",
  component: FilterChips,
};

export default meta;

const INITIAL: FilterChip[] = [
  { key: "keyword", label: "关键词：evidence_id" },
  { key: "source", label: "来源：ERP-S4" },
  { key: "status", label: "状态：PUBLISHED" },
];

function ChipDemo({ initial, clearable = true }: { initial: FilterChip[]; clearable?: boolean }) {
  const [chips, setChips] = useState(initial);
  return (
    <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-2">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
        工具栏（筛选已生效）
      </div>
      {chips.length > 0 ? (
        <FilterChips
          chips={chips}
          onRemove={(key) => setChips((prev) => prev.filter((chip) => chip.key !== key))}
          onClearAll={clearable ? () => setChips([]) : undefined}
        />
      ) : (
        <span className="text-xs text-muted-foreground">（无生效筛选）</span>
      )}
    </div>
  );
}

export const Default: StoryObj = {
  render: () => <ChipDemo initial={INITIAL} />,
};

export const SingleWithoutClearAll: StoryObj = {
  render: () => <ChipDemo initial={[{ key: "source", label: "来源：MDM" }]} clearable={false} />,
};

export const Empty: StoryObj = {
  render: () => <ChipDemo initial={[]} />,
};
