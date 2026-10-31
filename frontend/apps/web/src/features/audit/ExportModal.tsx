import { message } from "antd";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import { AUDIT_EXPORT_MAX_ROWS, auditApi, type AuditLogFilters, type AuditLogItem } from "./api";

/** 导出范围回显行（参数名与 GET /audit-logs 查询参数一一对应）。 */
export interface ExportEchoRow {
  param: string;
  label: string;
  value: string;
}

export function exportEchoRows(filters: AuditLogFilters): ExportEchoRow[] {
  return [
    { param: "since", label: "开始时间", value: filters.since ?? "全部" },
    { param: "until", label: "结束时间", value: filters.until ?? "全部" },
    { param: "actor_id", label: "操作人", value: filters.actor_id ?? "全部" },
    { param: "resource_type", label: "资源类型", value: filters.resource_type ?? "全部" },
    { param: "action", label: "动作", value: filters.action ?? "全部" },
  ];
}

/** CSV 单元格转义（引号翻倍 + 整体包引号）。 */
function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

/** 审计 CSV（utf-8 BOM 由调用侧 Blob 前缀补，便于 Excel 打开中文）。 */
export function buildAuditCsv(rows: AuditLogItem[]): string {
  const header = ["audit_id", "occurred_at", "actor_type", "actor_id", "action", "resource_type", "resource_id", "detail"];
  const lines = rows.map((row) =>
    [
      String(row.audit_id),
      row.occurred_at,
      row.actor_type,
      row.actor_id,
      row.action,
      row.resource_type,
      row.resource_id ?? "",
      JSON.stringify(row.detail ?? {}),
    ]
      .map(csvCell)
      .join(","),
  );
  return [header.map(csvCell).join(","), ...lines].join("\r\n");
}

/** 下载 Blob（jsdom/浏览器同构：锚点 click + 清理）。 */
function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export interface ExportModalProps {
  open: boolean;
  filters: AuditLogFilters;
  onClose: () => void;
}

/**
 * 导出审计日志弹窗（视觉基线 `原型设计/pages/导出审计日志 - 弹窗.html`）：
 * 导出范围回显当前筛选（参数与接口一一对应展示）+ 文件名（默认
 * audit-log-export）+「导出 CSV」→ 按当前筛选全量拉取（1000 行保护 +
 * 超限提示）→ 前端拼 CSV（utf-8 BOM）下载。
 */
export function ExportModal({ open, filters, onClose }: ExportModalProps) {
  const [filename, setFilename] = useState("audit-log-export");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (open) setFilename("audit-log-export");
  }, [open]);

  const echoRows = exportEchoRows(filters);

  const handleExport = async () => {
    setExporting(true);
    try {
      const { rows, capped } = await auditApi.listAllForExport(filters);
      if (rows.length === 0) {
        void message.info("当前筛选没有可导出的审计日志");
        return;
      }
      downloadCsv(buildAuditCsv(rows), filename.trim() || "audit-log-export");
      if (capped) {
        void message.warning(`结果超过 ${AUDIT_EXPORT_MAX_ROWS} 行，仅导出前 ${AUDIT_EXPORT_MAX_ROWS} 行`);
      }
      void message.success(`已导出 ${rows.length} 条审计日志`);
      onClose();
    } catch {
      void message.error("导出失败，请稍后重试");
    } finally {
      setExporting(false);
    }
  };

  return (
    <ModalForm
      open={open}
      title="导出审计日志"
      icon={<Download className="w-5 h-5" aria-hidden="true" />}
      width={520}
      onCancel={onClose}
      onSubmit={() => void handleExport()}
      submitText="导出 CSV"
      confirmLoading={exporting}
    >
      <div className="space-y-4 pt-2" data-dom-id="audit-export-modal">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">导出范围（当前筛选）</div>
          <div
            className="border border-border rounded-lg divide-y divide-border"
            data-dom-id="audit-export-echo"
          >
            {echoRows.map((row) => (
              <div key={row.param} className="flex items-center justify-between px-3 py-2">
                <span className="text-xs text-muted-foreground">
                  {row.label} <code className="font-mono text-[10px] text-muted-foreground/80">{row.param}</code>
                </span>
                <span className="font-mono text-xs text-foreground" data-dom-id={`audit-export-echo-${row.param}`}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground" data-dom-id="audit-export-limit">
          按当前筛选导出全部审计日志，单次最多 {AUDIT_EXPORT_MAX_ROWS} 行。
        </p>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">文件名称</div>
          <input
            type="text"
            data-dom-id="audit-export-filename"
            aria-label="导出文件名"
            placeholder="请输入导出文件名"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
          />
        </div>
      </div>
    </ModalForm>
  );
}
