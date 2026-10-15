import { EdpApiError } from "@edp/api-sdk";
import { message } from "antd";
import { errorSpec } from "@edp/shared";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import { SYSTEM_TYPE_OPTIONS, type SystemAuthConfig } from "./api";
import { useCreateSystem } from "./hooks";

export interface CreateAdapterModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 新增适配器弹窗（视觉基线 `新增适配器 - 弹窗.html` / 13.7 #6 480 档 +
 * #15 折叠面板）：名称 / 系统类型 SOURCE·CONSUMER / Endpoint + 认证信息
 * 折叠面板（kind apikey·basic + secret_ref，默认收起）→ POST /systems →
 * 201 toast「适配器已注册」+ 清单刷新；同名 409 行内错误。
 *
 * V1.3 T50：SOURCE 增加接入方式（REST / DB 拉取）；DB 拉取提供 DSN +
 * 表配置 JSON（adapter_config = {dsn, tables[]}，提交时解析校验）。
 */
export function CreateAdapterModal({ open, onClose }: CreateAdapterModalProps) {
  const [name, setName] = useState("");
  const [type, setType] = useState("SOURCE");
  const [endpoint, setEndpoint] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [authKind, setAuthKind] = useState<"apikey" | "basic">("apikey");
  const [secretRef, setSecretRef] = useState("");
  const [channel, setChannel] = useState<"REST" | "DB_PULL">("REST");
  const [dsn, setDsn] = useState("");
  const [tablesJson, setTablesJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const createSystem = useCreateSystem();

  useEffect(() => {
    if (!open) return;
    setName("");
    setType("SOURCE");
    setEndpoint("");
    setAuthOpen(false);
    setAuthKind("apikey");
    setSecretRef("");
    setChannel("REST");
    setDsn("");
    setTablesJson("");
    setError(null);
  }, [open]);

  const handleSubmit = () => {
    if (!name.trim()) {
      setError("请输入适配器名称");
      return;
    }
    const authConfig: SystemAuthConfig | undefined = secretRef.trim()
      ? { kind: authKind, secret_ref: secretRef.trim() }
      : undefined;

    let adapterConfig: Record<string, unknown> | undefined;
    if (type === "SOURCE" && channel === "DB_PULL") {
      if (!dsn.trim()) {
        setError("请输入数据库连接串（DSN）");
        return;
      }
      let tables: unknown;
      try {
        tables = JSON.parse(tablesJson.trim() || "[]");
      } catch {
        setError("表配置不是合法 JSON");
        return;
      }
      if (!Array.isArray(tables) || tables.length === 0) {
        setError("表配置至少一条：[{table, increment_column?, owner_domain?, excluded_columns?}]");
        return;
      }
      adapterConfig = { dsn: dsn.trim(), tables };
    }

    setError(null);
    createSystem.mutate(
      {
        name: name.trim(),
        type,
        endpoint: endpoint.trim() ? endpoint.trim() : undefined,
        auth_config: authConfig,
        adapter_config: adapterConfig,
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

  return (
    <ModalForm
      open={open}
      title="新增适配器"
      icon={<Plus className="w-5 h-5" aria-hidden="true" />}
      width={480}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="保存"
      confirmLoading={createSystem.isPending}
    >
      <div className="space-y-4 pt-2" data-dom-id="adapter-create-form">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">适配器名称</div>
          <input
            type="text"
            data-dom-id="adapter-name"
            aria-label="适配器名称"
            placeholder="例如：ERP-S4-Production"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError(null);
            }}
            className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">系统类型</div>
            <select
              data-dom-id="adapter-type"
              aria-label="系统类型"
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
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
              data-dom-id="adapter-endpoint"
              aria-label="Endpoint"
              placeholder="https://api.example.com/v1"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </div>
        </div>

        {type === "SOURCE" && (
          <div className="space-y-3" data-dom-id="adapter-channel-panel">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">接入方式</div>
              <select
                data-dom-id="adapter-channel"
                aria-label="接入方式"
                value={channel}
                onChange={(e) => setChannel(e.target.value as "REST" | "DB_PULL")}
                className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
              >
                <option value="REST">REST · 接口拉取</option>
                <option value="DB_PULL">DB_PULL · 数据库直连拉取</option>
              </select>
            </div>
            {channel === "DB_PULL" && (
              <>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">DSN 连接串</div>
                  <input
                    type="text"
                    data-dom-id="adapter-dsn"
                    aria-label="DSN 连接串"
                    placeholder="postgresql://user:password@host:5432/db"
                    value={dsn}
                    onChange={(e) => {
                      setDsn(e.target.value);
                      setError(null);
                    }}
                    className="h-9 w-full px-3 text-xs font-mono bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                  />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">表配置（JSON）</div>
                  <textarea
                    data-dom-id="adapter-tables-json"
                    aria-label="表配置 JSON"
                    rows={5}
                    placeholder={'[{"table":"scm_material","increment_column":"update_time",\n  "owner_domain":"master","excluded_columns":["contact_phone"]}]'}
                    value={tablesJson}
                    onChange={(e) => {
                      setTablesJson(e.target.value);
                      setError(null);
                    }}
                    className="w-full px-3 py-2 text-xs font-mono bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent resize-y"
                  />
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    increment_column 缺省全量拉取；excluded_columns 为敏感列 SQL 级排除。
                  </p>
                </div>
              </>
            )}
          </div>
        )}

        <div className="border border-border rounded-lg overflow-hidden" data-dom-id="adapter-auth-panel">
          <button
            type="button"
            data-dom-id="adapter-auth-toggle"
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
            <div data-dom-id="adapter-auth-body" className="p-3 space-y-3 border-t border-border">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">认证方式</div>
                <select
                  data-dom-id="adapter-auth-kind"
                  aria-label="认证方式"
                  value={authKind}
                  onChange={(e) => setAuthKind(e.target.value as "apikey" | "basic")}
                  className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                >
                  <option value="apikey">apikey</option>
                  <option value="basic">basic</option>
                </select>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Secret Ref</div>
                <input
                  type="text"
                  data-dom-id="adapter-secret-ref"
                  aria-label="Secret Ref"
                  placeholder="ENV:ERP_API_KEY"
                  value={secretRef}
                  onChange={(e) => setSecretRef(e.target.value)}
                  className="h-9 w-full px-3 text-xs font-mono bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                />
                <p className="mt-1 text-[10px] text-muted-foreground">
                  凭证不落库，仅登记密钥引用（secret_ref）。
                </p>
              </div>
            </div>
          )}
        </div>

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="adapter-create-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
