import { message, Skeleton } from "antd";
import { EdpApiError } from "@edp/api-sdk";
import { ClipboardCheck } from "lucide-react";
import { useState } from "react";
import { EmptyState, StatusPill } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import { riskLabelOf } from "../cases/labels";
import type { PendingDecisionItem } from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import { usePendingDecisions, useSubmitDecision } from "./hooks";

/**
 * 决策页（EDP-404，设计 13.6.5 / 13.9.2）：B.9 待决列表（头部「待决 N」角标 =
 * total_pending，N=0 隐藏）+ 表格（case_no mono/问题截断/风险 pill/创建时间/
 * 操作「审批」）→ 640 档决策表单弹窗（选项 radio + 意见 + Human-Only 标注）；
 * 提交成功 toast「决策已提交」+ 列表刷新（case 移出待决）；403 GUARD_POLICY_DENIED
 * →「该操作仅限人工执行」（13.9.2 逐字）。
 */
export function DecisionsPage() {
  const pendingQuery = usePendingDecisions();
  const submit = useSubmitDecision();
  const [selected, setSelected] = useState<PendingDecisionItem | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const items = pendingQuery.data?.items ?? [];
  const totalPending = pendingQuery.data?.total_pending ?? 0;

  const openForm = (item: PendingDecisionItem) => {
    setSelected(item);
    setModalOpen(true);
  };
  const closeForm = () => {
    setModalOpen(false);
    setSelected(null);
  };

  const handleSubmit = (body: { chosen_option: string; comment?: string; decision_type: "HUMAN" }) => {
    if (selected == null) return;
    submit.mutate(
      { caseId: selected.case_id, body },
      {
        onSuccess: () => {
          void message.success("决策已提交");
          closeForm();
          void pendingQuery.refetch();
        },
        onError: (error) => {
          if (error instanceof EdpApiError && error.code === "GUARD_POLICY_DENIED") {
            // 13.9.2 GUARD_POLICY_DENIED 逐字文案（服务 principal 被策略拒绝）
            void message.warning("该操作仅限人工执行");
            return;
          }
          void message.error(error.message);
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="decisions-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-foreground">决策</h1>
          {pendingQuery.data != null && totalPending > 0 && (
            <span
              data-dom-id="decisions-pending-badge"
              className="inline-flex items-center gap-1 h-6 px-2 rounded-full bg-primary-50 text-primary text-[11px] font-medium"
            >
              <ClipboardCheck className="w-3 h-3" aria-hidden="true" />
              待决 {totalPending}
            </span>
          )}
        </div>
      </section>

      {pendingQuery.isError && pendingQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="decisions-error"
        >
          待决列表暂不可用
        </div>
      ) : pendingQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="decisions-empty">
          <EmptyState
            title="暂无待决案例"
            description="当前没有等待人工审批的决策案例，提交后案例将自动移出待决列表。"
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="decisions-content"
        >
            <div className="table-scroll flex-1 min-h-0" data-dom-id="decisions-table">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="px-4 py-2.5 font-medium">案例编号</th>
                  <th className="px-4 py-2.5 font-medium">问题</th>
                  <th className="px-4 py-2.5 font-medium">风险</th>
                  <th className="px-4 py-2.5 font-medium">创建时间</th>
                  <th className="px-4 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => {
                  const riskDisplay = riskLabelOf(row.risk_level);
                  return (
                    <tr
                      key={row.case_id}
                      data-dom-id={`decisions-row-${row.case_id}`}
                      className="hover:bg-muted/50 transition-colors"
                    >
                      <td className="px-4 py-2.5 font-mono text-foreground whitespace-nowrap">
                        {row.case_no ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 max-w-[360px]">
                        <div className="truncate text-foreground" title={row.question}>
                          {row.question}
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={riskDisplay.tone} label={riskDisplay.label} size="sm" />
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {fmtDateTime(row.created_at)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          data-dom-id={`decisions-approve-${row.case_id}`}
                          onClick={() => openForm(row)}
                          className="h-7 px-2.5 border border-border rounded-lg text-primary hover:bg-muted text-[11px] font-medium"
                        >
                          审批
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

      <DecisionFormModal
        key={selected?.case_id ?? "none"}
        open={modalOpen}
        caseItem={selected}
        submitting={submit.isPending}
        onCancel={closeForm}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
