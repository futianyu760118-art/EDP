import { message } from "antd";
import { EdpApiError } from "@edp/api-sdk";
import { ArrowRight, CalendarClock, User, UserCheck, X } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MonoId, StatusPill } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import { actionStatusOf } from "../cases/labels";
import type { ActionDetail, TransitionItem } from "./api";
import { ModalForm } from "../../components/ModalForm";
import { StateMachineTimeline } from "./StateMachineTimeline";
import { useActionDetail, useTransitionAction } from "./hooks";

export interface ActionDetailDrawerProps {
  actionId: string | null;
  open: boolean;
  onClose: () => void;
}

/**
 * 行动详情抽屉（设计 13.6.5 行动页 / 13.7 #8 420px）：头部标题 + 当前 status pill +
 * owner/due 元信息 → 9 态状态轴 → allowed_to 按钮组（human_only 人形图标 +
 * tooltip「仅人工可执行」）→ 转移确认小弹窗（comment + 确认）PATCH：
 * - 422 INVALID_TRANSITION → toast + 重拉详情按服务端 allowed_to 重渲染按钮组；
 * - 409 CONFLICT →「数据已被他人修改，已刷新」toast + 自动重拉详情（13.9.2 逐字）。
 */
export function ActionDetailDrawer({ actionId, open, onClose }: ActionDetailDrawerProps) {
  const queryClient = useQueryClient();
  const detailQuery = useActionDetail(open ? actionId : null);
  const transition = useTransitionAction();
  const [pendingTo, setPendingTo] = useState<TransitionItem | null>(null);
  const [comment, setComment] = useState("");

  if (!open || actionId == null) return null;
  const detail: ActionDetail | undefined = detailQuery.data;
  const allowedTo = detail?.allowed_to ?? [];

  const refetchDetail = () => {
    void queryClient.invalidateQueries({ queryKey: ["actions", "detail", actionId] });
    void queryClient.invalidateQueries({ queryKey: ["actions", "list"] });
  };

  const closeTransitionModal = () => {
    setPendingTo(null);
    setComment("");
  };

  const handleTransition = () => {
    if (detail == null || pendingTo == null) return;
    transition.mutate(
      {
        actionId: detail.action_id,
        body: {
          from_status: detail.status as never,
          to_status: pendingTo.to_status as never,
          comment: comment.trim() ? comment.trim() : undefined,
        },
      },
      {
        onSuccess: () => {
          closeTransitionModal();
          refetchDetail();
        },
        onError: (error) => {
          if (error instanceof EdpApiError) {
            if (error.code === "INVALID_TRANSITION") {
              // 13.9.2：按响应 allowed_to 重渲染状态机按钮——客户端错误体不带 extra，
              // 以详情重拉（状态未变，allowed_to 即响应口径）为准
              void message.error("当前状态不允许该转移，可流转操作已更新");
              refetchDetail();
              return;
            }
            if (error.code === "CONFLICT") {
              // 13.9.2 逐字文案 + 自动重拉详情
              void message.warning("数据已被他人修改，已刷新");
              refetchDetail();
              return;
            }
            if (error.code === "GUARD_POLICY_DENIED") {
              void message.warning("该操作仅限人工执行");
              return;
            }
          }
          void message.error(error.message);
        },
      },
    );
  };

  const statusDisplay = detail != null ? actionStatusOf(detail.status) : null;

  return (
    <div
      className="fixed inset-y-0 left-[250px] right-0 z-30 flex justify-end bg-foreground/15 backdrop-blur-sm"
      data-dom-id="action-drawer-overlay"
    >
      <div
        data-dom-id="action-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="action-drawer-title"
        className="w-[420px] h-full bg-card border-l border-border shadow-2 flex flex-col rounded-l-lg"
      >
        {/* 头部：标题 + 当前 status pill + owner/due 元信息 */}
        <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <h2 id="action-drawer-title" className="text-lg font-semibold text-foreground truncate">
                {detail?.title ?? "行动详情"}
              </h2>
              {statusDisplay != null && (
                <span className="shrink-0" data-dom-id="action-drawer-status">
                  <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} size="sm" />
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
              {detail != null && <MonoId prefix="act" id={detail.action_id} />}
              <span className="inline-flex items-center gap-1">
                <User className="w-3 h-3" aria-hidden="true" />
                {detail?.owner ?? "未指派"}
              </span>
              <span className="inline-flex items-center gap-1">
                <CalendarClock className="w-3 h-3" aria-hidden="true" />
                {detail?.due_date != null ? fmtDateTime(detail.due_date) : "无截止"}
              </span>
            </div>
          </div>
          <button
            type="button"
            data-dom-id="action-drawer-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted grid place-items-center"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {detailQuery.isError ? (
            <div className="text-xs text-muted-foreground py-8 text-center" data-dom-id="action-drawer-error">
              行动详情暂不可用
            </div>
          ) : detail == null ? (
            <div className="text-xs text-muted-foreground py-8 text-center">加载中…</div>
          ) : (
            <>
              {/* 9 态状态轴 */}
              <div data-dom-id="action-drawer-timeline">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">状态机</div>
                <StateMachineTimeline status={detail.status} />
              </div>

              {/* 元信息 */}
              <div className="grid grid-cols-2 gap-2 text-[11px]" data-dom-id="action-drawer-meta">
                <div className="bg-muted rounded-md px-2.5 py-1.5">
                  <span className="text-muted-foreground block">类型</span>
                  <span className="font-mono font-medium text-foreground">{detail.action_type}</span>
                </div>
                <div className="bg-muted rounded-md px-2.5 py-1.5">
                  <span className="text-muted-foreground block">角色</span>
                  <span className="font-medium text-foreground">{detail.owner_role ?? "—"}</span>
                </div>
                {detail.completion_time != null && (
                  <div className="bg-muted rounded-md px-2.5 py-1.5">
                    <span className="text-muted-foreground block">完成时间</span>
                    <span className="font-medium text-foreground">{fmtDateTime(detail.completion_time)}</span>
                  </div>
                )}
                {detail.verified_by != null && (
                  <div className="bg-muted rounded-md px-2.5 py-1.5">
                    <span className="text-muted-foreground block">验证人</span>
                    <span className="font-medium text-foreground">{detail.verified_by}</span>
                  </div>
                )}
                {detail.case_id != null && (
                  <div className="bg-muted rounded-md px-2.5 py-1.5 col-span-2">
                    <span className="text-muted-foreground block">关联案例</span>
                    <span className="font-mono font-medium text-foreground">{detail.case_id}</span>
                  </div>
                )}
              </div>

              {/* allowed_to 按钮组 */}
              <div data-dom-id="action-drawer-transitions">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">可流转操作</div>
                <div className="flex items-center gap-2 flex-wrap">
                  {allowedTo.map((item) => (
                    <button
                      key={item.to_status}
                      type="button"
                      data-dom-id={`transition-btn-${item.to_status}`}
                      title={item.human_only ? "仅人工可执行" : undefined}
                      onClick={() => setPendingTo(item)}
                      className="h-8 px-3 border border-border rounded-lg text-[11px] font-medium text-foreground hover:bg-muted hover:border-primary/50 flex items-center gap-1.5"
                    >
                      {item.to_status}
                      {item.human_only && (
                        <UserCheck
                          className="w-3.5 h-3.5 text-state-warning"
                          aria-hidden="true"
                          data-dom-id={`transition-human-only-${item.to_status}`}
                        />
                      )}
                    </button>
                  ))}
                  {allowedTo.length === 0 && (
                    <span className="text-[11px] text-muted-foreground">终态，无可流转操作</span>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {/* 转移确认小弹窗：comment textarea + 确认 */}
        <ModalForm
          open={pendingTo != null}
          title={pendingTo != null ? `转移至 ${pendingTo.to_status}` : "状态转移"}
          icon={<ArrowRight className="w-5 h-5" aria-hidden="true" />}
          width={480}
          onCancel={closeTransitionModal}
          onSubmit={handleTransition}
          submitText="确认转移"
          confirmLoading={transition.isPending}
        >
          <div data-dom-id="transition-modal" className="space-y-3 pt-2">
            {pendingTo != null && (
              <div className="text-xs text-muted-foreground">
                当前状态 <span className="font-mono text-foreground">{detail?.status}</span> →{" "}
                <span className="font-mono text-foreground">{pendingTo.to_status}</span>
                {pendingTo.human_only && (
                  <span
                    title="仅人工可执行"
                    className="ml-2 inline-flex items-center gap-1 text-state-warning"
                    data-dom-id="transition-modal-human-only"
                  >
                    <UserCheck className="w-3.5 h-3.5" aria-hidden="true" />
                    Human-Only
                  </span>
                )}
              </div>
            )}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">转移意见（可选，落证据链）</div>
              <textarea
                data-dom-id="transition-comment"
                aria-label="转移意见"
                rows={3}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="补充转移理由或执行说明…"
                className="w-full text-xs bg-card border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring resize-none"
              />
            </div>
          </div>
        </ModalForm>
      </div>
    </div>
  );
}
