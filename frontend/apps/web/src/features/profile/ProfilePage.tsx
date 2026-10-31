import { message } from "antd";
import { IdCard, KeyRound, Palette, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { StatusPill } from "@edp/shared";
import { EdpApiError } from "@edp/api-sdk";
import { useThemeStore } from "../../app/providers/theme-store";
import { useChangePassword, useMe, useUpdateProfile } from "./hooks";

const inputCls =
  "h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";
const labelCls = "text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5";

function SectionCard({
  domId,
  icon,
  title,
  children,
}: {
  domId: string;
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id={domId}>
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        <span className="text-xs font-semibold text-foreground">{title}</span>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ProfilePage() {
  const { data: me } = useMe();
  const updateProfile = useUpdateProfile();
  const changePassword = useChangePassword();
  const { theme, setTheme } = useThemeStore();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [profileError, setProfileError] = useState<string | null>(null);

  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdError, setPwdError] = useState<string | null>(null);

  useEffect(() => {
    if (me) {
      setDisplayName(me.display_name ?? "");
      setEmail(me.email ?? "");
    }
  }, [me]);

  const saveProfile = () => {
    setProfileError(null);
    updateProfile.mutate(
      { display_name: displayName.trim(), email: email.trim() },
      {
        onSuccess: () => void message.success("个人资料已保存"),
        onError: (err) =>
          setProfileError(
            err instanceof EdpApiError ? err.message : "保存失败，请重试",
          ),
      },
    );
  };

  const submitPassword = () => {
    if (newPwd !== confirmPwd) {
      setPwdError("两次输入的新密码不一致");
      return;
    }
    setPwdError(null);
    changePassword.mutate(
      { old_password: oldPwd, new_password: newPwd },
      {
        onSuccess: () => {
          void message.success("密码已更新");
          setOldPwd("");
          setNewPwd("");
          setConfirmPwd("");
        },
        onError: (err) =>
          setPwdError(
            err instanceof EdpApiError ? err.message : "修改失败，请重试",
          ),
      },
    );
  };

  return (
    <div className="space-y-4" data-dom-id="profile-page">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <SectionCard domId="profile-section-identity" icon={<IdCard className="w-4 h-4" />} title="个人资料">
          <div className="space-y-3">
            <div>
              <div className={labelCls}>用户名（登录标识，不可修改）</div>
              <input type="text" data-dom-id="profile-username" aria-label="用户名" disabled value={me?.username ?? ""} className={`${inputCls} opacity-60`} />
            </div>
            <div>
              <div className={labelCls}>显示名称</div>
              <input type="text" data-dom-id="profile-display-name" aria-label="显示名称" placeholder="请输入显示名称" value={displayName} onChange={(e) => { setDisplayName(e.target.value); setProfileError(null); }} className={inputCls} />
            </div>
            <div>
              <div className={labelCls}>邮箱</div>
              <input type="email" data-dom-id="profile-email" aria-label="邮箱" placeholder="name@example.com" value={email} onChange={(e) => { setEmail(e.target.value); setProfileError(null); }} className={inputCls} />
            </div>
            {profileError != null && (
              <div className="text-[11px] text-state-error" data-dom-id="profile-save-error" role="alert">{profileError}</div>
            )}
            <div className="flex justify-end">
              <button type="button" data-dom-id="profile-save" onClick={saveProfile} disabled={updateProfile.isPending} className="h-9 px-4 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {updateProfile.isPending ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        </SectionCard>

        <SectionCard domId="profile-section-password" icon={<KeyRound className="w-4 h-4" />} title="修改密码">
          <div className="space-y-3">
            <div>
              <div className={labelCls}>当前密码</div>
              <input type="password" data-dom-id="profile-old-password" aria-label="当前密码" value={oldPwd} onChange={(e) => { setOldPwd(e.target.value); setPwdError(null); }} className={inputCls} />
            </div>
            <div>
              <div className={labelCls}>新密码（至少 8 位，含字母与数字）</div>
              <input type="password" data-dom-id="profile-new-password" aria-label="新密码" value={newPwd} onChange={(e) => { setNewPwd(e.target.value); setPwdError(null); }} className={inputCls} />
            </div>
            <div>
              <div className={labelCls}>确认新密码</div>
              <input type="password" data-dom-id="profile-confirm-password" aria-label="确认新密码" value={confirmPwd} onChange={(e) => { setConfirmPwd(e.target.value); setPwdError(null); }} className={inputCls} />
            </div>
            {pwdError != null && (
              <div className="text-[11px] text-state-error" data-dom-id="profile-password-error" role="alert">{pwdError}</div>
            )}
            <div className="flex justify-end">
              <button type="button" data-dom-id="profile-password-submit" onClick={submitPassword} disabled={changePassword.isPending} className="h-9 px-4 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {changePassword.isPending ? "提交中…" : "更新密码"}
              </button>
            </div>
          </div>
        </SectionCard>

        <SectionCard domId="profile-section-preference" icon={<Palette className="w-4 h-4" />} title="偏好设置">
          <div className="space-y-3">
            <div>
              <div className={labelCls}>界面主题</div>
              <div className="flex gap-2" data-dom-id="profile-theme-options">
                {(["light", "dark"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    data-dom-id={`profile-theme-${mode}`}
                    aria-pressed={theme === mode}
                    onClick={() => setTheme(mode)}
                    className={`h-9 px-4 text-xs rounded-lg border transition-colors ${
                      theme === mode
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-muted border-border text-foreground hover:bg-muted/70"
                    }`}
                  >
                    {mode === "light" ? "浅色" : "深色"}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard domId="profile-section-session" icon={<ShieldCheck className="w-4 h-4" />} title="会话与权限">
          <div className="space-y-3">
            <div>
              <div className={labelCls}>角色</div>
              <div className="flex flex-wrap gap-1.5" data-dom-id="profile-roles">
                {(me?.roles ?? []).map((role) => (
                  <StatusPill key={role} tone="info" label={role} size="sm" />
                ))}
                {me?.is_platform_admin === true && <StatusPill tone="warning" label="平台管理员" size="sm" />}
              </div>
            </div>
            <div>
              <div className={labelCls}>权限（{me?.permissions.length ?? 0} 项）</div>
              <div className="flex flex-wrap gap-1.5" data-dom-id="profile-permissions">
                {(me?.permissions ?? []).map((perm) => (
                  <code key={perm} className="px-1.5 py-0.5 text-[10px] font-mono bg-muted rounded">{perm}</code>
                ))}
              </div>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
