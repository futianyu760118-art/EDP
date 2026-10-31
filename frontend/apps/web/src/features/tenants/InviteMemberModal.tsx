import { message } from "antd";
import { UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { roleLabel } from "@edp/shared";
import { ModalForm } from "../../components/ModalForm";
import { useInviteMember, usePlatformUsers } from "./hooks";

/** 可分配成员角色（B.14 member_roles；平台运营不在租户成员角色内）。 */
export const MEMBER_ROLE_OPTIONS = ["ADMIN", "MANAGER", "ANALYST"] as const;
export type MemberRole = (typeof MEMBER_ROLE_OPTIONS)[number];

export interface InviteMemberModalProps {
  open: boolean;
  onClose: () => void;
  tenantId: string;
}

/**
 * 邀请成员弹窗（视觉基线 `邀请成员 - 弹窗.html`）：
 * 用户选择（GET /admin/users 真端点 Page 信封——W5-11 收口；目录范围为平台管理员
 * 主租户用户，跨租户通道待契约裁定 W6-07，UI 正常渲染返回数据）+ 成员角色多选 →
 * POST members → 201；409 已在册 → 行内错误；目录 404/失败 → 降级手输 user_id。
 */
export function InviteMemberModal({ open, onClose, tenantId }: InviteMemberModalProps) {
  const [userId, setUserId] = useState("");
  const [roles, setRoles] = useState<MemberRole[]>([]);
  const [error, setError] = useState<string | null>(null);
  const invite = useInviteMember(tenantId);
  const users = usePlatformUsers();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setUserId("");
    setRoles([]);
    setError(null);
  }, [open]);

  const toggleRole = (role: MemberRole) => {
    setError(null);
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  };

  const canSubmit = userId !== "" && roles.length > 0 && !invite.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      setError("请选择用户并至少勾选一个角色");
      return;
    }
    setError(null);
    invite.mutate(
      { user_id: userId, member_roles: roles },
      {
        onSuccess: () => {
          void message.success("邀请已发送");
          void queryClient.invalidateQueries({ queryKey: ["tenants", "members", tenantId] });
          onClose();
        },
        onError: (err) => {
          const code = (err as unknown as { code?: string }).code;
          setError(code === "CONFLICT" ? "该用户已是租户成员" : "邀请失败，请稍后重试");
        },
      },
    );
  };

  return (
    <ModalForm
      open={open}
      title="邀请成员"
      icon={<UserPlus className="w-5 h-5" aria-hidden="true" />}
      width={520}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="发送邀请"
      confirmLoading={invite.isPending}
    >
      <div className="space-y-4 pt-2" data-dom-id="invite-form">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            用户 <span className="text-state-error">*</span>
          </div>
          {users.isError ? (
            <input
              type="text"
              data-dom-id="invite-user-manual"
              aria-label="手动输入用户 ID"
              placeholder="用户目录暂不可用，请输入用户 user_id"
              value={userId}
              onChange={(e) => {
                setUserId(e.target.value.trim());
                setError(null);
              }}
              className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            />
          ) : (
            <select
              data-dom-id="invite-user"
              aria-label="选择用户"
              value={userId}
              onChange={(e) => {
                setUserId(e.target.value);
                setError(null);
              }}
              className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">
                {users.isLoading ? "加载用户目录…" : "请选择用户"}
              </option>
              {users.data?.map((user) => (
                <option key={user.user_id} value={user.user_id}>
                  {user.display_name ? `${user.display_name}（${user.username}）` : user.username}
                </option>
              ))}
            </select>
          )}
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            成员角色 <span className="text-state-error">*</span>
          </div>
          <div className="flex flex-wrap items-center gap-2" data-dom-id="invite-roles">
            {MEMBER_ROLE_OPTIONS.map((role) => {
              const active = roles.includes(role);
              return (
                <label
                  key={role}
                  className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-full border text-xs cursor-pointer transition-colors ${
                    active
                      ? "bg-primary-50 text-primary border-primary/30"
                      : "bg-card text-muted-foreground border-border hover:bg-muted"
                  }`}
                >
                  <input
                    type="checkbox"
                    data-dom-id={`invite-role-${role}`}
                    checked={active}
                    onChange={() => toggleRole(role)}
                    className="w-3.5 h-3.5 accent-primary"
                  />
                  <span>{roleLabel(role)}</span>
                </label>
              );
            })}
          </div>
        </div>

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="invite-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
