import { Boxes, CircleCheck, CircleX, GitBranch } from "lucide-react";
import { MonoId, StatusPill } from "@edp/shared";
import type { EvidenceRecord } from "../../mocks/types";
import { evidenceKind, fmtTime, type VerifyState } from "./derive";

export interface ChainPanelProps {
  selected: EvidenceRecord | undefined;
  objectEvidence: EvidenceRecord[] | undefined;
  verifyState: Record<string, VerifyState>;
  onSelect: (record: EvidenceRecord) => void;
}

/**
 * 右栏证据链图（设计 13.6.2）：对象节点 → 同对象证据节点（垂直链）+
 * 底部「链上校验」区（按本会话 verify 结果计数）。
 */
export function ChainPanel({
  selected,
  objectEvidence,
  verifyState,
  onSelect,
}: ChainPanelProps) {
  if (selected == null) {
    return (
      <div
        className="bg-card border border-border rounded-xl p-8 text-center text-xs text-muted-foreground min-h-0 overflow-auto"
        data-dom-id="evidence-chain-empty"
      >
        从左侧选择一份证据查看证据链
      </div>
    );
  }

  const nodes = (objectEvidence ?? [selected]).slice().sort((a, b) =>
    a.captured_at.localeCompare(b.captured_at),
  );
  const verified = nodes.filter((node) => verifyState[node.evidence_id] === "valid").length;
  const failed = nodes.filter((node) => verifyState[node.evidence_id] === "invalid").length;
  const allVerified = failed === 0 && verified === nodes.length && nodes.length > 0;

  return (
    <aside
      className="bg-card border border-border rounded-xl overflow-auto min-h-0"
      data-dom-id="evidence-chain"
    >
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <GitBranch className="w-4 h-4 text-primary" aria-hidden="true" />
        <span className="text-xs font-semibold text-foreground">证据链</span>
        <span className="text-[10px] text-muted-foreground ml-auto">
          {nodes.length} 个节点
        </span>
      </header>

      <div className="p-4 space-y-0">
        <div className="flex items-start gap-3 pb-3 border-b border-border">
          <span className="w-7 h-7 rounded-full bg-primary-50 text-primary grid place-items-center shrink-0">
            <Boxes className="w-3.5 h-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="text-xs font-medium text-foreground">业务对象</div>
            <div className="mt-0.5">
              <MonoId
                id={selected.object_id}
                full={selected.object_id}
                length={8}
                prefix="obj"
              />
            </div>
          </div>
        </div>

        {nodes.map((node, index) => {
          const kind = evidenceKind(node);
          const state = verifyState[node.evidence_id] ?? "unverified";
          const isSelected = node.evidence_id === selected.evidence_id;
          return (
            <button
              key={node.evidence_id}
              type="button"
              data-dom-id={`chain-node-${index}`}
              onClick={() => onSelect(node)}
              className={`w-full text-left flex items-start gap-3 pt-3 ${
                index < nodes.length - 1 ? "pb-3 border-b border-border" : ""
              } ${isSelected ? "" : "opacity-80 hover:opacity-100"}`}
            >
              <span
                className={`w-7 h-7 rounded-full grid place-items-center shrink-0 ${
                  kind === "Derived"
                    ? "bg-state-info-bg text-state-info"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                <span className="w-2 h-2 rounded-full bg-current" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-xs font-medium text-foreground truncate">
                    {node.source_record_id}
                  </span>
                  {state === "valid" && (
                    <CircleCheck className="w-3.5 h-3.5 text-state-success shrink-0" aria-hidden="true" />
                  )}
                  {state === "invalid" && (
                    <CircleX className="w-3.5 h-3.5 text-state-error shrink-0" aria-hidden="true" />
                  )}
                </span>
                <span className="block mt-0.5 text-[10px] text-muted-foreground">
                  {kind} · {node.source_system} · {fmtTime(node.captured_at)}
                </span>
              </span>
              {isSelected && <StatusPill tone="info" label="当前" size="sm" />}
            </button>
          );
        })}
      </div>

      <footer
        className="px-4 py-3 border-t border-border text-[11px] text-muted-foreground"
        data-dom-id="chain-verify-summary"
      >
        {failed > 0 ? (
          <span className="text-state-error">
            {nodes.length} 份证据中 {failed} 份校验失败
          </span>
        ) : allVerified ? (
          <span className="text-state-success">
            {nodes.length} 份证据校验和均有效，依赖关系完整
          </span>
        ) : (
          <span>
            已校验 {verified}/{nodes.length} 份——点击列表「校验」后更新
          </span>
        )}
      </footer>
    </aside>
  );
}
