import { Check, ChevronDown, ChevronUp, Copy, DatabaseZap, Loader2, Play, ShieldCheck } from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { EdpApiError } from "@edp/api-sdk";
import { EmptyState, errorSpec, MonoId } from "@edp/shared";
import { TOOL_DEFS, type EvidenceHint } from "./api";
import { useTryToolQuery } from "./hooks";

/** 折叠阈值：JSON 行数超过即先收起（长内容折叠，展开按需）。 */
const COLLAPSE_LINES = 30;

/** 提取响应内 evidence_hint（B.8：对象级在顶层，列表级随 items 行携带）。 */
function extractHints(data: unknown): EvidenceHint[] {
  if (data == null || typeof data !== "object") return [];
  const obj = data as Record<string, unknown>;
  const hints: EvidenceHint[] = [];
  if (obj.evidence_hint && typeof obj.evidence_hint === "object") {
    hints.push(obj.evidence_hint as EvidenceHint);
  }
  if (Array.isArray(obj.items)) {
    for (const item of obj.items) {
      if (item != null && typeof item === "object") {
        const h = (item as Record<string, unknown>).evidence_hint;
        if (h && typeof h === "object") hints.push(h as EvidenceHint);
      }
    }
  }
  return hints;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label="复制响应 JSON"
      data-dom-id="tools-copy"
      onClick={async () => {
        try {
          await navigator.clipboard?.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          // 剪贴板不可用（非安全上下文）时静默忽略
        }
      }}
      className="h-7 px-2 border border-border rounded-md text-[10px] text-muted-foreground hover:bg-muted flex items-center gap-1"
    >
      {copied ? <Check className="w-3 h-3 text-state-success" aria-hidden="true" /> : <Copy className="w-3 h-3" aria-hidden="true" />}
      {copied ? "已复制" : "复制"}
    </button>
  );
}

/** 证据追溯行（证据页暂无 focus 定位参数，本轮仅展示 id 文本 + title 全量）。 */
function EvidenceRows({ hints }: { hints: EvidenceHint[] }) {
  if (hints.length === 0) return null;
  return (
    <div className="border-t border-border pt-3" data-dom-id="tools-evidence">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">证据追溯（evidence_hint）</div>
      <div className="flex flex-wrap gap-2">
        {hints.map((hint, i) => (
          <span
            key={`${hint.object_id}-${i}`}
            data-dom-id="tools-evidence-row"
            className="inline-flex items-center gap-1.5 bg-muted border border-border rounded-md px-2 py-1"
          >
            <ShieldCheck className="w-3.5 h-3.5 text-state-success shrink-0" aria-hidden="true" />
            <MonoId prefix="obj" id={hint.object_id.slice(-8)} full={hint.object_id} copyable={false} />
            {hint.event_id != null && (
              <MonoId prefix="evt" id={hint.event_id.slice(-8)} full={hint.event_id} copyable={false} />
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

function ErrorBox({ error }: { error: unknown }) {
  const apiErr = error instanceof EdpApiError ? error : null;
  const spec = errorSpec(apiErr?.code);
  return (
    <div
      role="alert"
      data-dom-id="tools-error"
      className="border border-state-error/40 bg-state-error-bg text-state-error rounded-lg px-3 py-2.5 text-xs"
    >
      <span className="font-medium">
        试查失败（HTTP {apiErr?.status ?? 0} · {apiErr?.code ?? "INTERNAL"}）
      </span>
      <span className="block mt-0.5">{spec.message}</span>
    </div>
  );
}

/**
 * 在线试查表单（EDP-503，13.7 表单/结果卡模式）：六接口下拉 → 按接口动态查询键
 * 输入（label/placeholder 逐字提示契约参数名）→ GET → 只读 JSON（pre mono + 复制 +
 * 长内容折叠）+ evidence_hint 证据行；404/403 等按 13.9.2 errorSpec 呈现。
 */
export function TryQueryForm() {
  const [toolValue, setToolValue] = useState(TOOL_DEFS[0].value);
  const def = TOOL_DEFS.find((t) => t.value === toolValue) ?? TOOL_DEFS[0];
  const [values, setValues] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(false);

  const tryQuery = useTryToolQuery();
  const data = tryQuery.data;
  const jsonText = useMemo(() => (data != null ? JSON.stringify(data, null, 2) : ""), [data]);
  const jsonLines = jsonText ? jsonText.split("\n").length : 0;
  const collapsible = jsonLines > COLLAPSE_LINES;
  const hints = data != null ? extractHints(data) : [];

  const missingRequired = def.fields.filter((f) => f.required && !values[f.key]?.trim());
  const submittable = missingRequired.length === 0 && !tryQuery.isPending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setExpanded(false);
    tryQuery.mutate({ def, values });
  };

  let result: ReactNode = null;
  if (tryQuery.isError) {
    result = <ErrorBox error={tryQuery.error} />;
  } else if (data != null) {
    result = (
      <div
        className="bg-muted border border-border rounded-lg p-3 space-y-3"
        data-dom-id="tools-result"
        aria-busy={tryQuery.isPending}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            响应 JSON（只读 · {jsonLines} 行）
          </span>
          <CopyButton text={jsonText} />
        </div>
        <pre
          data-dom-id="tools-result-json"
          className={`font-mono text-[11px] text-foreground whitespace-pre-wrap break-all overflow-auto ${
            collapsible && !expanded ? "max-h-64" : "max-h-[480px]"
          }`}
        >
          {jsonText}
        </pre>
        {collapsible && (
          <button
            type="button"
            data-dom-id="tools-collapse"
            onClick={() => setExpanded((v) => !v)}
            className="h-7 px-2 border border-border bg-card rounded-md text-[10px] text-muted-foreground hover:bg-muted flex items-center gap-1"
          >
            {expanded ? <ChevronUp className="w-3 h-3" aria-hidden="true" /> : <ChevronDown className="w-3 h-3" aria-hidden="true" />}
            {expanded ? "收起" : `展开全部 ${jsonLines} 行`}
          </button>
        )}
        <EvidenceRows hints={hints} />
      </div>
    );
  }

  return (
    <section className="bg-card border border-border rounded-xl p-4 space-y-4" data-dom-id="tools-form">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-end gap-3">
          <label className="flex flex-col gap-1 min-w-52">
            <span className="text-xs font-medium text-foreground">查询接口</span>
            <select
              data-dom-id="tools-interface"
              aria-label="查询接口"
              value={toolValue}
              onChange={(e) => {
                setToolValue(e.target.value);
                setValues({});
                tryQuery.reset();
                setExpanded(false);
              }}
              className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {TOOL_DEFS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label} · {t.description}
                </option>
              ))}
            </select>
          </label>
          {def.fields.map((field) => (
            <label key={field.key} className="flex flex-col gap-1 lg:w-64" data-dom-id={`tools-field-${field.key}`}>
              <span className="text-xs font-medium text-foreground">
                {field.label}
                {field.required ? <span className="text-state-error"> *</span> : <span className="text-muted-foreground">（可选）</span>}
              </span>
              <input
                type="text"
                aria-label={field.label}
                placeholder={field.placeholder}
                value={values[field.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring font-mono"
              />
            </label>
          ))}
          <button
            type="submit"
            disabled={!submittable}
            data-dom-id="tools-submit"
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none flex items-center gap-1.5"
          >
            {tryQuery.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            ) : (
              <Play className="w-4 h-4" aria-hidden="true" />
            )}
            执行试查
          </button>
        </div>
      </form>
      {result == null && !tryQuery.isPending && (
        <div data-dom-id="tools-idle">
          <EmptyState
            icon={<DatabaseZap className="w-7 h-7" />}
            title="选择接口开始试查"
            description="选择上方只读接口并填入查询参数，执行后在此查看 JSON 响应与证据追溯。"
          />
        </div>
      )}
      {result}
    </section>
  );
}
