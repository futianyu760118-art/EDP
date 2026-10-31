import { ChevronRight, GitBranch } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { EmptyState, StatusPill, type StatusPillTone } from "@edp/shared";
import type { EvidenceChainItem } from "./api";

/** verify 结果（本会话状态；同证据库页 derive.VerifyState 语义）。 */
export type VerifyState = "unverified" | "pending" | "valid" | "invalid";

/** 四层横向链（设计 7.6 逆向追溯 / 13.6.5 ②）：Result→Decision→Evidence→Source。 */
const LAYERS = ["RESULT", "DECISION", "EVIDENCE", "SOURCE"] as const;

const LAYER_LABELS: Record<(typeof LAYERS)[number], { label: string; tone: StatusPillTone }> = {
  RESULT: { label: "RESULT · 回流结果", tone: "info" },
  DECISION: { label: "DECISION · 决策记录", tone: "warning" },
  EVIDENCE: { label: "EVIDENCE · 案例证据", tone: "success" },
  SOURCE: { label: "SOURCE · 源记录", tone: "muted" },
};

/** checksum 缩写（a4c1…9f3d 样式，13.7 #13）；剥 sha256: 前缀。 */
function checksumAbbr(cs: string): string {
  const raw = cs.replace(/^sha256:/, "");
  return `${raw.slice(0, 4)}…${raw.slice(-4)}`;
}

function VerifyPill({ state, onClick }: { state: VerifyState; onClick: () => void }) {
  let pill: React.ReactNode;
  if (state === "pending") {
    pill = <StatusPill tone="info" label="校验中…" size="sm" />;
  } else if (state === "valid") {
    pill = <StatusPill tone="success" label="VALID" size="sm" dot />;
  } else if (state === "invalid") {
    pill = <StatusPill tone="error" label="INVALID" size="sm" dot />;
  } else {
    pill = (
      <button
        type="button"
        data-dom-id="case-chain-verify-btn"
        onClick={onClick}
        className="text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted"
      >
        校验
      </button>
    );
  }
  return (
    <span data-dom-id="case-chain-verify-state" className="inline-flex">
      {pill}
    </span>
  );
}

export interface EvidenceChainGraphProps {
  chain: EvidenceChainItem[];
  verifyState: Record<string, VerifyState>;
  onVerify: (item: EvidenceChainItem) => void;
}

/**
 * 证据链横向图（设计 13.6.5 ② / 13.7 模式）：四层标签 pill + 节点卡横向滚动流
 * （title / checksum 缩写 / source_system / source_record_id）；EVIDENCE 层节点带
 * 「校验」按钮 → GET /evidence/{id}/verify 即时 VALID/INVALID pill 切换 + toast。
 */
export function EvidenceChainGraph({ chain, verifyState, onVerify }: EvidenceChainGraphProps) {
  const navigate = useNavigate();
  if (chain.length === 0) {
    return (
      <div data-dom-id="case-chain-empty">
        <EmptyState
          icon={<GitBranch className="w-7 h-7" />}
          title="暂无证据链节点"
          description="案例尚无关联证据；可在证据库检索源记录并关联。"
          primaryAction={{ label: "查看证据库", onClick: () => navigate("/admin/evidence") }}
        />
      </div>
    );
  }
  return (
    <div className="flex items-stretch gap-1 overflow-x-auto pb-2" data-dom-id="case-chain-flow">
      {LAYERS.map((layer, index) => {
        const nodes = chain.filter((item) => item.layer === layer);
        return (
          <div key={layer} className="flex items-stretch">
            {index > 0 && (
              <div className="self-center px-1 text-muted-foreground shrink-0" aria-hidden="true">
                <ChevronRight className="w-4 h-4" />
              </div>
            )}
            <div
              className="min-w-[220px] max-w-[260px] shrink-0 space-y-2"
              data-dom-id={`case-chain-layer-${layer}`}
            >
              <div className="flex items-center gap-2">
                <StatusPill tone={LAYER_LABELS[layer].tone} label={LAYER_LABELS[layer].label} size="sm" />
                <span className="text-[10px] text-muted-foreground">{nodes.length} 节点</span>
              </div>
              {nodes.length === 0 && (
                <div className="text-[10px] text-muted-foreground border border-dashed border-border rounded-lg p-3 text-center">
                  暂无节点
                </div>
              )}
              {nodes.map((node) => {
                const key = node.evidence_id ?? node.source_record_id ?? node.title;
                const state = node.evidence_id != null ? (verifyState[node.evidence_id] ?? "unverified") : "unverified";
                return (
                  <div
                    key={key}
                    data-dom-id={`case-chain-node-${node.evidence_id ?? key}`}
                    className="border border-border rounded-lg p-3 bg-card"
                  >
                    <div className="text-xs font-medium text-foreground truncate" title={node.title}>
                      {node.title}
                    </div>
                    <div className="mt-1 text-[10px] text-muted-foreground truncate">
                      {node.source_system ?? "—"} · {node.source_record_id ?? "—"}
                    </div>
                    <div className="mt-1.5 flex items-center justify-between gap-2">
                      {node.checksum != null ? (
                        <span className="font-mono text-[10px] text-muted-foreground" title={node.checksum}>
                          {checksumAbbr(node.checksum)}
                        </span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground">无 checksum</span>
                      )}
                      {layer === "EVIDENCE" && node.evidence_id != null && (
                        <VerifyPill state={state} onClick={() => onVerify(node)} />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
