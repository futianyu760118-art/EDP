import { message } from "antd";
import { ShieldPlus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import type { PolicyCreateRequest } from "./api";
import { useCreatePolicy } from "./hooks";

/** 常用资源类型候选（接口 fullname 口径）。 */
const RESOURCE_CANDIDATES = [
  "event.events",
  "evidence.records",
  "decision.records",
  "decision.cases",
  "action.actions",
  "master.business_objects",
] as const;

/** 常用动作候选（含 `PREFIX_*` 通配形态）。 */
const ACTION_CANDIDATES = [
  "EVIDENCE_*",
  "EVENT_*",
  "DECISION_*",
  "CASE_*",
  "ACTION_*",
  "GUARD_DENIED",
  "RATE_LIMITED",
] as const;

const ACTOR_OPTIONS: { value: "HUMAN" | "AI" | "SERVICE"; label: string }[] = [
  { value: "HUMAN", label: "人工（HUMAN）" },
  { value: "AI", label: "AI" },
  { value: "SERVICE", label: "服务（SERVICE）" },
];

/** 通知渠道（W4 终审 Minor：当前实现仅站内消息落地，email 预留——演示文案对齐真实现）。 */
const NOTIFY_CHANNELS = ["站内消息（email 预留）"] as const;

/** 多选 chip 组（输入添加 + 候选点选 + 已选移除）。 */
function MultiSelectChips({
  domId,
  placeholder,
  candidates,
  selected,
  onChange,
  transform,
}: {
  domId: string;
  placeholder: string;
  candidates: readonly string[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** 输入归一（如动作大写化）。 */
  transform?: (value: string) => string;
}) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const value = (transform?.(raw) ?? raw).trim();
    if (!value || selected.includes(value)) return;
    onChange([...selected, value]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          data-dom-id={domId}
          aria-label={placeholder}
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          className="h-9 flex-1 px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
        />
        <button
          type="button"
          data-dom-id={`${domId}-add`}
          onClick={() => add(draft)}
          className="h-9 px-3 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted"
        >
          添加
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {candidates.map((candidate) => {
          const active = selected.includes(candidate);
          return (
            <button
              key={candidate}
              type="button"
              data-dom-id={`${domId}-candidate-${candidate.replaceAll(".", "-").replaceAll("*", "any")}`}
              onClick={() =>
                active
                  ? onChange(selected.filter((v) => v !== candidate))
                  : onChange([...selected, candidate])
              }
              className={`h-7 px-2.5 rounded-full font-mono text-[11px] border transition-colors ${
                active
                  ? "bg-primary-50 text-primary border-primary/30"
                  : "bg-card text-muted-foreground border-border hover:bg-muted"
              }`}
            >
              {candidate}
            </button>
          );
        })}
      </div>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-dom-id={`${domId}-selected`}>
          {selected
            .filter((value) => !candidates.includes(value))
            .map((value) => (
              <span
                key={value}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-primary-50 text-primary font-mono"
              >
                {value}
                <button
                  type="button"
                  aria-label={`移除 ${value}`}
                  onClick={() => onChange(selected.filter((v) => v !== value))}
                  className="w-3.5 h-3.5 rounded grid place-items-center hover:bg-state-error-bg hover:text-state-error"
                >
                  <X className="w-2.5 h-2.5" aria-hidden="true" />
                </button>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

export interface PolicyCreateModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 新建审计策略弹窗（视觉基线 `原型设计/pages/新建审计策略 - 弹窗.html`，
 * 字段对齐 EDP-032 三维匹配契约）：策略名称 / 描述 / 资源类型多选（输入 +
 * 常用候选）/ 动作多选（支持 `PREFIX_*` 通配提示）/ 触发者多选
 * HUMAN·AI·SERVICE / 通知渠道 → POST → 201 → 列表刷新 + toast。
 */
export function PolicyCreateModal({ open, onClose }: PolicyCreateModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [resourceTypes, setResourceTypes] = useState<string[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [actorTypes, setActorTypes] = useState<("HUMAN" | "AI" | "SERVICE")[]>([]);
  const [notifyChannel, setNotifyChannel] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const createPolicy = useCreatePolicy();

  useEffect(() => {
    if (!open) return;
    setName("");
    setDescription("");
    setResourceTypes([]);
    setActions([]);
    setActorTypes([]);
    setNotifyChannel("");
    setError(null);
  }, [open]);

  const toggleActor = (value: "HUMAN" | "AI" | "SERVICE") => {
    setActorTypes((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  const handleSubmit = () => {
    if (!name.trim()) {
      setError("请输入策略名称");
      return;
    }
    if (actions.some((value) => value.includes(" "))) {
      setError("动作不支持空格，多个动作请分别添加");
      return;
    }
    setError(null);
    const body: PolicyCreateRequest = {
      name: name.trim(),
      description: description.trim() ? description.trim() : undefined,
      resource_types: resourceTypes,
      actions,
      actor_types: actorTypes,
      notify_channel: notifyChannel || undefined,
    };
    createPolicy.mutate(body, {
      onSuccess: () => {
        void message.success("策略已创建");
        onClose();
      },
      onError: () => {
        void message.error("策略创建失败，请稍后重试");
      },
    });
  };

  return (
    <ModalForm
      open={open}
      title="新建审计策略"
      icon={<ShieldPlus className="w-5 h-5" aria-hidden="true" />}
      width={520}
      onCancel={onClose}
      onSubmit={handleSubmit}
      submitText="确认创建"
      confirmLoading={createPolicy.isPending}
    >
      <div className="space-y-4 pt-2" data-dom-id="policy-create-form">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">策略名称</div>
          <input
            type="text"
            data-dom-id="policy-name"
            aria-label="策略名称"
            placeholder="请输入策略名称"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError(null);
            }}
            className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
          />
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">描述（可选）</div>
          <textarea
            data-dom-id="policy-description"
            aria-label="策略描述"
            rows={2}
            placeholder="策略用途、命中后处置方式…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full text-xs bg-muted border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            资源类型（留空 = 全部）
          </div>
          <MultiSelectChips
            domId="policy-resource-input"
            placeholder="输入资源全名（如 evidence.records）后回车"
            candidates={RESOURCE_CANDIDATES}
            selected={resourceTypes}
            onChange={setResourceTypes}
          />
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            动作（留空 = 全部）
          </div>
          <MultiSelectChips
            domId="policy-action-input"
            placeholder="输入动作（如 GUARD_DENIED）后回车"
            candidates={ACTION_CANDIDATES}
            selected={actions}
            onChange={setActions}
            transform={(value) => value.toUpperCase()}
          />
          <p className="mt-1 text-[10px] text-muted-foreground" data-dom-id="policy-action-hint">
            支持前缀通配，如 EVIDENCE_* 匹配全部证据动作
          </p>
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
            触发者（留空 = 全部）
          </div>
          <div className="flex items-center gap-4" data-dom-id="policy-actors">
            {ACTOR_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  data-dom-id={`policy-actor-${option.value}`}
                  checked={actorTypes.includes(option.value)}
                  onChange={() => toggleActor(option.value)}
                  className="w-3.5 h-3.5 rounded border-border accent-primary"
                />
                <span className="text-xs text-foreground">{option.label}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">通知渠道（可选）</div>
          <select
            data-dom-id="policy-notify-channel"
            aria-label="通知渠道"
            value={notifyChannel}
            onChange={(e) => setNotifyChannel(e.target.value)}
            className="h-9 w-full px-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
          >
            <option value="">不通知</option>
            {NOTIFY_CHANNELS.map((channel) => (
              <option key={channel} value={channel}>
                {channel}
              </option>
            ))}
          </select>
        </div>

        {error != null && (
          <div className="text-[11px] text-state-error" data-dom-id="policy-create-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </ModalForm>
  );
}
