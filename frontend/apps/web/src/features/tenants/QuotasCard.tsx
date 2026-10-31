import { message } from "antd";
import { Gauge, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ModalForm } from "../../components/ModalForm";
import { fmt, fmtDateTime } from "../../lib/labels";
import type { TenantQuotaDetailData } from "./api";
import { useTenantQuotas, useUpdateQuotas } from "./hooks";

/** 七字段展示清单（B.14 完整配额：六配额字段 + 调整时间）。 */
const QUOTA_FIELDS: { key: keyof TenantQuotaDetailData; label: string; unit?: string }[] = [
  { key: "api_rate_limit", label: "API 速率上限", unit: "次/分" },
  { key: "batch_max_events", label: "批量事件上限", unit: "条/批" },
  { key: "events_per_month", label: "月事件配额", unit: "条/月" },
  { key: "pool_share", label: "资源池份额" },
  { key: "query_timeout_ms", label: "查询超时", unit: "ms" },
  { key: "storage_gb", label: "存储配额", unit: "GB" },
];

const inputClass =
  "h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

/** 配额卡（EDP-501）：七字段只读网格 + 「调整配额」→ PATCH 弹窗（三字段可调 + reason 必填）。 */
export function QuotasCard({ tenantId }: { tenantId: string }) {
  const quotasQuery = useTenantQuotas(tenantId);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const quotas = quotasQuery.data;

  return (
    <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id="tenant-quotas">
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <span className="text-primary">
          <Gauge className="w-4 h-4" aria-hidden="true" />
        </span>
        <span className="text-xs font-semibold text-foreground">配额</span>
        <span className="ml-auto">
          <button
            type="button"
            data-dom-id="quota-adjust"
            disabled={quotas == null}
            onClick={() => setAdjustOpen(true)}
            className="h-8 px-3 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted flex items-center gap-1.5 disabled:opacity-50"
          >
            <Settings2 className="w-3.5 h-3.5" aria-hidden="true" />
            调整配额
          </button>
        </span>
      </header>
      <div className="p-4" data-dom-id="tenant-quotas-body">
        {quotas == null ? (
          <div className="text-xs text-muted-foreground py-4 text-center">配额信息暂不可用</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2" data-dom-id="quota-fields">
              {QUOTA_FIELDS.map((field) => {
                const value = quotas[field.key];
                const display =
                  field.key === "pool_share"
                    ? String(value)
                    : fmt(Number(value));
                return (
                  <div key={String(field.key)} className="bg-muted rounded-md px-2.5 py-2" data-dom-id={`quota-${String(field.key)}`}>
                    <span className="text-[10px] text-muted-foreground block">
                      {field.label}
                      {field.unit != null ? `（${field.unit}）` : ""}
                    </span>
                    <span className="text-xs font-medium text-foreground break-all">{display}</span>
                  </div>
                );
              })}
              <div className="bg-muted rounded-md px-2.5 py-2" data-dom-id="quota-updated_at">
                <span className="text-[10px] text-muted-foreground block">最近调整</span>
                <span className="text-xs font-medium text-foreground">
                  {quotas.updated_at != null ? fmtDateTime(quotas.updated_at) : "—"}
                </span>
              </div>
            </div>
            <p className="mt-3 text-[10px] text-muted-foreground">
              临时提额仅可调 API 速率 / 存储 / 月事件配额，需填写调整原因（审计留痕）。
            </p>
          </>
        )}
      </div>
      {quotas != null && (
        <QuotaAdjustModal
          open={adjustOpen}
          onClose={() => setAdjustOpen(false)}
          tenantId={tenantId}
          quotas={quotas}
        />
      )}
    </section>
  );
}

/** 调整配额弹窗：api_rate_limit / storage_gb / events_per_month 可改 + reason 必填（空则禁用提交）。 */
function QuotaAdjustModal({
  open,
  onClose,
  tenantId,
  quotas,
}: {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  quotas: TenantQuotaDetailData;
}) {
  const [apiRateLimit, setApiRateLimit] = useState(String(quotas.api_rate_limit));
  const [storageGb, setStorageGb] = useState(String(quotas.storage_gb));
  const [eventsPerMonth, setEventsPerMonth] = useState(String(quotas.events_per_month));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const updateQuotas = useUpdateQuotas(tenantId);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setApiRateLimit(String(quotas.api_rate_limit));
    setStorageGb(String(quotas.storage_gb));
    setEventsPerMonth(String(quotas.events_per_month));
    setReason("");
    setError(null);
  }, [open, quotas]);

  const reasonEmpty = reason.trim() === "";
  const canSubmit = !reasonEmpty && !updateQuotas.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      setError("请填写调整原因");
      return;
    }
    setError(null);
    updateQuotas.mutate(
      {
        api_rate_limit: Number(apiRateLimit),
        storage_gb: Number(storageGb),
        events_per_month: Number(eventsPerMonth),
        reason: reason.trim(),
      },
      {
        onSuccess: () => {
          void message.success("配额已调整");
          void queryClient.invalidateQueries({ queryKey: ["tenants", "quotas", tenantId] });
          void queryClient.invalidateQueries({ queryKey: ["tenants", "detail", tenantId] });
          onClose();
        },
        onError: () => setError("调整失败，请稍后重试"),
      },
    );
  };

  return (
    <ModalForm
      open={open}
      title="调整配额"
      icon={<Settings2 className="w-5 h-5" aria-hidden="true" />}
      width={480}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="确认调整"
      confirmLoading={updateQuotas.isPending}
      submitDisabled={reasonEmpty}
    >
      <div className="space-y-4 pt-2" data-dom-id="quota-adjust-form">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">API 速率上限（次/分）</div>
          <input
            type="number"
            min={1}
            data-dom-id="quota-input-api_rate_limit"
            aria-label="API 速率上限"
            value={apiRateLimit}
            onChange={(e) => setApiRateLimit(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">存储配额（GB）</div>
          <input
            type="number"
            min={1}
            data-dom-id="quota-input-storage_gb"
            aria-label="存储配额"
            value={storageGb}
            onChange={(e) => setStorageGb(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">月事件配额（条/月）</div>
          <input
            type="number"
            min={1}
            data-dom-id="quota-input-events_per_month"
            aria-label="月事件配额"
            value={eventsPerMonth}
            onChange={(e) => setEventsPerMonth(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            调整原因 <span className="text-state-error">*</span>
          </div>
          <textarea
            rows={2}
            data-dom-id="quota-input-reason"
            aria-label="调整原因"
            placeholder="例如：大促期间临时提额，有效期 7 天"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setError(null);
            }}
            className="w-full text-xs bg-muted border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
          {reasonEmpty && (
            <p className="mt-1 text-[10px] text-state-warning" data-dom-id="quota-reason-hint">
              调整原因必填（审计留痕）
            </p>
          )}
        </div>
        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="quota-adjust-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
