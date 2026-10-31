import { message, Skeleton } from "antd";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { DangerConfirm, EmptyState, StatusPill } from "@edp/shared";
import type { PolicyItem } from "./api";
import { useAuditPolicies, useDeletePolicy, useUpdatePolicy } from "./hooks";
import { PolicyCreateModal } from "./PolicyCreateModal";

const ACTOR_LABELS: Record<string, string> = {
  HUMAN: "人工",
  AI: "AI",
  SERVICE: "服务",
};

/** 三维范围摘要：空数组 = 通配（全部）。 */
const rangeOf = (values: string[], labelOf: (v: string) => string = (v) => v): string =>
  values.length === 0 ? "全部（通配）" : values.map(labelOf).join("、");

const statusPillOf = (status: string) =>
  status === "ACTIVE"
    ? { tone: "success" as const, label: "启用中" }
    : { tone: "muted" as const, label: "已停用" };

export interface PolicyTabProps {
  /** 头部「新建策略」按钮共用一个弹窗实例（AuditPage 持有）。 */
  createOpen: boolean;
  onCreateOpen: () => void;
  onCreateClose: () => void;
}

/**
 * 策略 tab（视觉基线 `原型设计/pages/审计日志.html` 左栏策略卡 + 设计 13.6.3）：
 * 策略列表（name/三维范围摘要/notify/status pill）+ 启停开关（PATCH status）+
 * 删除（13.7 #10 一般级危险确认，无强确认短语）+「新建策略」。
 */
export function PolicyTab({ createOpen, onCreateOpen, onCreateClose }: PolicyTabProps) {
  const [statusFilter, setStatusFilter] = useState<"" | "ACTIVE" | "DISABLED">("");
  const [deleting, setDeleting] = useState<PolicyItem | null>(null);
  const policiesQuery = useAuditPolicies(statusFilter || undefined);
  const updatePolicy = useUpdatePolicy();
  const deletePolicy = useDeletePolicy();

  const items = policiesQuery.data?.items ?? [];

  const toggleStatus = (policy: PolicyItem) => {
    const next = policy.status === "ACTIVE" ? "DISABLED" : "ACTIVE";
    updatePolicy.mutate(
      { policyId: policy.policy_id, body: { status: next } },
      {
        onSuccess: () => {
          void message.success(next === "ACTIVE" ? `策略「${policy.name}」已启用` : `策略「${policy.name}」已停用`);
        },
        onError: () => {
          void message.error("策略更新失败，请稍后重试");
        },
      },
    );
  };

  const confirmDelete = () => {
    if (deleting == null) return;
    const target = deleting;
    deletePolicy.mutate(target.policy_id, {
      onSuccess: () => {
        void message.success(`策略「${target.name}」已删除`);
        setDeleting(null);
      },
      onError: () => {
        void message.error("策略删除失败，请稍后重试");
      },
    });
  };

  const activeCount = items.filter((p) => p.status === "ACTIVE").length;

  return (
    <section className="flex flex-col gap-4 flex-1 min-h-0" data-dom-id="audit-policies-tab">
      <div className="bg-card border border-border rounded-xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <select
            data-dom-id="policy-filter-status"
            aria-label="策略状态筛选"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | "ACTIVE" | "DISABLED")}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部状态</option>
            <option value="ACTIVE">启用中</option>
            <option value="DISABLED">已停用</option>
          </select>
          {policiesQuery.data != null && (
            <span className="text-[11px] text-muted-foreground" data-dom-id="policy-count">
              {statusFilter === "" ? `共 ${items.length} 条 · ${activeCount} 条生效中` : `命中 ${items.length} 条`}
            </span>
          )}
        </div>
        <button
          type="button"
          data-dom-id="policy-create-inline"
          onClick={onCreateOpen}
          className="h-9 px-3 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
        >
          <Plus className="w-4 h-4" aria-hidden="true" />
          新建策略
        </button>
      </div>

      {policiesQuery.isError && policiesQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="policy-error"
        >
          策略列表暂不可用
        </div>
      ) : policiesQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 4 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="policy-empty">
          <EmptyState
            title="暂无审计策略"
            description="创建策略后，命中的审计行将携带策略标记，便于回溯与告警。"
            primaryAction={{ label: "新建策略", onClick: onCreateOpen }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="policy-table"
        >
          <div className="table-scroll flex-1 min-h-0">
            <table className="w-full text-xs min-w-[860px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border bg-muted/50">
                  <th className="px-4 py-2.5 font-medium">策略名称</th>
                  <th className="px-4 py-2.5 font-medium">资源类型</th>
                  <th className="px-4 py-2.5 font-medium">动作</th>
                  <th className="px-4 py-2.5 font-medium">触发者</th>
                  <th className="px-4 py-2.5 font-medium">通知渠道</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((policy) => {
                  const pill = statusPillOf(policy.status);
                  const enabled = policy.status === "ACTIVE";
                  return (
                    <tr key={policy.policy_id} data-dom-id={`policy-row-${policy.policy_id}`} className="hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-2.5 max-w-[220px]">
                        <div className="truncate text-foreground font-medium" title={policy.name}>
                          {policy.name}
                        </div>
                        {policy.description != null && (
                          <div className="truncate text-[11px] text-muted-foreground" title={policy.description}>
                            {policy.description}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground max-w-[180px]">
                        <div className="truncate font-mono text-[11px]" title={policy.resource_types.join("、")}>
                          {rangeOf(policy.resource_types)}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground max-w-[160px]">
                        <div className="truncate font-mono text-[11px]" title={policy.actions.join("、")}>
                          {rangeOf(policy.actions)}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {rangeOf(policy.actor_types, (v) => ACTOR_LABELS[v] ?? v)}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {policy.notify_channel ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <span data-dom-id={`policy-status-${policy.policy_id}`}>
                          <StatusPill tone={pill.tone} label={pill.label} size="sm" />
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={enabled}
                          aria-label={enabled ? `停用策略 ${policy.name}` : `启用策略 ${policy.name}`}
                          data-dom-id={`policy-toggle-${policy.policy_id}`}
                          onClick={() => toggleStatus(policy)}
                          disabled={updatePolicy.isPending}
                          title={enabled ? "点击停用" : "点击启用"}
                          className={`relative inline-flex h-[22px] w-[40px] items-center rounded-full transition-colors disabled:opacity-50 ${
                            enabled ? "bg-primary" : "bg-border"
                          }`}
                        >
                          <span
                            className={`absolute top-[2px] h-[18px] w-[18px] rounded-full bg-card shadow transition-transform ${
                              enabled ? "translate-x-[20px]" : "translate-x-[2px]"
                            }`}
                          />
                        </button>
                        <button
                          type="button"
                          aria-label={`删除策略 ${policy.name}`}
                          data-dom-id={`policy-delete-${policy.policy_id}`}
                          onClick={() => setDeleting(policy)}
                          className="ml-2 h-7 px-2.5 border border-border rounded-lg text-state-error hover:bg-state-error-bg text-[11px] font-medium inline-flex items-center gap-1"
                        >
                          <Trash2 className="w-3 h-3" aria-hidden="true" />
                          删除
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <PolicyCreateModal open={createOpen} onClose={onCreateClose} />

      <DangerConfirm
        open={deleting != null}
        title="删除审计策略"
        description={
          <>
            确定删除策略「{deleting?.name}」？删除后该策略立即停止匹配，操作不可恢复。
          </>
        }
        objectName={deleting?.name}
        confirmText="删除策略"
        loading={deletePolicy.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}
