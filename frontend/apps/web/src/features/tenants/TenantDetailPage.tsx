import { App as AntdApp, Skeleton } from "antd";
import { AlertTriangle, ArrowLeft, Ban, PlayCircle, UserPlus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { EmptyState, MonoId, StatusPill, roleLabel, planLabel, TENANT_STATUS_LABELS } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import type { TenantDetailData, TenantMemberRow } from "./api";
import { InviteMemberModal } from "./InviteMemberModal";
import { PermissionModal } from "./PermissionModal";
import { QuotasCard } from "./QuotasCard";
import { useCancelTenant, useResumeTenant, useSuspendTenant, useTenantDetail, useTenantMembers } from "./hooks";

/** 成员状态展示（B.14 tenant_members.status 三值）。 */
const MEMBER_STATUS_LABELS: Record<string, { label: string; tone: "success" | "info" | "muted" }> = {
  INVITED: { label: "已邀请", tone: "info" },
  ACTIVE: { label: "正常", tone: "success" },
  DISABLED: { label: "已禁用", tone: "muted" },
};

/**
 * 租户详情页（EDP-501）：基本信息卡 + QuotasCard（七字段 + 调整配额）
 * + 成员表（邀请/权限分配）+ 生命周期操作区（ACTIVE：暂停/注销；SUSPENDED：恢复）。
 * 注销为强确认（删除确认稿语义：输入 slug 解锁 + reason 必填 + 工单号可选）。
 */
export function TenantDetailPage() {
  const { tenant_id: tenantId } = useParams();
  const { message } = AntdApp.useApp();
  const detailQuery = useTenantDetail(tenantId);
  const membersQuery = useTenantMembers(tenantId);
  const queryClient = useQueryClient();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [permMember, setPermMember] = useState<TenantMemberRow | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const suspend = useSuspendTenant();
  const resume = useResumeTenant();

  const detail = detailQuery.data;
  const members = membersQuery.data?.items ?? [];

  const invalidateDetail = () => {
    void queryClient.invalidateQueries({ queryKey: ["tenants", "detail", tenantId] });
    void queryClient.invalidateQueries({ queryKey: ["tenants", "list"] });
  };

  const handleSuspend = () => {
    if (!tenantId) return;
    suspend.mutate(tenantId, {
      onSuccess: () => {
        void message.success("暂停已受理");
        invalidateDetail();
      },
    });
  };

  const handleResume = () => {
    if (!tenantId) return;
    resume.mutate(tenantId, {
      onSuccess: () => {
        void message.success("恢复已受理");
        invalidateDetail();
      },
    });
  };

  const statusDisplay = detail ? TENANT_STATUS_LABELS[detail.status] : undefined;

  return (
    <div className="space-y-4" data-dom-id="tenant-detail-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            to="/tenants"
            aria-label="返回租户列表"
            data-dom-id="tenant-detail-back"
            className="h-9 px-3 border border-border bg-card text-muted-foreground rounded-lg text-xs font-medium hover:bg-muted flex items-center gap-1.5 shrink-0"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            返回
          </Link>
          <h1 className="text-xl font-semibold text-foreground whitespace-nowrap">租户详情</h1>
          {tenantId != null && <MonoId prefix="tenant" id={tenantId} />}
        </div>
        {detail != null && statusDisplay != null && (
          <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} />
        )}
      </section>

      {detailQuery.isError && detail == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="tenant-detail-error"
        >
          租户详情暂不可用
        </div>
      ) : detail == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 10 }} />
        </div>
      ) : (
        <>
          {/* ① 基本信息卡 */}
          <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id="tenant-basic">
            <header className="px-4 py-3 border-b border-border flex items-center gap-2">
              <span className="text-xs font-semibold text-foreground">基本信息</span>
            </header>
            <div className="p-4 space-y-2 text-xs max-w-xl" data-dom-id="tenant-basic-body">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">租户编码</span>
                <span className="font-mono text-foreground">{detail.slug}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">名称</span>
                <span className="text-foreground">{detail.name}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">套餐</span>
                <span className="text-foreground">{planLabel(detail.plan)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">状态</span>
                {statusDisplay != null && <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} size="sm" />}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">创建时间</span>
                <span className="text-foreground">{fmtDateTime(detail.created_at)}</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground shrink-0">租户 ID</span>
                <span className="font-mono text-foreground break-all" title={detail.tenant_id}>
                  {detail.tenant_id}
                </span>
              </div>
            </div>
          </section>

          {/* ② 配额卡 */}
          {tenantId != null && <QuotasCard tenantId={tenantId} />}

          {/* ③ 成员表 */}
          <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id="tenant-members">
            <header className="px-4 py-3 border-b border-border flex items-center gap-2">
              <span className="text-xs font-semibold text-foreground">成员</span>
              <span className="text-[10px] text-muted-foreground">
                共 {membersQuery.data?.total ?? members.length} 人
              </span>
              <span className="ml-auto">
                <button
                  type="button"
                  data-dom-id="member-invite"
                  onClick={() => setInviteOpen(true)}
                  className="h-8 px-3 bg-primary text-primary-foreground rounded-lg text-xs hover:opacity-90 flex items-center gap-1.5"
                >
                  <UserPlus className="w-3.5 h-3.5" aria-hidden="true" />
                  邀请成员
                </button>
              </span>
            </header>
            <div className="overflow-x-auto" data-dom-id="tenant-members-table">
              {members.length === 0 && membersQuery.isSuccess ? (
                <div data-dom-id="tenant-members-empty">
                  <EmptyState
                    icon={<UserPlus className="w-7 h-7" />}
                    title="暂无成员"
                    description="邀请成员并分配角色后，将在此列出租户成员。"
                    primaryAction={{ label: "邀请成员", onClick: () => setInviteOpen(true) }}
                  />
                </div>
              ) : membersQuery.isError ? (
                <div
                  className="text-xs text-muted-foreground py-8 text-center"
                  data-dom-id="tenant-members-error"
                >
                  成员列表暂不可用，请稍后重试
                </div>
              ) : members.length === 0 ? (
                <div className="text-xs text-muted-foreground py-8 text-center">加载中…</div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                      <th className="px-4 py-2.5 font-medium">成员</th>
                      <th className="px-4 py-2.5 font-medium">成员角色</th>
                      <th className="px-4 py-2.5 font-medium">状态</th>
                      <th className="px-4 py-2.5 font-medium">加入时间</th>
                      <th className="px-4 py-2.5 font-medium text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {members.map((member) => {
                      const memberStatus = MEMBER_STATUS_LABELS[member.status] ?? {
                        label: member.status,
                        tone: "muted" as const,
                      };
                      return (
                        <tr key={member.member_id} data-dom-id={`member-row-${member.member_id}`} className="hover:bg-muted/50 transition-colors">
                          <td className="px-4 py-2.5 text-foreground">{member.display_name ?? "—"}</td>
                          <td className="px-4 py-2.5">
                            <div className="flex flex-wrap gap-1" data-dom-id={`member-roles-${member.member_id}`}>
                              {member.member_roles.length === 0 ? (
                                <span className="text-muted-foreground">—</span>
                              ) : (
                                member.member_roles.map((role) => (
                                  <span
                                    key={role}
                                    className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-primary-50 text-primary"
                                  >
                                    {roleLabel(role)}
                                  </span>
                                ))
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusPill tone={memberStatus.tone} label={memberStatus.label} size="sm" />
                          </td>
                          <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                            {fmtDateTime(member.joined_at)}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <button
                              type="button"
                              data-dom-id={`member-perm-${member.member_id}`}
                              onClick={() => setPermMember(member)}
                              className="h-7 px-2.5 border border-border rounded-lg text-primary hover:bg-muted text-[11px] font-medium"
                            >
                              权限分配
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          {/* ④ 生命周期操作区 */}
          <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id="tenant-lifecycle">
            <header className="px-4 py-3 border-b border-border flex items-center gap-2">
              <span className="text-xs font-semibold text-foreground">生命周期</span>
              {detail.cancel_scheduled_at != null && (
                <span className="text-[10px] text-muted-foreground">
                  注销受理于 {fmtDateTime(detail.cancel_scheduled_at)}
                </span>
              )}
            </header>
            <div className="p-4 flex items-center gap-2">
              {detail.status === "ACTIVE" && (
                <>
                  <button
                    type="button"
                    data-dom-id="tenant-suspend"
                    onClick={handleSuspend}
                    disabled={suspend.isPending}
                    className="h-9 px-4 border border-state-warning/50 bg-state-warning-bg text-state-warning rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <Ban className="w-4 h-4" aria-hidden="true" />
                    暂停
                  </button>
                  <button
                    type="button"
                    data-dom-id="tenant-cancel-open"
                    onClick={() => setCancelOpen(true)}
                    className="h-9 px-4 bg-state-error text-white rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
                  >
                    <AlertTriangle className="w-4 h-4" aria-hidden="true" />
                    注销
                  </button>
                </>
              )}
              {detail.status === "SUSPENDED" && (
                <button
                  type="button"
                  data-dom-id="tenant-resume"
                  onClick={handleResume}
                  disabled={resume.isPending}
                  className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5 disabled:opacity-50"
                >
                  <PlayCircle className="w-4 h-4" aria-hidden="true" />
                  恢复
                </button>
              )}
              {detail.status === "CANCELLED" && (
                <span className="text-xs text-muted-foreground">租户已注销，数据将按保留期清理。</span>
              )}
            </div>
          </section>
        </>
      )}

      {tenantId != null && (
        <>
          <InviteMemberModal open={inviteOpen} onClose={() => setInviteOpen(false)} tenantId={tenantId} />
          <PermissionModal
            open={permMember != null}
            onClose={() => setPermMember(null)}
            tenantId={tenantId}
            member={permMember}
          />
          {detail != null && (
            <CancelTenantModal
              open={cancelOpen}
              onClose={() => setCancelOpen(false)}
              tenantId={tenantId}
              detail={detail}
              onDone={invalidateDetail}
            />
          )}
        </>
      )}
    </div>
  );
}

/** 注销强确认弹窗（删除确认稿语义：输入 slug 解锁 + reason 必填 + 工单号可选）。 */
function CancelTenantModal({
  open,
  onClose,
  tenantId,
  detail,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  detail: TenantDetailData;
  onDone: () => void;
}) {
  const { message } = AntdApp.useApp();
  const [slugInput, setSlugInput] = useState("");
  const [reason, setReason] = useState("");
  const [ticket, setTicket] = useState("");
  const [error, setError] = useState<string | null>(null);
  const cancel = useCancelTenant();

  useEffect(() => {
    if (!open) return;
    setSlugInput("");
    setReason("");
    setTicket("");
    setError(null);
  }, [open]);

  const unlocked = slugInput === detail.slug;
  const reasonEmpty = reason.trim() === "";
  const canSubmit = unlocked && !reasonEmpty && !cancel.isPending;

  const handleConfirm = () => {
    cancel.mutate(
      { tenantId, body: { confirm: true, reason: reason.trim() } },
      {
        onSuccess: () => {
          void message.success("注销已受理");
          onDone();
          onClose();
        },
        onError: () => setError("注销失败，请稍后重试"),
      },
    );
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="注销租户"
      data-dom-id="tenant-cancel-modal"
    >
      <div className="absolute inset-0 bg-black/45" data-dom-id="tenant-cancel-backdrop" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-xl shadow-[var(--edp-shadow-3)] w-full max-w-[480px] mx-4 overflow-hidden">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div
              className="w-8 h-8 rounded-lg bg-state-error-bg text-state-error grid place-items-center"
              aria-hidden="true"
            >
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h2 className="text-sm font-semibold text-foreground">注销租户</h2>
          </div>
          <button
            type="button"
            aria-label="关闭"
            data-dom-id="tenant-cancel-close"
            onClick={onClose}
            className="w-7 h-7 rounded-lg border border-border bg-card grid place-items-center text-muted-foreground hover:bg-muted"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-5 space-y-4">
          <p className="text-sm text-foreground leading-relaxed">
            确定要注销租户
            <code className="mx-1 font-mono text-xs bg-muted px-1.5 py-0.5 rounded text-foreground">
              {detail.slug}
            </code>
            吗？注销后数据将按保留期清理，且无法恢复。
          </p>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              输入租户编码 <span className="font-mono text-foreground normal-case">{detail.slug}</span> 以确认
              <span className="text-state-error">*</span>
            </div>
            <input
              type="text"
              data-dom-id="tenant-cancel-slug"
              aria-label="输入租户编码确认"
              value={slugInput}
              onChange={(e) => {
                setSlugInput(e.target.value);
                setError(null);
              }}
              className="h-9 w-full px-3 text-xs font-mono bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              注销原因 <span className="text-state-error">*</span>
            </div>
            <textarea
              rows={2}
              data-dom-id="tenant-cancel-reason"
              aria-label="注销原因"
              placeholder="例如：合同到期，客户确认退出"
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                setError(null);
              }}
              className="w-full text-xs bg-card border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring resize-none"
            />
            {reasonEmpty && (
              <p className="mt-1 text-[10px] text-state-warning" data-dom-id="tenant-cancel-reason-hint">
                注销原因必填（审计留痕）
              </p>
            )}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              操作工单号（可选）
            </div>
            <input
              type="text"
              data-dom-id="tenant-cancel-ticket"
              aria-label="操作工单号"
              placeholder="例如：OPS-2026-0912"
              value={ticket}
              onChange={(e) => setTicket(e.target.value)}
              className="h-9 w-full px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </div>
          {error != null && (
            <div className="text-[11px] text-state-error" data-dom-id="tenant-cancel-error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="px-5 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            type="button"
            data-dom-id="tenant-cancel-cancel"
            onClick={onClose}
            className="h-9 px-4 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted"
          >
            取消
          </button>
          <button
            type="button"
            data-dom-id="tenant-cancel-confirm"
            onClick={handleConfirm}
            disabled={!canSubmit}
            className="h-9 px-4 bg-state-error text-white rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
            确认注销
          </button>
        </div>
      </div>
    </div>
  );
}
