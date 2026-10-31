import { App as AntdApp, Button, Modal } from "antd";
import { Check, ChevronRight, Info } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSessionStore } from "../features/auth/session-store";
import { useSwitchTenantContext, useTenantSwitchOptions } from "../features/tenants/hooks";
import { initials, planLabel } from "../lib/labels";

/**
 * 切换租户弹窗（EDP-501：W1 静态清单 → 真调用）：
 * 目标清单仅 ACTIVE；确认 → POST /tenants/{id}/context → access_token
 * 替换本地 token（refresh_token 沿用）→ 顶栏/侧栏租户名更新（session store）
 * → queryClient.clear() 全站重拉 → toast「已切换」。
 */
export function TenantSwitchModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntdApp.useApp();
  const tenant = useSessionStore((s) => s.tenant);
  const setTenant = useSessionStore((s) => s.setTenant);
  const currentSlug = tenant?.slug ?? "default";
  const [selected, setSelected] = useState<string | null>(null);
  const optionsQuery = useTenantSwitchOptions();
  const switchContext = useSwitchTenantContext();
  const queryClient = useQueryClient();

  const options = optionsQuery.data?.items ?? [];
  const effectiveSlug = selected ?? currentSlug;
  const target = options.find((t) => t.slug === effectiveSlug) ?? null;
  const isCurrent = effectiveSlug === currentSlug;

  function handleConfirm() {
    if (!target || isCurrent) {
      onClose();
      return;
    }
    switchContext.mutate(target.tenant_id, {
      onSuccess: (resp) => {
        const refreshToken = useSessionStore.getState().refreshToken;
        useSessionStore.getState().updateTokens({
          accessToken: resp.access_token,
          refreshToken: refreshToken ?? resp.access_token,
        });
        setTenant({
          slug: target.slug,
          name: target.name,
          plan: target.plan,
          status: "ACTIVE",
        });
        queryClient.clear();
        void message.success("已切换");
        setSelected(null);
        onClose();
      },
      onError: () => {
        void message.error("切换失败，请稍后重试");
      },
    });
  }

  return (
    <Modal
      title="切换租户 / 工作空间"
      open={open}
      onCancel={onClose}
      destroyOnClose
      width={420}
      footer={
        <Button
          type="primary"
          block
          data-dom-id="tenant-switch-confirm"
          loading={switchContext.isPending}
          disabled={target == null || isCurrent}
          onClick={handleConfirm}
        >
          确认切换
        </Button>
      }
    >
      <p
        className="text-[11px] text-state-info bg-state-info-bg rounded-lg px-3 py-2 mb-3 flex items-start gap-1.5"
        data-dom-id="tenant-switch-impact"
      >
        <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" aria-hidden="true" />
        切换后将以目标租户身份重新加载数据，当前页面与查询缓存将全部刷新。
      </p>
      <div className="flex flex-col gap-2 py-2" data-dom-id="tenant-switch-list">
        {optionsQuery.isLoading ? (
          <div className="text-xs text-muted-foreground py-4 text-center">加载租户清单…</div>
        ) : optionsQuery.isError ? (
          <div className="text-xs text-muted-foreground py-4 text-center" data-dom-id="tenant-switch-error">
            租户清单暂不可用
          </div>
        ) : (
          options.map((t) => {
            const isSelected = effectiveSlug === t.slug;
            const isCurrentRow = currentSlug === t.slug;
            return (
              <button
                key={t.slug}
                type="button"
                data-dom-id={`tenant-option-${t.slug}`}
                onClick={() => setSelected(t.slug)}
                className={`w-full flex items-center gap-2.5 p-2.5 rounded-lg border text-left transition-colors ${
                  isSelected ? "border-primary bg-primary-50" : "border-border hover:bg-muted"
                }`}
              >
                <div className="w-7 h-7 rounded-lg bg-primary-50 text-primary grid place-items-center text-xs font-extrabold">
                  {initials(t.name)}
                </div>
                <div className="min-w-0 flex-1">
                  <b className="text-xs block truncate">{t.name}</b>
                  <span className="text-[10px] text-muted-foreground block truncate">
                    {planLabel(t.plan)} · 生产环境
                  </span>
                </div>
                {isCurrentRow && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary text-primary-foreground">
                    当前
                  </span>
                )}
                {isSelected ? (
                  <Check className="w-4 h-4 text-primary" aria-hidden="true" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
                )}
              </button>
            );
          })
        )}
      </div>
    </Modal>
  );
}
