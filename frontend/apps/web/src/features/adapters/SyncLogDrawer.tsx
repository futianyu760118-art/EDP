import { Drawer } from "antd";
import { StatusPill } from "@edp/shared";
import { CheckCircle2, History, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { AdapterJobItem } from "./api";
import { useAdapterJobs } from "./hooks";

export interface SyncLogDrawerProps {
  adapter: string | undefined;
  open: boolean;
  onClose: () => void;
}

const STAT_LABELS = [
  { key: "fetched", label: "拉取" },
  { key: "registered", label: "注册" },
  { key: "duplicated", label: "去重" },
  { key: "failed", label: "失败" },
] as const;

function fmtTs(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const JOB_PILL: Record<string, { tone: "info" | "success" | "error"; label: string }> = {
  RUNNING: { tone: "info", label: "运行中" },
  SUCCEEDED: { tone: "success", label: "已完成" },
  FAILED: { tone: "error", label: "失败" },
};

function jobOptionLabel(job: AdapterJobItem): string {
  const pill = JOB_PILL[job.status]?.label ?? job.status;
  return `${fmtTs(job.started_at)} · ${job.scope ?? "sync"} · ${pill}`;
}

/**
 * 适配器同步日志抽屉（13.7 #8 420px + #16 进度日志时间线）：历史任务下拉
 * （T5 GET /{name}/jobs，默认最新一条）+ 选中任务（任务号/完成时间/scope/
 * stats 四计数 + 时间线）。最新任务 RUNNING 时 1s 轮询推进。
 */
export function SyncLogDrawer({ adapter, open, onClose }: SyncLogDrawerProps) {
  const jobsQuery = useAdapterJobs(open ? adapter : undefined);
  const jobs = jobsQuery.data?.items ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // 下拉缺省选中最新一条；适配器切换或列表更新时重置到最新
  useEffect(() => {
    setSelectedId(null);
  }, [adapter]);
  const selected = jobs.find((job) => job.task_id === selectedId) ?? jobs[0] ?? null;
  const stats = selected?.stats ?? null;
  const pill = selected ? JOB_PILL[selected.status] : undefined;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={420}
      title="适配器同步日志"
      data-dom-id="adapter-log-drawer"
    >
      {adapter == null || selected == null ? (
        jobsQuery.isError ? (
          <p className="text-xs text-muted-foreground">任务历史暂不可用</p>
        ) : (
          <p className="text-xs text-muted-foreground">加载中…</p>
        )
      ) : (
        <div data-dom-id="adapter-log-body" className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium text-foreground">{adapter}</span>
            {pill != null && <StatusPill tone={pill.tone} label={pill.label} />}
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              历史任务
            </div>
            <select
              aria-label="选择历史任务"
              data-dom-id="adapter-log-history"
              value={selected.task_id}
              onChange={(e) => setSelectedId(e.target.value)}
              className="w-full h-9 px-2 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {jobs.map((job) => (
                <option key={job.task_id} value={job.task_id}>
                  {jobOptionLabel(job)}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            <div>
              <div className="text-[10px] uppercase tracking-wider">任务号</div>
              <div className="text-foreground mt-0.5 font-mono break-all" data-dom-id="adapter-log-sync-id">
                {selected.task_id}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider">完成时间</div>
              <div className="text-foreground mt-0.5" data-dom-id="adapter-log-finished">
                {selected.finished_at != null ? fmtTs(selected.finished_at) : "—"}
              </div>
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">同步计数</div>
            <div className="grid grid-cols-4 gap-2" data-dom-id="adapter-log-stats">
              {STAT_LABELS.map(({ key, label }) => (
                <div key={key} className="border border-border rounded-md px-2 py-1.5 text-center">
                  <div className="text-[10px] text-muted-foreground">{label}</div>
                  <div className="text-sm font-semibold text-foreground font-mono">
                    {stats != null ? stats[key] : "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">进度日志</div>
            <ul data-dom-id="adapter-log-timeline" className="p-3 bg-muted/50 border border-border rounded-lg space-y-2">
              <li className="flex items-start gap-2 text-xs">
                <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-foreground">同步任务已触发</span>
                  <span className="block text-[10px] text-muted-foreground font-mono truncate">
                    {" "}task {selected.task_id.slice(-8)} · scope {selected.scope ?? "sync"}
                  </span>
                </div>
              </li>
              {selected.status === "RUNNING" && (
                <li className="flex items-start gap-2 text-xs">
                  <Loader2 className="w-4 h-4 text-state-info mt-0.5 shrink-0 animate-spin" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步执行中</span>
                    <span className="block text-[10px] text-muted-foreground font-mono"> status RUNNING</span>
                  </div>
                </li>
              )}
              {selected.status === "SUCCEEDED" && (
                <li className="flex items-start gap-2 text-xs">
                  <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-foreground">同步完成</span>
                    <span className="block text-[10px] text-muted-foreground font-mono truncate">
                      {" "}fetched {stats?.fetched ?? 0} · registered {stats?.registered ?? 0} · duplicated{" "}
                      {stats?.duplicated ?? 0} · failed {stats?.failed ?? 0}
                    </span>
                  </div>
                  {selected.finished_at != null && (
                    <span className="text-[10px] text-muted-foreground font-mono shrink-0">
                      {fmtTs(selected.finished_at)}
                    </span>
                  )}
                </li>
              )}
              {selected.status === "FAILED" && (
                <li className="flex items-start gap-2 text-xs" data-dom-id="adapter-log-failed-row">
                  <XCircle className="w-4 h-4 text-state-error mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步失败</span>
                    <span className="block text-[10px] text-muted-foreground font-mono">
                      {" "}failed {stats?.failed ?? "—"}
                    </span>
                  </div>
                </li>
              )}
            </ul>
          </div>

          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <History className="w-3.5 h-3.5" aria-hidden="true" />
            共 {jobs.length} 条历史任务（最近 30 天）
          </div>
        </div>
      )}
    </Drawer>
  );
}
