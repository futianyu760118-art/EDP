import { message } from "antd";
import { UserCog } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { roleLabel } from "@edp/shared";
import { ModalForm } from "../../components/ModalForm";
import type { TenantMemberRow } from "./api";
import { useUpdateMember } from "./hooks";
import { MEMBER_ROLE_OPTIONS, type MemberRole } from "./InviteMemberModal";

export interface PermissionModalProps {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  member: TenantMemberRow | null;
}

/**
 * 权限分配弹窗（视觉基线 `权限分配 - 弹窗.html`）：
 * 成员角色 checkbox 组 → PATCH members/{member_id} → 200 更新。
 * 标题/按钮文案沿稿（分配角色权限 / 保存权限）。
 */
export function PermissionModal({ open, onClose, tenantId, member }: PermissionModalProps) {
  const [roles, setRoles] = useState<MemberRole[]>([]);
  const [error, setError] = useState<string | null>(null);
  const updateMember = useUpdateMember(tenantId);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open || !member) return;
    setRoles(member.member_roles.filter((r): r is MemberRole =>
      (MEMBER_ROLE_OPTIONS as readonly string[]).includes(r),
    ));
    setError(null);
  }, [open, member]);

  const toggleRole = (role: MemberRole) => {
    setError(null);
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  };

  const canSubmit = roles.length > 0 && !updateMember.isPending;

  const handleSubmit = () => {
    if (!member) return;
    if (!canSubmit) {
      setError("至少保留一个角色");
      return;
    }
    setError(null);
    updateMember.mutate(
      { memberId: member.member_id, body: { member_roles: roles } },
      {
        onSuccess: () => {
          void message.success("成员角色已更新");
          void queryClient.invalidateQueries({ queryKey: ["tenants", "members", tenantId] });
          onClose();
        },
        onError: () => setError("保存失败，请稍后重试"),
      },
    );
  };

  return (
    <ModalForm
      open={open}
      title="分配角色权限"
      icon={<UserCog className="w-5 h-5" aria-hidden="true" />}
      width={520}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="保存权限"
      confirmLoading={updateMember.isPending}
    >
      <div className="space-y-4 pt-2" data-dom-id="permission-form">
        {member != null && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border border-border">
            <div className="w-9 h-9 rounded-lg bg-primary text-primary-foreground grid place-items-center shrink-0">
              <UserCog className="w-4 h-4" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-foreground truncate">
                  {member.display_name ?? "未命名成员"}
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary-50 text-primary font-medium">
                  {member.member_roles.map((r) => roleLabel(r)).join(" / ") || "无角色"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">
                调整该成员在当前租户的角色，保存后立即生效。
              </p>
            </div>
          </div>
        )}

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">成员角色</div>
          <div className="space-y-2" data-dom-id="permission-roles">
            {MEMBER_ROLE_OPTIONS.map((role) => (
              <label
                key={role}
                className="flex items-center gap-2.5 px-3 py-2.5 border border-border rounded-lg bg-card hover:bg-muted cursor-pointer"
              >
                <input
                  type="checkbox"
                  data-dom-id={`permission-role-${role}`}
                  checked={roles.includes(role)}
                  onChange={() => toggleRole(role)}
                  className="w-4 h-4 rounded border-border accent-primary"
                />
                <span className="text-xs text-foreground">{roleLabel(role)}</span>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">{role}</span>
              </label>
            ))}
          </div>
        </div>

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="permission-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
