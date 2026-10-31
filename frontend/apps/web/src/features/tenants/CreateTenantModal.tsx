import { message } from "antd";
import { Building2, Copy, Check, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ModalForm } from "../../components/ModalForm";
import type { TenantCreateResponse, TenantPlan } from "./api";
import { useCreateTenant } from "./hooks";

/** 套餐选项（视觉基线：新建租户弹窗.html 套餐版本单选卡；枚举对齐 B.14 四值）。 */
const PLAN_OPTIONS: { value: TenantPlan; label: string; desc: string }[] = [
  { value: "TRIAL", label: "TRIAL", desc: "体验版" },
  { value: "STANDARD", label: "STANDARD", desc: "基础版" },
  { value: "PREMIUM", label: "PREMIUM", desc: "专业版" },
  { value: "DEDICATED", label: "DEDICATED", desc: "企业版" },
];

const inputClass =
  "h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

const labelClass = "text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5";

export interface CreateTenantModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 新建租户弹窗（EDP-501，视觉基线 `新建租户 - 弹窗.html`）：
 * 租户名称 / 套餐版本单选卡 / 初始管理员（用户名/邮箱/显示名称/初始口令
 * 可选）→ POST /tenants → 201 → 编码由服务端自动生成（ten-YYYY-NNNN，
 * 成功页展示）+ 一次性临时口令展示行（temporary_password 非空时，
 * 仅此一次可见）。
 */
export function CreateTenantModal({ open, onClose }: CreateTenantModalProps) {
  const [name, setName] = useState("");
  const [plan, setPlan] = useState<TenantPlan>("STANDARD");
  const [adminUsername, setAdminUsername] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminDisplayName, setAdminDisplayName] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<TenantCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const createTenant = useCreateTenant();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setName("");
    setPlan("STANDARD");
    setAdminUsername("");
    setAdminEmail("");
    setAdminDisplayName("");
    setAdminPassword("");
    setError(null);
    setCreated(null);
    setCopied(false);
  }, [open]);

  const canSubmit =
    name.trim() !== "" &&
    adminUsername.trim() !== "" &&
    adminEmail.trim() !== "" &&
    adminDisplayName.trim() !== "" &&
    !createTenant.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      setError("请填写带 * 的必填项");
      return;
    }
    setError(null);
    createTenant.mutate(
      {
        name: name.trim(),
        plan,
        admin: {
          username: adminUsername.trim(),
          email: adminEmail.trim(),
          display_name: adminDisplayName.trim(),
          ...(adminPassword.trim() ? { password: adminPassword } : {}),
        },
      },
      {
        onSuccess: (resp) => {
          setCreated(resp);
          void message.success("租户已创建");
          void queryClient.invalidateQueries({ queryKey: ["tenants", "list"] });
        },
        onError: (err) => {
          const code = (err as unknown as { code?: string }).code;
          if (code === "CONFLICT") setError("创建冲突，请重试");
          else setError("创建失败，请稍后重试");
        },
      },
    );
  };

  async function copyTempPassword(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      void message.error("复制失败，请手动选择复制");
    }
  }

  return (
    <ModalForm
      open={open}
      title="新建租户"
      icon={<Building2 className="w-5 h-5" aria-hidden="true" />}
      width={480}
      onCancel={onClose}
      onSubmit={created != null ? onClose : handleSubmit}
      submitText={created != null ? "完成" : "确认创建"}
      confirmLoading={createTenant.isPending}
    >
      {created != null ? (
        <div className="space-y-3 pt-2" data-dom-id="tenant-create-success">
          <p className="text-xs text-muted-foreground">
            租户 <span className="font-mono text-foreground">{created.slug}</span> 已开通（{created.name}）。
          </p>
          {created.temporary_password != null && created.temporary_password !== "" && (
            <div
              className="rounded-lg border border-state-warning/40 bg-state-warning-bg px-3 py-2.5"
              data-dom-id="temp-password-box"
            >
              <div className="flex items-center gap-1.5 text-[10px] text-state-warning font-medium mb-1.5">
                <KeyRound className="w-3.5 h-3.5" aria-hidden="true" />
                初始管理员临时口令（仅此一次可见，请立即交付并要求首登修改）
              </div>
              <div className="flex items-center gap-2">
                <code
                  className="flex-1 font-mono text-xs bg-card border border-border rounded px-2 py-1.5 text-foreground break-all"
                  data-dom-id="temp-password-value"
                >
                  {created.temporary_password}
                </code>
                <button
                  type="button"
                  data-dom-id="temp-password-copy"
                  aria-label="复制临时口令"
                  onClick={() => void copyTempPassword(created.temporary_password!)}
                  className="h-8 w-8 shrink-0 rounded-lg border border-border bg-card grid place-items-center text-muted-foreground hover:bg-muted"
                >
                  {copied ? (
                    <Check className="w-3.5 h-3.5 text-state-success" aria-hidden="true" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4 pt-2" data-dom-id="tenant-create-form">
          <div>
            <div className={labelClass}>
              租户名称 <span className="text-state-error">*</span>
            </div>
            <input
              type="text"
              data-dom-id="tenant-name"
              aria-label="租户名称"
              placeholder="例如：ACME · 华东事业群"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              className={inputClass}
            />
            <p className="mt-1.5 text-[10px] text-muted-foreground">
              租户编码由系统自动生成（ten-年份-序号），创建后不可修改。
            </p>
          </div>

          <div>
            <div className={labelClass}>
              套餐版本 <span className="text-state-error">*</span>
            </div>
            <div className="grid grid-cols-2 gap-2" data-dom-id="tenant-plan-options">
              {PLAN_OPTIONS.map((option) => {
                const active = plan === option.value;
                return (
                  <label
                    key={option.value}
                    className={`flex items-center gap-2 h-11 px-3 border rounded-lg cursor-pointer transition-colors ${
                      active ? "border-primary bg-primary-50" : "border-border bg-card hover:bg-muted"
                    }`}
                  >
                    <input
                      type="radio"
                      name="tenant-plan"
                      data-dom-id={`tenant-plan-${option.value}`}
                      checked={active}
                      onChange={() => setPlan(option.value)}
                      className="accent-primary"
                    />
                    <span className="text-xs font-medium text-foreground">{option.label}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{option.desc}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="border-t border-border pt-4">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
              初始管理员 <span className="text-state-error">*</span>
            </div>
            <div className="space-y-3">
              <input
                type="text"
                data-dom-id="tenant-admin-username"
                aria-label="管理员用户名"
                placeholder="用户名（租户内唯一）"
                value={adminUsername}
                onChange={(e) => setAdminUsername(e.target.value)}
                className={inputClass}
              />
              <input
                type="email"
                data-dom-id="tenant-admin-email"
                aria-label="管理员邮箱"
                placeholder="admin@example.com"
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                className={inputClass}
              />
              <input
                type="text"
                data-dom-id="tenant-admin-display"
                aria-label="管理员显示名称"
                placeholder="显示名称（如：张三）"
                value={adminDisplayName}
                onChange={(e) => setAdminDisplayName(e.target.value)}
                className={inputClass}
              />
              <div>
                <input
                  type="password"
                  data-dom-id="tenant-admin-password"
                  aria-label="初始口令"
                  placeholder="初始口令（可选）"
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  className={inputClass}
                />
                <p className="mt-1.5 text-[10px] text-muted-foreground">
                  留空则由系统生成一次性临时口令，创建成功后仅展示一次。
                </p>
              </div>
            </div>
          </div>

          {error != null && (
            <div className="text-[11px] text-state-error" data-dom-id="tenant-create-error" role="alert">
              {error}
            </div>
          )}
        </div>
      )}
    </ModalForm>
  );
}
