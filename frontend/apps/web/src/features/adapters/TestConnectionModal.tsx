import { useQueryClient } from "@tanstack/react-query";
import { EdpApiError } from "@edp/api-sdk";
import { errorSpec } from "@edp/shared";
import { Activity, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import type { AdapterRow } from "./api";
import { useAdapterStatus, useSyncAdapter } from "./hooks";

export interface TestConnectionModalProps {
  open: boolean;
  /** 行操作预填目标适配器。 */
  initialAdapter?: string;
  adapters: AdapterRow[];
  onClose: () => void;
}

function fmtTs(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const STAT_LABELS = [
  { key: "fetched", label: "拉取" },
  { key: "registered", label: "注册" },
  { key: "duplicated", label: "去重" },
  { key: "failed", label: "失败" },
] as const;

/**
 * 测试适配器连接弹窗（视觉基线 `测试适配器 - 弹窗.html` / 13.7 #16 进度日志
 * 时间线）：选适配器（预填当前行）→「开始测试」→ POST /{name}/sync
 * （mode=incremental）→ 202 → status 1s 轮询（RUNNING → 终态停）→ 完成后
 * stats 四计数摘要 + 成功行内提示「连接正常」。
 */
export function TestConnectionModal({
  open,
  initialAdapter,
  adapters,
  onClose,
}: TestConnectionModalProps) {
  const [target, setTarget] = useState("");
  const [job, setJob] = useState<{ sync_id: string; started_at: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sync = useSyncAdapter();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setTarget(initialAdapter ?? "");
    setJob(null);
    setError(null);
  }, [open, initialAdapter]);

  const statusQuery = useAdapterStatus(job != null ? target : undefined);
  const lastSync = statusQuery.data?.last_sync ?? null;
  const terminal = lastSync != null && lastSync.status !== "RUNNING";

  const start = () => {
    if (!target) {
      setError("请选择适配器");
      return;
    }
    setError(null);
    // 新一轮测试：清缓存态，保证开启后立即拉最新 status
    void queryClient.removeQueries({ queryKey: ["adapters", "status", target] });
    sync.mutate(target, {
      onSuccess: (data) => setJob({ sync_id: data.sync_id, started_at: data.started_at }),
      onError: (err) => {
        setError(
          err instanceof EdpApiError ? err.message : errorSpec("INTERNAL").message,
        );
      },
    });
  };

  const stats = lastSync?.stats ?? null;

  return (
    <ModalForm
      open={open}
      title="测试适配器连接"
      icon={<Activity className="w-5 h-5" aria-hidden="true" />}
      width={640}
      onCancel={onClose}
      onSubmit={start}
      submitText={job == null ? "开始测试" : terminal ? "重新测试" : "测试中…"}
      confirmLoading={sync.isPending || (job != null && !terminal)}
    >
      <div className="space-y-4 pt-2" data-dom-id="adapter-test-modal">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">测试目标</div>
          <select
            data-dom-id="adapter-test-target"
            aria-label="测试目标适配器"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={job != null && !terminal}
            className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent disabled:opacity-60"
          >
            <option value="">选择适配器…</option>
            {adapters.map((row) => (
              <option key={row.adapter} value={row.adapter}>
                {row.adapter}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            以增量同步（incremental）验证连通性与拉取链路。
          </p>
        </div>

        {job != null && lastSync != null && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">进度日志</div>
            <ul
              data-dom-id="adapter-test-timeline"
              className="p-3 bg-muted/50 border border-border rounded-lg space-y-2"
            >
              <li className="flex items-start gap-2 text-xs">
                <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-foreground">已触发测试同步</span>
                  <span className="block text-[10px] text-muted-foreground font-mono truncate">
                    {" "}sync_id {job.sync_id.slice(-8)} · mode incremental
                  </span>
                </div>
                <span className="text-[10px] text-muted-foreground font-mono">{fmtTs(job.started_at)}</span>
              </li>
              {lastSync.status === "RUNNING" && (
                <li className="flex items-start gap-2 text-xs" data-dom-id="adapter-test-running">
                  <Loader2 className="w-4 h-4 text-state-info mt-0.5 shrink-0 animate-spin" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步执行中</span>
                    <span className="block text-[10px] text-muted-foreground font-mono"> status RUNNING</span>
                  </div>
                </li>
              )}
              {terminal && lastSync.status === "SUCCEEDED" && (
                <li className="flex items-start gap-2 text-xs">
                  <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-foreground">同步完成</span>
                    <span className="block text-[10px] text-muted-foreground font-mono truncate">
                      {" "}fetched {stats?.fetched ?? 0} · registered {stats?.registered ?? 0} · duplicated{" "}
                      {stats?.duplicated ?? 0} · failed {stats?.failed ?? 0}
                    </span>
                  </div>
                  {lastSync.finished_at != null && (
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {fmtTs(lastSync.finished_at)}
                    </span>
                  )}
                </li>
              )}
              {terminal && lastSync.status === "FAILED" && (
                <li className="flex items-start gap-2 text-xs">
                  <XCircle className="w-4 h-4 text-state-error mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步失败</span>
                    <span className="block text-[10px] text-muted-foreground font-mono">
                      {" "}{lastSync.error ?? "unknown error"}
                    </span>
                  </div>
                </li>
              )}
            </ul>
          </div>
        )}

        {terminal && lastSync?.status === "SUCCEEDED" && stats != null && (
          <div
            data-dom-id="adapter-test-result"
            className="p-3 bg-state-success-bg border border-state-success/20 rounded-lg"
          >
            <div className="text-xs font-medium text-state-success" data-dom-id="adapter-test-ok">
              连接正常
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              适配器连通性与拉取链路验证通过。
            </div>
            <div className="grid grid-cols-4 gap-2 mt-2" data-dom-id="adapter-test-stats">
              {STAT_LABELS.map(({ key, label }) => (
                <div key={key} className="bg-card border border-border rounded-md px-2 py-1.5">
                  <div className="text-[10px] text-muted-foreground">{label}</div>
                  <div className="text-sm font-semibold text-foreground font-mono">{stats[key]}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {terminal && lastSync?.status === "FAILED" && (
          <div
            data-dom-id="adapter-test-result"
            className="p-3 bg-state-error-bg border border-state-error/20 rounded-lg text-xs text-state-error"
          >
            连接失败：{lastSync.error ?? "未知错误"}
          </div>
        )}

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="adapter-test-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
