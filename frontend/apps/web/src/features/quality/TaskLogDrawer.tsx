import { message } from "antd";
import { Drawer } from "antd";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { StatusPill } from "@edp/shared";
import type { QualityTask } from "../../mocks/types";
import { useQualityTask } from "./hooks";

export interface TaskLogDrawerProps {
  taskId: string | undefined;
  open: boolean;
  onClose: () => void;
}

const LEVEL_TONE: Record<string, "info" | "warning" | "error"> = {
  INFO: "info",
  WARN: "warning",
  ERROR: "error",
};

const STATUS_PILL: Record<string, { tone: "info" | "success" | "error"; label: string }> = {
  RUNNING: { tone: "info", label: "运行中" },
  SUCCEEDED: { tone: "success", label: "已完成" },
  FAILED: { tone: "error", label: "失败" },
};

function fmtTs(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 任务日志抽屉（视觉基线 `任务日志 - 抽屉.html`）：头部任务号 + 状态 pill、
 * 元信息（开始/完成时间、已耗时、scope）、日志时间线（级别 pill + 进度行）、
 * 下载日志占位。数据源：GET /admin/quality/tasks/{id}（T4 QualityTaskOut）。 */
export function TaskLogDrawer({ taskId, open, onClose }: TaskLogDrawerProps) {
  const taskQuery = useQualityTask(open ? taskId : undefined);
  const queryClient = useQueryClient();
  const task: QualityTask | undefined = taskQuery.data;
  const elapsed = task ? elapsedText(task.started_at, task.finished_at) : "—";
  const pill = task ? STATUS_PILL[task.status] : undefined;
  const logs = task?.logs ?? [];

  // 轮询离开 RUNNING（成功/失败终态）→ 再失效一次报告与异常卡（终态读数刷新）
  const sawRunningRef = useRef(false);
  const status = task?.status;
  useEffect(() => {
    if (status === "RUNNING") sawRunningRef.current = true;
  }, [status]);
  useEffect(() => {
    if (status != null && status !== "RUNNING" && sawRunningRef.current) {
      sawRunningRef.current = false;
      void queryClient.invalidateQueries({ queryKey: ["quality", "report"] });
      void queryClient.invalidateQueries({ queryKey: ["quality", "exceptions"] });
    }
  }, [status, queryClient]);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={420}
      title="重新校验任务日志"
      data-dom-id="quality-task-drawer"
    >
      {task == null ? (
        <p className="text-xs text-muted-foreground">加载中…</p>
      ) : (
        <div data-dom-id="quality-task-body">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-foreground">{task.task_id}</span>
            {pill != null && <StatusPill tone={pill.tone} label={pill.label} />}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            <div>
              <div className="text-[10px] uppercase tracking-wider">开始时间</div>
              <div className="text-foreground mt-0.5">{task.started_at.slice(0, 19).replace("T", " ")}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider">已耗时</div>
              <div className="text-foreground mt-0.5">{elapsed}</div>
            </div>
            {task.scope != null && (
              <div>
                <div className="text-[10px] uppercase tracking-wider">范围</div>
                <div className="text-foreground mt-0.5 font-mono">{task.scope}</div>
              </div>
            )}
            {task.finished_at != null && (
              <div>
                <div className="text-[10px] uppercase tracking-wider">完成时间</div>
                <div className="text-foreground mt-0.5">
                  {task.finished_at.slice(0, 19).replace("T", " ")}
                </div>
              </div>
            )}
          </div>

          <ul className="mt-4 space-y-2.5" data-dom-id="quality-task-logs">
            {logs.map((log, index) => (
              <li key={`${log.ts}-${index}`} className="flex items-start gap-2">
                <span className="font-mono text-[10px] text-muted-foreground pt-0.5">
                  {fmtTs(log.ts)}
                </span>
                <StatusPill tone={LEVEL_TONE[log.level] ?? "muted"} label={log.level} size="sm" />
                <span className="text-[11px] text-foreground flex-1">{log.message}</span>
              </li>
            ))}
          </ul>

          <div className="mt-6 flex justify-end">
            <button
              type="button"
              data-dom-id="quality-task-download"
              onClick={() => void message.info("日志下载暂未开放")}
              className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
            >
              下载日志
            </button>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function elapsedText(startedAt: string, finishedAt?: string | null): string {
  const end = finishedAt != null ? new Date(finishedAt).getTime() : Date.now();
  const ms = Math.max(0, end - new Date(startedAt).getTime());
  const totalSeconds = Math.floor(ms / 1000);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}
