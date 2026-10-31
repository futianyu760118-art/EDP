import { Button, Input, Modal, Radio, Select, Steps } from "antd";
import { EdpApiError } from "@edp/api-sdk";
import { errorSpec, MonoId, StatusPill } from "@edp/shared";
import { AlertCircle, CheckCircle2, ChevronRight, RotateCcw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { eventTypeDisplay, fmtDateTime, sourceLabel } from "../../lib/labels";
import type { AdapterSyncResponse, EventResponse } from "../../mocks/types";
import { useAdapterOptions, useReplayEvent } from "./hooks";

/** 回放模式（原型 radio 卡：按原序/并发）——仅前端呈现，不下发 API（spec §3.4）。 */
type ReplayMode = "original" | "concurrent";

const MODE_OPTIONS: { value: ReplayMode; label: string }[] = [
  { value: "original", label: "按原序" },
  { value: "concurrent", label: "并发" },
];

const shortId = (id: string) => `evt-${id.slice(-8)}`;

/** 描述回退链：data.summary → data.reason → data.note → 「—」（同 EventTable）。 */
function describe(e: EventResponse): string {
  for (const key of ["summary", "reason", "note"] as const) {
    const value = e.data?.[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "—";
}

/** 完整时间 `YYYY-MM-DD HH:mm:ss`（原型摘要卡「原始发生时间」行）。 */
function fmtFullDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function SummaryRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <tr className="border-b border-border last:border-b-0">
      <td className="px-4 py-2.5 text-muted-foreground w-[140px]">{label}</td>
      <td className="px-4 py-2.5 text-foreground">{children}</td>
    </tr>
  );
}

/** 只读事件摘要卡（原型行 623~650）：步骤 2/3 共用，内容与步骤 1 选中行一致。 */
function EventSummaryCard({ event }: { event: EventResponse }) {
  const type = eventTypeDisplay(event.event_type);
  return (
    <div className="border border-border rounded-xl overflow-hidden" data-dom-id="replay-summary">
      <div className="px-4 py-2.5 bg-muted border-b border-border text-xs font-medium text-foreground">
        事件摘要
      </div>
      <table className="w-full border-collapse">
        <tbody className="text-xs">
          <SummaryRow label="事件 ID">
            <MonoId
              prefix="evt"
              id={event.event_id.slice(-8)}
              full={event.event_id}
              copyable={false}
            />
          </SummaryRow>
          <SummaryRow label="事件类型">
            <StatusPill tone={type.tone} label={type.label} size="sm" />
          </SummaryRow>
          <SummaryRow label="业务对象">
            <span className="font-mono">{event.object_source_id ?? event.object_id}</span>
          </SummaryRow>
          <SummaryRow label="描述">{describe(event)}</SummaryRow>
          <SummaryRow label="原始发生时间">{fmtFullDateTime(event.occurred_at)}</SummaryRow>
        </tbody>
      </table>
    </div>
  );
}

/**
 * 回放三步向导（spec §7.2，视觉基线：`原型设计/pages/事件回放 - 执行流程.html`）：
 * ① 选择事件（Radio 列表 + 选中回显）→ ② 配置参数（目标适配器 Select / 回放模式 radio 卡 /
 * 开始时间 datetime-local → since / 只读事件摘要卡）→ ③ 确认执行 → `POST
 * /admin/adapters/{name}/sync {mode:"replay"}` → 202 展示 sync_id/状态，失败按 errorSpec 文案。
 */
export function ReplayWizard({
  open,
  events,
  onClose,
}: {
  open: boolean;
  events: EventResponse[];
  onClose: () => void;
}) {
  const [step, setStep] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adapter, setAdapter] = useState<string | undefined>(undefined);
  const [mode, setMode] = useState<ReplayMode>("original");
  const [since, setSince] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<AdapterSyncResponse | null>(null);

  // W3-37：向导打开才拉取适配器清单（未打开不发请求）
  const adaptersQuery = useAdapterOptions(open);
  const replay = useReplayEvent();

  // 关闭即复位：下次打开从步骤 1 开始（destroyOnClose 只卸载内容，状态在本组件）。
  useEffect(() => {
    if (!open) {
      setStep(0);
      setSelectedId(null);
      setAdapter(undefined);
      setMode("original");
      setSince("");
      setSubmitError(null);
      setResult(null);
    }
  }, [open]);

  const selected = events.find((e) => e.event_id === selectedId) ?? null;
  const canNext = step === 0 ? selected != null : adapter != null;

  const handleClose = () => {
    replay.reset();
    onClose();
  };

  const handleExecute = () => {
    if (selected == null || adapter == null) return;
    setSubmitError(null);
    replay.mutate(
      { adapter, since: since ? new Date(since).toISOString() : undefined },
      {
        onSuccess: (data) => setResult(data),
        onError: (error) => {
          setSubmitError(
            error instanceof EdpApiError
              ? errorSpec(error.code).message
              : errorSpec("INTERNAL").message,
          );
        },
      },
    );
  };

  const header = (
    <div className="flex items-center gap-2.5">
      <div
        className="w-10 h-10 rounded-lg bg-primary-50 text-primary grid place-items-center"
        aria-hidden="true"
      >
        <RotateCcw className="w-5 h-5" />
      </div>
      <span className="text-base font-semibold text-foreground">事件回放</span>
    </div>
  );

  const footer = (
    <div className="w-full border-t border-border pt-4 flex items-center justify-between gap-2">
      <Button data-dom-id="replay-cancel" autoInsertSpace={false} onClick={handleClose}>
        取消
      </Button>
      {result == null ? (
        <div className="flex items-center gap-2">
          {step > 0 && (
            <Button
              data-dom-id="replay-prev"
              autoInsertSpace={false}
              onClick={() => setStep((s) => s - 1)}
            >
              上一步
            </Button>
          )}
          {step < 2 ? (
            <Button
              type="primary"
              data-dom-id="replay-next"
              autoInsertSpace={false}
              disabled={!canNext}
              icon={<ChevronRight className="w-4 h-4" aria-hidden="true" />}
              iconPosition="end"
              onClick={() => setStep((s) => s + 1)}
            >
              下一步
            </Button>
          ) : (
            <Button
              type="primary"
              data-dom-id="replay-execute"
              autoInsertSpace={false}
              loading={replay.isPending}
              disabled={adapter == null}
              onClick={handleExecute}
            >
              执行回放
            </Button>
          )}
        </div>
      ) : (
        <Button type="primary" data-dom-id="replay-done" autoInsertSpace={false} onClick={handleClose}>
          完成
        </Button>
      )}
    </div>
  );

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      width={720}
      title={header}
      footer={footer}
      getContainer={false}
      destroyOnClose
    >
      <div data-dom-id="replay-wizard" className="flex flex-col gap-4 pt-1">
        <div data-dom-id="replay-steps">
          <Steps
            size="small"
            current={step}
            items={[
              { title: "选择事件", description: selected ? shortId(selected.event_id) : "未选择" },
              { title: "配置参数", description: "目标与模式" },
              { title: "确认执行", description: "核对与下发" },
            ]}
          />
        </div>

        {step === 0 && (
          <div data-dom-id="replay-step-1">
            {events.length === 0 ? (
              <div className="text-xs text-muted-foreground py-8 text-center">
                当前页暂无可回放事件
              </div>
            ) : (
              <Radio.Group
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value as string)}
                className="!flex flex-col gap-2 w-full"
              >
                {events.map((e) => {
                  const type = eventTypeDisplay(e.event_type);
                  const active = selectedId === e.event_id;
                  return (
                    <Radio
                      key={e.event_id}
                      value={e.event_id}
                      data-dom-id="replay-event-option"
                      className={`!m-0 !flex !items-start w-full gap-2.5 border rounded-lg px-3 py-2.5 cursor-pointer ${
                        active ? "border-primary bg-primary-50" : "border-border bg-card hover:bg-muted"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <MonoId
                            prefix="evt"
                            id={e.event_id.slice(-8)}
                            full={e.event_id}
                            copyable={false}
                          />
                          <StatusPill tone={type.tone} label={type.label} size="sm" />
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">
                          {describe(e)}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          {fmtDateTime(e.occurred_at)} · {sourceLabel(e.source_system)}
                        </div>
                      </div>
                    </Radio>
                  );
                })}
              </Radio.Group>
            )}
          </div>
        )}

        {step === 1 && selected != null && (
          <div data-dom-id="replay-step-2" className="space-y-4">
            <div>
              <label
                htmlFor="replay-adapter"
                className="block text-xs font-medium text-foreground mb-1.5"
              >
                目标适配器
              </label>
              <Select
                id="replay-adapter"
                data-dom-id="replay-adapter"
                className="w-full"
                placeholder="选择目标适配器"
                value={adapter}
                onChange={(v) => setAdapter(v)}
                loading={adaptersQuery.isPending}
                options={adaptersQuery.data ?? []}
              />
              <p className="text-[10px] text-muted-foreground mt-1.5">
                回放事件将被投递至所选适配器的输入队列。
              </p>
            </div>

            <div>
              <span className="block text-xs font-medium text-foreground mb-1.5">回放模式</span>
              <Radio.Group value={mode} onChange={(e) => setMode(e.target.value as ReplayMode)}>
                <div className="flex items-center gap-3">
                  {MODE_OPTIONS.map((m) => (
                    <Radio
                      key={m.value}
                      value={m.value}
                      data-dom-id={`replay-mode-${m.value}`}
                      className={`!m-0 border rounded-lg px-3 py-2 cursor-pointer ${
                        mode === m.value
                          ? "border-primary bg-primary-50"
                          : "border-border bg-card hover:bg-muted"
                      }`}
                    >
                      {m.label}
                    </Radio>
                  ))}
                </div>
              </Radio.Group>
              <p className="text-[10px] text-muted-foreground mt-1.5">
                按原序保留事件时间戳顺序；并发可提升吞吐但可能改变因果顺序。
              </p>
            </div>

            <div>
              <label
                htmlFor="replay-since"
                className="block text-xs font-medium text-foreground mb-1.5"
              >
                开始时间（可选）
              </label>
              <Input
                id="replay-since"
                data-dom-id="replay-since"
                type="datetime-local"
                value={since}
                onChange={(e) => setSince(e.target.value)}
              />
              <p className="text-[10px] text-muted-foreground mt-1.5">
                留空则重放全部历史事件；设置后仅重放该时间之后发生的事件。
              </p>
            </div>

            <EventSummaryCard event={selected} />
          </div>
        )}

        {step === 2 && selected != null && (
          <div data-dom-id="replay-step-3" className="space-y-4">
            {result == null ? (
              <>
                <EventSummaryCard event={selected} />
                <div className="text-[11px] text-muted-foreground">
                  目标适配器：<span className="text-foreground font-medium">{adapter}</span> ·
                  回放模式：{mode === "original" ? "按原序" : "并发"}
                </div>
                {submitError != null && (
                  <div
                    data-dom-id="replay-error"
                    role="alert"
                    className="flex items-center gap-1.5 text-xs text-state-error"
                  >
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    {submitError}
                  </div>
                )}
              </>
            ) : (
              <div
                data-dom-id="replay-result"
                className="border border-border rounded-xl p-5 flex flex-col items-center text-center gap-3"
              >
                <div className="w-12 h-12 rounded-full bg-state-success-bg text-state-success grid place-items-center">
                  <CheckCircle2 className="w-6 h-6" aria-hidden="true" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-foreground">回放已下发</div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    任务已下发至目标适配器，可在适配器管理页查看执行状态。
                  </div>
                </div>
                <div className="w-full grid grid-cols-2 gap-2 text-[11px]">
                  <div className="bg-muted rounded-md px-3 py-2 text-left">
                    <span className="text-muted-foreground block">任务 ID</span>
                    <span
                      data-dom-id="replay-sync-id"
                      className="font-mono text-foreground break-all"
                    >
                      {result.sync_id}
                    </span>
                  </div>
                  <div className="bg-muted rounded-md px-3 py-2 text-left">
                    <span className="text-muted-foreground block">状态</span>
                    <span data-dom-id="replay-status">
                      <StatusPill tone="info" label={result.status} size="sm" />
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
