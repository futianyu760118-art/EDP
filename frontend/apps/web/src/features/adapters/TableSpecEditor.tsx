import { Plus, Trash2 } from "lucide-react";

export interface TableSpecRow {
  table: string;
  increment_column: string;
  owner_domain: string;
  excluded_columns: string;
}

/**
 * 表配置结构化编辑器（V1.3 T50 细化）：逐表行编辑——
 * 表名 / 增量列（留空=全量拉取）/ 归属域 / 排除列（逗号分隔，SQL 级排除）。
 * excluded_columns 以逗号字符串在行内编辑，提交方转数组。
 */
export function TableSpecEditor({
  rows,
  onChange,
}: {
  rows: TableSpecRow[];
  onChange: (rows: TableSpecRow[]) => void;
}) {
  const cellCls =
    "w-full h-8 px-2 text-xs font-mono bg-muted border border-border rounded focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

  const update = (index: number, patch: Partial<TableSpecRow>) => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const remove = (index: number) => {
    onChange(rows.filter((_, i) => i !== index));
  };

  const add = () => {
    onChange([...rows, { table: "", increment_column: "", owner_domain: "master", excluded_columns: "" }]);
  };

  return (
    <div className="space-y-2" data-dom-id="table-spec-editor">
      {rows.length === 0 ? (
        <div className="text-[11px] text-muted-foreground text-center py-3 border border-dashed border-border rounded-lg">
          尚无表配置，点击下方「添加表」
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full border-collapse" data-dom-id="table-spec-table">
            <thead>
              <tr className="bg-muted/50">
                {["表名", "增量列（空=全量）", "归属域", "排除列（逗号分隔）", ""].map((h, i) => (
                  <th
                    key={i}
                    className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium text-left px-2 py-2 border-b border-border whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-xs">
              {rows.map((row, index) => (
                <tr key={index} data-dom-id={`table-spec-row-${index}`} className="border-b border-border last:border-b-0">
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      data-dom-id={`table-spec-table-${index}`}
                      aria-label={`表名 ${index + 1}`}
                      placeholder="scm_material"
                      value={row.table}
                      onChange={(e) => update(index, { table: e.target.value })}
                      className={cellCls}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      data-dom-id={`table-spec-increment-${index}`}
                      aria-label={`增量列 ${index + 1}`}
                      placeholder="update_time"
                      value={row.increment_column}
                      onChange={(e) => update(index, { increment_column: e.target.value })}
                      className={cellCls}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      data-dom-id={`table-spec-domain-${index}`}
                      aria-label={`归属域 ${index + 1}`}
                      placeholder="master"
                      value={row.owner_domain}
                      onChange={(e) => update(index, { owner_domain: e.target.value })}
                      className={cellCls}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      data-dom-id={`table-spec-excluded-${index}`}
                      aria-label={`排除列 ${index + 1}`}
                      placeholder="contact_phone,address"
                      value={row.excluded_columns}
                      onChange={(e) => update(index, { excluded_columns: e.target.value })}
                      className={cellCls}
                    />
                  </td>
                  <td className="px-2 py-1.5 w-8">
                    <button
                      type="button"
                      data-dom-id={`table-spec-remove-${index}`}
                      aria-label={`删除表 ${index + 1}`}
                      onClick={() => remove(index)}
                      className="w-7 h-7 rounded border border-border text-muted-foreground hover:bg-muted grid place-items-center"
                    >
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button
        type="button"
        data-dom-id="table-spec-add"
        onClick={add}
        className="h-8 px-3 border border-border rounded-lg text-[11px] text-muted-foreground hover:bg-muted inline-flex items-center gap-1.5"
      >
        <Plus className="w-3.5 h-3.5" aria-hidden="true" />
        添加表
      </button>
    </div>
  );
}
