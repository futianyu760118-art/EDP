import { EdpApiError } from "@edp/api-sdk";
import { Button, Modal, Steps, message } from "antd";
import { errorSpec } from "@edp/shared";
import { Cable, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { SYSTEM_TYPE_OPTIONS, type SystemAuthConfig } from "./api";
import { useCreateSystem } from "./hooks";

export interface ConnectWizardProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 数据源连接三步向导（视觉基线 `数据源连接 - 弹窗.html` / 13.7 #7 stepper
 * 可回退）：① 基本信息（名称/系统类型/Endpoint）→ ② 认证配置（折叠面板
 * 展开态：kind + secret_ref）→ ③ 确认摘要（只读回显卡）→ 提交
 * POST /systems + 成功关闭。
 */
export function ConnectWizard({ open, onClose }: ConnectWizardProps) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [type, setType] = useState("SOURCE");
  const [endpoint, setEndpoint] = useState("");
  const [authOpen, setAuthOpen] = useState(true);
  const [authKind, setAuthKind] = useState<"apikey" | "basic">("apikey");
  const [secretRef, setSecretRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const createSystem = useCreateSystem();

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setName("");
    setType("SOURCE");
    setEndpoint("");
    setAuthOpen(true);
    setAuthKind("apikey");
    setSecretRef("");
    setError(null);
  }, [open]);

  const canNext = step === 0 ? name.trim().length > 0 && endpoint.trim().length > 0 : true;

  const submit = () => {
    setError(null);
    const authConfig: SystemAuthConfig | undefined = secretRef.trim()
      ? { kind: authKind, secret_ref: secretRef.trim() }
      : undefined;
    createSystem.mutate(
      {
        name: name.trim(),
        type,
        endpoint: endpoint.trim(),
        auth_config: authConfig,
      },
      {
        onSuccess: () => {
          void message.success("适配器已注册");
          onClose();
        },
        onError: (err) => {
          setError(
            err instanceof EdpApiError ? err.message : errorSpec("INTERNAL").message,
          );
        },
      },
    );
  };

  const handleNext = () => {
    if (step < 2) {
      setError(null);
      setStep((s) => s + 1);
    } else {
      submit();
    }
  };

  const header = (
    <div className="flex items-center gap-2.5">
      <div
        className="w-10 h-10 rounded-lg bg-primary-50 text-primary grid place-items-center"
        aria-hidden="true"
      >
        <Cable className="w-5 h-5" />
      </div>
      <span className="text-base font-semibold text-foreground">数据源连接</span>
    </div>
  );

  const footer = (
    <div className="w-full border-t border-border pt-4 flex items-center justify-end gap-2">
      <Button data-dom-id="wizard-cancel" autoInsertSpace={false} onClick={onClose}>
        取消
      </Button>
      <Button
        data-dom-id="wizard-prev"
        autoInsertSpace={false}
        disabled={step === 0}
        onClick={() => {
          setError(null);
          setStep((s) => s - 1);
        }}
      >
        上一步
      </Button>
      <Button
        type="primary"
        data-dom-id="wizard-next"
        autoInsertSpace={false}
        disabled={step === 0 && !canNext}
        loading={createSystem.isPending}
        icon={<ChevronRight className="w-4 h-4" aria-hidden="true" />}
        iconPosition="end"
        onClick={handleNext}
      >
        {step === 2 ? "完成" : "下一步"}
      </Button>
    </div>
  );

  const inputCls =
    "h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={720}
      title={header}
      footer={footer}
      getContainer={false}
      destroyOnClose
    >
      <div data-dom-id="connect-wizard" className="flex flex-col gap-4 pt-1">
        <Steps
          size="small"
          current={step}
          items={[{ title: "基本信息" }, { title: "认证配置" }, { title: "确认摘要" }]}
        />

        {step === 0 && (
          <div data-dom-id="wizard-step-1" className="space-y-4">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">适配器名称</div>
              <input
                type="text"
                data-dom-id="wizard-name"
                aria-label="适配器名称"
                placeholder="例如：ERP-S4-Production"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">系统类型</div>
                <select
                  data-dom-id="wizard-type"
                  aria-label="系统类型"
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                  className={inputCls}
                >
                  {SYSTEM_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Endpoint</div>
                <input
                  type="text"
                  data-dom-id="wizard-endpoint"
                  aria-label="Endpoint"
                  placeholder="https://api.example.com/v1"
                  value={endpoint}
                  onChange={(e) => setEndpoint(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div data-dom-id="wizard-step-2" className="space-y-4">
            <div className="border border-border rounded-lg overflow-hidden" data-dom-id="wizard-auth-panel">
              <button
                type="button"
                data-dom-id="wizard-auth-toggle"
                aria-expanded={authOpen}
                onClick={() => setAuthOpen((v) => !v)}
                className="w-full px-3 py-2.5 flex items-center justify-between bg-muted/40 hover:bg-muted transition-colors text-left"
              >
                <span className="text-xs font-medium text-foreground">认证信息</span>
                <svg
                  className={`w-4 h-4 text-muted-foreground transition-transform ${authOpen ? "rotate-180" : ""}`}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </button>
              {authOpen && (
                <div data-dom-id="wizard-auth-body" className="p-3 space-y-3 border-t border-border">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">认证方式</div>
                    <select
                      data-dom-id="wizard-auth-kind"
                      aria-label="认证方式"
                      value={authKind}
                      onChange={(e) => setAuthKind(e.target.value as "apikey" | "basic")}
                      className={inputCls}
                    >
                      <option value="apikey">apikey</option>
                      <option value="basic">basic</option>
                    </select>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Secret Ref</div>
                    <input
                      type="text"
                      data-dom-id="wizard-secret-ref"
                      aria-label="Secret Ref"
                      placeholder="ENV:ERP_API_KEY"
                      value={secretRef}
                      onChange={(e) => setSecretRef(e.target.value)}
                      className={`${inputCls} font-mono`}
                    />
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      凭证不落库，仅登记密钥引用（secret_ref）；留空则跳过认证配置。
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {step === 2 && (
          <div data-dom-id="wizard-step-3" className="space-y-4">
            <div className="border border-border rounded-xl overflow-hidden" data-dom-id="wizard-summary">
              <div className="px-4 py-2.5 bg-muted border-b border-border text-xs font-medium text-foreground">
                连接信息确认
              </div>
              <dl className="text-xs">
                {(
                  [
                    ["适配器名称", name.trim()],
                    ["系统类型", SYSTEM_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type],
                    ["Endpoint", endpoint.trim()],
                    ["认证方式", secretRef.trim() ? authKind : "未配置"],
                    ["Secret Ref", secretRef.trim() || "—"],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label} className="flex items-start border-b border-border last:border-b-0">
                    <dt className="w-[120px] shrink-0 px-4 py-2.5 text-muted-foreground">{label}</dt>
                    <dd className="px-4 py-2.5 text-foreground font-mono break-all">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <p className="text-[11px] text-muted-foreground">
              提交后将注册为接入系统（POST /systems），可在清单中查看运行状态。
            </p>
          </div>
        )}

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="wizard-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
