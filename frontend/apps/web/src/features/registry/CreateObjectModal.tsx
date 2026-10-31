import { message } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { EdpApiError } from "@edp/api-sdk";
import { AlertCircle, ChevronDown, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import { objectsApi, type ObjectCreateBody } from "./api";

/**
 * 注册业务对象弹窗（T8，视觉基线：`原型设计/pages/新建业务对象 - 弹窗.html` 行 577~658）。
 * 弹窗语义为登记主数据对象：object_type 固定 MASTER（B.2 契约必填）。
 * 所属域选项为原型 select 实际文案（订单/客户/供应商/物料），按域归属映射
 * owner_domain 实际值（订单=sales、客户/物料=master、供应商=procurement，
 * 与列表页域筛选值对齐）。
 */
const DOMAIN_OPTIONS = [
  { label: "订单", value: "sales" },
  { label: "客户", value: "master" },
  { label: "供应商", value: "procurement" },
  { label: "物料", value: "master" },
];

/** 数据来源多选 chip（原型行 624~635 逐字：ERP-S4/MDM/CRM）。 */
const SOURCE_OPTIONS = ["ERP-S4", "MDM", "CRM"];

interface FormState {
  name: string;
  code: string;
  domain: string;
  sources: string[];
  owner: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  code: "",
  domain: "",
  sources: [],
  owner: "",
  description: "",
};

interface FormErrors {
  name?: string;
  code?: string;
  domain?: string;
  sources?: string;
  /** 服务端 VALIDATION_ERROR 等通用行内错误（表单底部展示后端 message）。 */
  form?: string;
}

type CreateResult = { ok: true } | { ok: false; error: unknown };

const inputClass =
  "h-9 w-full px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

function FieldError({ msg }: { msg?: string }) {
  if (msg == null) return null;
  return (
    <p className="mt-1.5 text-[11px] text-state-error flex items-center gap-1">
      <AlertCircle className="w-3 h-3" aria-hidden="true" />
      {msg}
    </p>
  );
}

export function CreateObjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});

  // 每次打开重置表单与错误（ModalForm destroyOnClose 只卸载 children，状态在本组件）
  useEffect(() => {
    if (open) {
      setForm(EMPTY_FORM);
      setErrors({});
    }
  }, [open]);

  const mutation = useMutation({
    // 409/422 属可预期分支：吞掉异常走行内展示，避免触发 main.tsx 全局兜底 toast
    mutationFn: async (body: ObjectCreateBody): Promise<CreateResult> => {
      try {
        await objectsApi.create(body);
        return { ok: true };
      } catch (error) {
        return { ok: false, error };
      }
    },
  });

  const handleSubmit = () => {
    const next: FormErrors = {};
    if (!form.name.trim()) next.name = "对象名称不能为空，且不能与已有对象重复";
    if (!form.code.trim()) next.code = "对象编码不能为空";
    if (!form.domain) next.domain = "请选择所属域";
    if (form.sources.length === 0) next.sources = "请至少选择一个数据来源";
    setErrors(next);
    if (next.name != null || next.code != null || next.domain != null || next.sources != null) {
      return;
    }
    mutation.mutate(
      {
        object_type: "MASTER",
        owner_domain: form.domain,
        source_system: form.sources.join(","),
        source_id: form.code.trim(),
        attributes: {
          name: form.name.trim(),
          owner: form.owner.trim(),
          description: form.description.trim(),
          sources: form.sources,
        },
      },
      {
        onSuccess: (result) => {
          if (result.ok) {
            void queryClient.invalidateQueries({ queryKey: ["registry", "objects"] });
            void message.success("对象已创建");
            onClose();
            return;
          }
          const err = result.error;
          if (err instanceof EdpApiError && err.code === "CONFLICT") {
            setErrors({ code: "对象编码已存在，请更换" });
          } else if (err instanceof EdpApiError) {
            // VALIDATION_ERROR 等服务端校验失败：后端 message 行内展示
            setErrors({ form: err.message });
          } else {
            setErrors({ form: "创建失败，请稍后重试" });
          }
        },
      },
    );
  };

  return (
    <ModalForm
      open={open}
      title="注册业务对象"
      icon={<Plus className="w-5 h-5" aria-hidden="true" />}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="创建对象"
      confirmLoading={mutation.isPending}
    >
      <div className="flex flex-col gap-4 pt-2">
        <div>
          <label htmlFor="create-object-name" className="block text-xs font-medium text-foreground mb-1.5">
            对象名称 <span className="text-state-error">*</span>
          </label>
          <input
            id="create-object-name"
            type="text"
            data-dom-id="create-object-name"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="例如：客户主数据"
            className={inputClass}
          />
          <FieldError msg={errors.name} />
        </div>

        <div>
          <label htmlFor="create-object-code" className="block text-xs font-medium text-foreground mb-1.5">
            对象编码 <span className="text-state-error">*</span>
          </label>
          <input
            id="create-object-code"
            type="text"
            data-dom-id="create-object-code"
            value={form.code}
            onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
            placeholder="例如：CUST-MASTER-001"
            className={inputClass}
          />
          <FieldError msg={errors.code} />
        </div>

        <div>
          <label htmlFor="create-object-domain" className="block text-xs font-medium text-foreground mb-1.5">
            所属域 <span className="text-state-error">*</span>
          </label>
          <div className="relative">
            <select
              id="create-object-domain"
              data-dom-id="create-object-domain"
              value={form.domain}
              onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value }))}
              className={`${inputClass} pr-8 appearance-none`}
            >
              <option value="">请选择所属域</option>
              {DOMAIN_OPTIONS.map((d) => (
                <option key={d.label} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
            <ChevronDown
              className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none"
              aria-hidden="true"
            />
          </div>
          <FieldError msg={errors.domain} />
        </div>

        <div>
          <span className="block text-xs font-medium text-foreground mb-1.5">
            数据来源 <span className="text-state-error">*</span>
          </span>
          <div className="flex flex-wrap gap-2">
            {SOURCE_OPTIONS.map((s) => {
              const checked = form.sources.includes(s);
              return (
                <label
                  key={s}
                  htmlFor={`create-object-source-${s}`}
                  data-dom-id="create-object-source"
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 border rounded-lg cursor-pointer select-none ${
                    checked
                      ? "border-primary bg-primary-50 text-primary"
                      : "border-border bg-card text-foreground hover:bg-muted"
                  }`}
                >
                  <input
                    id={`create-object-source-${s}`}
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      setForm((f) => ({
                        ...f,
                        sources: f.sources.includes(s)
                          ? f.sources.filter((x) => x !== s)
                          : [...f.sources, s],
                      }))
                    }
                    className="w-3.5 h-3.5 rounded border-border text-primary focus:ring-ring"
                  />
                  <span className="text-xs">{s}</span>
                </label>
              );
            })}
          </div>
          <FieldError msg={errors.sources} />
        </div>

        <div>
          <label htmlFor="create-object-owner" className="block text-xs font-medium text-foreground mb-1.5">
            责任人
          </label>
          <input
            id="create-object-owner"
            type="text"
            data-dom-id="create-object-owner"
            value={form.owner}
            onChange={(e) => setForm((f) => ({ ...f, owner: e.target.value }))}
            placeholder="例如：张三"
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor="create-object-description" className="block text-xs font-medium text-foreground mb-1.5">
            描述
          </label>
          <textarea
            id="create-object-description"
            data-dom-id="create-object-description"
            rows={3}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            placeholder="补充对象的业务说明、使用场景或关联规则…"
            className="w-full px-3 py-2.5 text-xs bg-card border border-border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
          />
        </div>

        <FieldError msg={errors.form} />
      </div>
    </ModalForm>
  );
}
