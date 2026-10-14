import { Skeleton } from "antd";
import { EmptyState, StatusPill } from "@edp/shared";
import { Cable, Plug, Plus, RefreshCw, ScrollText } from "lucide-react";
import { useState } from "react";
import { relTime } from "../../lib/labels";
import { useAdapters } from "./hooks";
import type { AdapterRow } from "./api";
import { CreateAdapterModal } from "./CreateAdapterModal";
import { TestConnectionModal } from "./TestConnectionModal";
import { ConnectWizard } from "./ConnectWizard";
import { SyncLogDrawer } from "./SyncLogDrawer";

const STATUS_TONE: Record<string, "success" | "warning" | "error" | "muted"> = {
  运行中: "success",
  空闲: "success",
  降级: "warning",
  异常: "error",
};

const HEADERS = ["系统", "接入方式", "责任团队", "最近同步", "健康度", "状态", "模式", "操作"] as const;

function statusTone(status: string): "success" | "warning" | "error" | "muted" {
  return STATUS_TONE[status] ?? "muted";
}

/**
 * 适配器管理页（EDP-402，视觉基线 `适配器管理.html`）：7 数据列表格
 * （adapter mono / access / team / last_sync_at 相对时间 / health / status
 * pill / mode）——access/team 为 MSW 演示列，真实契约（adapter/mode/status/
 * health/last_sync_at）不含，真模式按 W3-01 口径「—」降级；刷新按钮 +
 * 行操作（测试连接 → 轮询弹窗 / 日志 → 抽屉）+ 新增弹窗 + 数据源连接向导。
 */
export function AdaptersPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testTarget, setTestTarget] = useState<string | undefined>(undefined);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [logAdapter, setLogAdapter] = useState<string | undefined>(undefined);
  const [logOpen, setLogOpen] = useState(false);
  const adaptersQuery = useAdapters();
  const rows = adaptersQuery.data?.items ?? [];

  const openTest = (adapter?: string) => {
    setTestTarget(adapter);
    setTestOpen(true);
  };

  const openLog = (adapter: string) => {
    setLogAdapter(adapter);
    setLogOpen(true);
  };

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="adapters-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">适配器管理</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="adapters-refresh"
            onClick={() => void adaptersQuery.refetch()}
            className="h-9 px-3 border border-border bg-card text-muted-foreground rounded-lg text-xs hover:bg-muted flex items-center gap-1.5"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            刷新
          </button>
          <button
            type="button"
            data-dom-id="connect-open"
            onClick={() => setWizardOpen(true)}
            className="h-9 px-3 border border-border bg-card text-muted-foreground rounded-lg text-xs hover:bg-muted flex items-center gap-1.5"
          >
            <Cable className="w-4 h-4" aria-hidden="true" />
            数据源连接
          </button>
          <button
            type="button"
            data-dom-id="adapter-add"
            onClick={() => setCreateOpen(true)}
            className="h-9 px-3 bg-primary text-primary-foreground rounded-lg text-xs hover:opacity-90 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            新增适配器
          </button>
        </div>
      </section>

      {adaptersQuery.isError ? (
        <section className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="p-4 text-xs text-muted-foreground" data-dom-id="adapters-error">
            适配器清单暂不可用
          </div>
        </section>
      ) : rows.length === 0 && !adaptersQuery.isPending ? (
        <div data-dom-id="adapters-empty">
          <EmptyState
            icon={<Plug className="w-7 h-7" />}
            title="暂无适配器"
            description="尚未接入任何源系统适配器；新增后可测试连接并查看同步日志。"
            primaryAction={{ label: "新增适配器", onClick: () => setCreateOpen(true) }}
            secondaryAction={{ label: "数据源连接向导", onClick: () => setWizardOpen(true) }}
          />
        </div>
      ) : (
        <section className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col">
          <div className="table-scroll flex-1 min-h-0">
            <table className="w-full border-collapse min-w-[880px]" data-dom-id="adapters-table">
              <thead>
                <tr className="bg-muted/50">
                  {HEADERS.map((header) => (
                    <th
                      key={header}
                      className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium text-left px-4 py-3 border-b border-border whitespace-nowrap"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-xs text-foreground">
                {rows.map((row: AdapterRow) => (
                  <tr key={row.adapter} data-dom-id={`adapter-row-${row.adapter}`} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-3 font-mono font-medium whitespace-nowrap">{row.adapter}</td>
                    <td className="px-4 py-3">{row.access ?? "—"}</td>
                    <td className="px-4 py-3">{row.team ?? "—"}</td>
                    <td className="px-4 py-3 font-mono whitespace-nowrap">
                      {row.last_sync_at ?? row.last_sync ? relTime(row.last_sync_at ?? row.last_sync!) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill
                        tone={row.health === "OK" ? "success" : "warning"}
                        label={row.health_pct != null ? `${row.health_pct}%` : row.health}
                        size="sm"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill tone={statusTone(row.status)} label={row.status} size="sm" />
                    </td>
                    <td className="px-4 py-3 font-mono">{row.mode}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <button
                        type="button"
                        data-dom-id={`adapter-test-${row.adapter}`}
                        onClick={() => openTest(row.adapter)}
                        className="text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted flex items-center gap-1"
                      >
                        <Plug className="w-3 h-3" aria-hidden="true" />
                        测试连接
                      </button>
                      <button
                        type="button"
                        data-dom-id={`adapter-log-${row.adapter}`}
                        onClick={() => openLog(row.adapter)}
                        className="ml-1.5 text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted inline-flex items-center gap-1"
                      >
                        <ScrollText className="w-3 h-3" aria-hidden="true" />
                        日志
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {adaptersQuery.isPending && (
            <div className="p-4" data-dom-id="adapters-skeleton">
              <Skeleton active paragraph={{ rows: 4 }} />
            </div>
          )}
        </section>
      )}

      <CreateAdapterModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <TestConnectionModal
        open={testOpen}
        initialAdapter={testTarget}
        adapters={rows}
        onClose={() => setTestOpen(false)}
      />
      <ConnectWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
      <SyncLogDrawer adapter={logAdapter} open={logOpen} onClose={() => setLogOpen(false)} />
    </div>
  );
}
