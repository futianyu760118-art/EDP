import { message, Skeleton } from "antd";
import { ArrowLeft, CircleHelp, GitBranch, ListOrdered, ShieldAlert, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useState } from "react";
import { MonoId, StatusPill } from "@edp/shared";
import { fmt } from "../../lib/labels";
import { RiskDrawer } from "../../shared/components/RiskDrawer";
import type { EvidenceChainItem } from "./api";
import { ActionCard } from "./ActionCard";
import { EvidenceChainGraph, type VerifyState } from "./EvidenceChainGraph";
import { useCaseDetail, useVerifyCaseEvidence } from "./hooks";
import { caseStatusOf, riskLabelOf } from "./labels";
import { StepsTimeline } from "./StepsTimeline";

/** context 影响说明 key-value 中文标签（B.5 context 常见键；未命中回退原键）。 */
const CONTEXT_LABELS: Record<string, string> = {
  order_amount: "订单金额",
  material_gap: "物料缺口",
  source_event_id: "源事件",
  expected_delay_days: "预计延误（天）",
};

function contextValue(value: unknown): string {
  if (typeof value === "number") return fmt(value);
  return String(value ?? "—");
}

function SectionCard({
  title,
  icon,
  anchor,
  extra,
  children,
}: {
  title: string;
  icon: ReactNode;
  anchor: string;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id={anchor}>
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        <span className="text-xs font-semibold text-foreground">{title}</span>
        {extra != null && <span className="ml-auto text-[10px] text-muted-foreground">{extra}</span>}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

/**
 * 案例详情页（EDP-403 M4 关键，设计 13.6.5：一屏闭环叙事四区）：
 * ① 问题卡（question + context 影响说明 key-value + 风险 pill + options radio 只读）
 * ② 证据链横向图（Result→Decision→Evidence→Source；EVIDENCE 节点 verify 联动）
 * ③ Steps 垂直时间线（Human-Only 人形图标）④ 关联行动卡（allowed_to 只读 chips）；
 * 顶部「关联风险」→ 泛化 RiskDrawer（detail.event.event_id；event 缺省禁用）。
 */
export function CaseDetailPage() {
  const { case_id: caseId } = useParams();
  const detailQuery = useCaseDetail(caseId);
  const [riskOpen, setRiskOpen] = useState(false);
  const [verifyState, setVerifyState] = useState<Record<string, VerifyState>>({});
  const verify = useVerifyCaseEvidence();

  const detail = detailQuery.data;
  const eventId = detail?.event?.event_id ?? null;

  const handleVerify = (item: EvidenceChainItem) => {
    const evidenceId = item.evidence_id;
    if (evidenceId == null) return;
    setVerifyState((state) => ({ ...state, [evidenceId]: "pending" }));
    verify.mutate(evidenceId, {
      onSuccess: (result) => {
        setVerifyState((state) => ({
          ...state,
          [evidenceId]: result.valid ? "valid" : "invalid",
        }));
        void message[result.valid ? "success" : "error"](
          result.valid ? "校验通过：快照与 checksum 一致" : "校验失败：快照可能被篡改",
        );
      },
      onError: () => {
        setVerifyState((state) => ({ ...state, [evidenceId]: "unverified" }));
        void message.error("校验请求失败，请稍后重试");
      },
    });
  };

  const chain = detail?.evidence_chain ?? [];
  const steps = detail?.steps ?? [];
  const actions = detail?.actions ?? [];
  const decidedOption = detail?.decisions?.[0]?.chosen_option;
  const risk = riskLabelOf(detail?.risk_level);
  const status = caseStatusOf(detail?.status ?? "");

  return (
    <div className="space-y-4" data-dom-id="case-detail-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            to="/cases"
            aria-label="返回案例列表"
            data-dom-id="case-detail-back"
            className="h-9 px-3 border border-border bg-card text-muted-foreground rounded-lg text-xs font-medium hover:bg-muted flex items-center gap-1.5 shrink-0"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            返回
          </Link>
          <h1 className="text-xl font-semibold text-foreground whitespace-nowrap">案例详情</h1>
          {caseId != null && <MonoId prefix="case" id={caseId} />}
        </div>
        <div className="flex items-center gap-2">
          {detail != null && (
            <>
              <StatusPill tone={risk.tone} label={risk.label} />
              <StatusPill tone={status.tone} label={status.label} />
            </>
          )}
          <button
            type="button"
            data-dom-id="case-detail-risk-btn"
            disabled={eventId == null}
            title={eventId == null ? "该案例无关联风险事件" : undefined}
            onClick={() => setRiskOpen(true)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none flex items-center gap-1.5"
          >
            <ShieldAlert className="w-4 h-4" aria-hidden="true" />
            关联风险
          </button>
        </div>
      </section>

      {detailQuery.isError && detail == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="case-detail-error"
        >
          案例详情暂不可用
        </div>
      ) : detail == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 10 }} />
        </div>
      ) : (
        <>
          {/* ① 问题卡 */}
          <SectionCard
            title="问题"
            icon={<CircleHelp className="w-4 h-4" aria-hidden="true" />}
            anchor="case-detail-question"
            extra={decidedOption != null ? "已有决策记录" : "待决策"}
          >
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium text-foreground">{detail.question}</p>
            </div>
            {Object.keys(detail.context).length > 0 && (
              <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2" data-dom-id="case-question-context">
                {Object.entries(detail.context).map(([key, value]) => (
                  <div key={key} className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-[10px] text-muted-foreground block">{CONTEXT_LABELS[key] ?? key}</span>
                    <span className="text-xs font-medium text-foreground break-all" title={contextValue(value)}>
                      {contextValue(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 space-y-2" data-dom-id="case-options">
              {detail.options.map((option) => {
                const key = typeof option.key === "string" ? option.key : String(option.key);
                const label = typeof option.label === "string" ? option.label : key;
                return (
                  <label
                    key={key}
                    className={`flex items-center gap-2.5 border rounded-lg px-3 py-2 ${
                      decidedOption === key ? "border-primary bg-primary-50" : "border-border"
                    }`}
                  >
                    <input
                      type="radio"
                      name="case-option"
                      data-dom-id={`case-option-${key}`}
                      aria-label={label}
                      checked={decidedOption === key}
                      disabled
                      className="accent-primary"
                    />
                    <span className="text-xs text-foreground">{label}</span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">{key}</span>
                  </label>
                );
              })}
            </div>
          </SectionCard>

          {/* ② 证据链横向图 */}
          <SectionCard
            title="证据链"
            icon={<GitBranch className="w-4 h-4" aria-hidden="true" />}
            anchor="case-chain"
            extra="Result → Decision → Evidence → Source"
          >
            <EvidenceChainGraph chain={chain} verifyState={verifyState} onVerify={handleVerify} />
          </SectionCard>

          {/* ③ Steps 时间线 */}
          <SectionCard
            title="闭环步骤"
            icon={<ListOrdered className="w-4 h-4" aria-hidden="true" />}
            anchor="case-steps"
            extra={`${steps.length} 个节点 · 时间升序`}
          >
            <StepsTimeline steps={steps} />
          </SectionCard>

          {/* ④ 关联行动卡 */}
          <SectionCard
            title="关联行动"
            icon={<Zap className="w-4 h-4" aria-hidden="true" />}
            anchor="case-actions"
            extra={`${actions.length} 项行动`}
          >
            {actions.length === 0 ? (
              <div className="text-xs text-muted-foreground py-6 text-center" data-dom-id="case-actions-empty">
                暂无关联行动
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {actions.map((action) => (
                  <ActionCard key={action.action_id} action={action} caseId={detail.case_id} />
                ))}
              </div>
            )}
          </SectionCard>
        </>
      )}

      <RiskDrawer eventId={eventId} open={riskOpen} onClose={() => setRiskOpen(false)} />
    </div>
  );
}
