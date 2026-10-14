import { FileCheck2, ShieldCheck } from "lucide-react";
import { MonoId, StatusPill } from "@edp/shared";
import type { EvidenceRecord } from "../../mocks/types";
import { evidenceKind, fmtTime, summarizeSnapshot, type VerifyState } from "./derive";

export interface EvidenceListProps {
  items: EvidenceRecord[];
  verifyState: Record<string, VerifyState>;
  selectedId: string | undefined;
  onSelect: (record: EvidenceRecord) => void;
  onVerify: (record: EvidenceRecord) => void;
}

function VerifyPill({ state, onClick }: { state: VerifyState; onClick: () => void }) {
  if (state === "pending") {
    return <StatusPill tone="info" label="校验中…" />;
  }
  if (state === "valid") {
    return <StatusPill tone="success" label="VALID" dot />;
  }
  if (state === "invalid") {
    return <StatusPill tone="error" label="INVALID" dot />;
  }
  return (
    <button
      type="button"
      data-dom-id="evidence-verify-btn"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted"
    >
      校验
    </button>
  );
}

/** 左栏证据列表（设计 13.6.2 证据卡：类型 pill + 标题 + 状态 + 短 ID/来源/业务键 + 摘要）。 */
export function EvidenceList({
  items,
  verifyState,
  selectedId,
  onSelect,
  onVerify,
}: EvidenceListProps) {
  return (
    <ul className="divide-y divide-border flex-1 min-h-0 overflow-auto" data-dom-id="evidence-list">
      {items.map((record) => {
        const kind = evidenceKind(record);
        const state = verifyState[record.evidence_id] ?? "unverified";
        const summary = summarizeSnapshot(record);
        const selected = record.evidence_id === selectedId;
        return (
          <li key={record.evidence_id}>
            <button
              type="button"
              data-dom-id={`evidence-card-${record.evidence_id}`}
              aria-pressed={selected}
              onClick={() => onSelect(record)}
              className={`w-full text-left px-4 py-3 transition-colors ${
                selected ? "bg-primary-50" : "hover:bg-muted"
              }`}
            >
              <div className="flex items-center gap-2">
                <StatusPill tone={kind === "Derived" ? "info" : "muted"} label={kind} />
                <span className="text-xs font-medium text-foreground truncate">
                  {record.source_record_id}
                </span>
                <span className="ml-auto shrink-0">
                  <VerifyPill state={state} onClick={() => onVerify(record)} />
                </span>
              </div>
              <div className="mt-1.5 text-[11px] text-muted-foreground flex items-center gap-1.5 flex-wrap">
                <MonoId prefix="ev" id={record.evidence_id} full={record.evidence_id} length={8} />
                <span>·</span>
                <span>{record.source_system}</span>
                <span>·</span>
                <span className="truncate">{record.source_record_id}</span>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground truncate">
                {summary ?? "—"}
              </p>
              <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>{fmtTime(record.captured_at)}</span>
                <span>·</span>
                <span className="font-mono" title={record.checksum}>
                  {record.checksum.replace(/^sha256:/, "").slice(0, 4)}…
                  {record.checksum.slice(-4)}
                </span>
                <span className="ml-auto inline-flex items-center gap-1">
                  {kind === "Primary" ? (
                    <FileCheck2 className="w-3 h-3" aria-hidden="true" />
                  ) : (
                    <ShieldCheck className="w-3 h-3" aria-hidden="true" />
                  )}
                  {record.source_system}
                </span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
