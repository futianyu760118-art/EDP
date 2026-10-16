import { EdpApiError } from "@edp/api-sdk";
import { message, Skeleton } from "antd";
import { errorSpec } from "@edp/shared";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import { SYSTEM_TYPE_OPTIONS, type SystemAuthConfig } from "./api";
import { TableSpecEditor, type TableSpecRow } from "./TableSpecEditor";
import { useSystem, useUpdateSystem } from "./hooks";

export interface EditAdapterModalProps {
  open: boolean;
  systemId: string | null;
  onClose: () => void;
}

function toSpecRows(tables: unknown): TableSpecRow[] {
  if (!Array.isArray(tables)) return [];
  return tables.map((item) => {
    const t = item as Record<string, unknown>;
    return {
      table: String(t.table ?? ""),
      increment_column: t.increment_column ? String(t.increment_column) : "",
      owner_domain: t.owner_domain ? String(t.owner_domain) : "master",
      excluded_columns: Array.isArray(t.excluded_columns)
        ? t.excluded_columns.join(", ")
        : "",
    };
  });
}

function toTables(rows: TableSpecRow[]) {
  return rows
    .filter((r) => r.table.trim())
    .map((r) => ({
      table: r.table.trim(),
      ...(r.increment_column.trim()
        ? { increment_column: r.increment_column.trim() }
        : { increment_column: null }),
      owner_domain: r.owner_domain.trim() || "master",
      ...(r.excluded_columns.trim()
        ? {
            excluded_columns: r.excluded_columns
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean),
          }
        : { excluded_columns: [] }),
    }));
}

/**
 * 编辑适配器弹窗（V1.3 T50）：GET /systems/{id} 预填 → PUT 局部更新。
 * 名称（注册键）只读；接入方式 / DSN / 表配置（逐表结构化编辑）/
 * Endpoint / 认证引用可改。
 */
export function EditAdapterModal({ open, systemId, onClose }: EditAdapterModalProps) {
  const system = useSystem(open ? systemId ?? undefined : undefined);
  const updateSystem = useUpdateSystem(systemId ?? undefined);

  const [type, setType] = useState("SOURCE");
  const [endpoint, setEndpoint] = useState("");
  const [channel, setChannel] = useState<"REST" | "DB_PULL">("REST");
  const [dsn, setDsn] = useState("");
  const [tableSpecs, setTableSpecs] = useState<TableSpecRow[]>([]);
  const [secretRef, setSecretRef] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !system.data) return;
    const cfg = system.data.adapter_config as { dsn?: string; tables?: unknown } | null;
    const auth = system.data.auth_config as SystemAuthConfig | undefined;
    setType(system.data.type);
    setEndpoint(system.data.endpoint ?? "");
    setChannel(cfg?.dsn ? "DB_PULL" : "REST");
    setDsn(cfg?.dsn ?? "");
    setTableSpecs(toSpecRows(cfg?.tables));
    setSecretRef(auth?.secret_ref ?? "");
    setError(null);
  }, [open, system.data]);

  const handleSubmit = () => {
    let adapterConfig: Record<string, unknown> | null | undefined;
    if (type === "SOURCE" && channel === "DB_PULL") {
      if (!dsn.trim()) {
        setError("请输入数据库连接串（DSN）");
        return;
      }
      if (!tableSpecs.some((r) => r.table.trim())) {
        setError("请至少添加一张表配置");
        return;
      }
      adapterConfig = { dsn: dsn.trim(), tables: toTables(tableSpecs) };
    } else if (channel === "REST") {
      adapterConfig = null; // 显式清空驱动配置（回退未装配语义）
    }

    setError(null);
    updateSystem.mutate(
      {
        type,
        endpoint: endpoint.trim() ? endpoint.trim() : undefined,
        auth_config: secretRef.trim() ? { kind: "apikey", secret_ref: secretRef.trim() } : undefined,
        ...(adapterConfig !== undefined ? { adapter_config: adapterConfig } : {}),
      },
      {
        onSuccess: () => {
          void message.success("适配器已更新");
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
      title="编辑适配器"
      width={520}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="保存"
      confirmLoading={updateSystem.isPending}
    >
      {system.isPending ? (
        <div className="py-4" data-dom-id="adapter-edit-loading">
          <Skeleton active paragraph={{ rows: 3 }} />
        </div>
      ) : (
        <div className="space-y-4 pt-2" data-dom-id="adapter-edit-form">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">适配器名称（不可修改）</div>
            <input
              type="text"
              data-dom-id="adapter-edit-name"
              aria-label="适配器名称"
              disabled
              value={system.data?.name ?? ""}
              className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg opacity-60"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">系统类型</div>
              <select
                data-dom-id="adapter-edit-type"
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
                data-dom-id="adapter-edit-endpoint"
                aria-label="Endpoint"
                placeholder="https://api.example.com/v1"
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
              />
            </div>
          </div>

          {type === "SOURCE" && (
            <div className="space-y-3" data-dom-id="adapter-edit-channel-panel">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">接入方式</div>
                <select
                  data-dom-id="adapter-edit-channel"
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
                      data-dom-id="adapter-edit-dsn"
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
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">表配置</div>
                    <TableSpecEditor rows={tableSpecs} onChange={setTableSpecs} />
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      增量列留空 = 全量拉取；排除列为敏感列 SQL 级排除。
                    </p>
                  </div>
                </>
              )}
            </div>
          )}

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Secret Ref（凭证引用，不落明文）</div>
            <input
              type="text"
              data-dom-id="adapter-edit-secret-ref"
              aria-label="Secret Ref"
              placeholder="ENV:ERP_API_KEY"
              value={secretRef}
              onChange={(e) => setSecretRef(e.target.value)}
              className="h-9 w-full px-3 text-xs font-mono bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </div>

          {error != null && (
            <div className="text-[11px] text-state-error" data-dom-id="adapter-edit-error" role="alert">
              {error}
            </div>
          )}
        </div>
      )}
    </ModalForm>
  );
}
