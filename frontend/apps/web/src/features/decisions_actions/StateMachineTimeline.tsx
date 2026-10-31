/**
 * 9 态状态轴（设计 13.6.5 行动页 / B.5 状态机）：
 * 主线 PROPOSED→ASSIGNED→ACCEPTED→APPROVED→EXECUTING→COMPLETED→VERIFIED 横向节点流，
 * REJECTED/CANCELLED 作为分支弱化线；已走路径 primary 高亮连线、当前节点实心强调、
 * 未达 muted、终态灰；节点下小字状态名。
 * 类名锚点（测试/E2E）：state-node-{STATUS} + state-current/state-walked/state-pending/
 * state-terminal/state-branch；连线 state-line-walked/state-line-pending。
 */

export const MAIN_LINE_STATES = [
  "PROPOSED",
  "ASSIGNED",
  "ACCEPTED",
  "APPROVED",
  "EXECUTING",
  "COMPLETED",
  "VERIFIED",
] as const;

export const BRANCH_STATES = ["REJECTED", "CANCELLED"] as const;

type MainState = (typeof MAIN_LINE_STATES)[number];

type NodeKind = "current" | "walked" | "pending" | "terminal" | "branch";

const NODE_CLASS: Record<NodeKind, string> = {
  current: "state-current bg-primary border-primary text-primary-foreground",
  walked: "state-walked bg-primary-50 border-primary/50 text-primary",
  pending: "state-pending bg-muted border-border text-muted-foreground",
  terminal: "state-terminal bg-muted/60 border-border text-muted-foreground/60",
  branch: "state-branch bg-muted border-border/70 text-muted-foreground/70 border-dashed",
};

/** 外层锚点类名（测试/E2E 断言 state-node-{STATUS} 携带的语义类）。 */
const KIND_STATE_CLASS: Record<NodeKind, string> = {
  current: "state-current",
  walked: "state-walked",
  pending: "state-pending",
  terminal: "state-terminal",
  branch: "state-branch",
};

const LINE_WALKED = "state-line-walked bg-primary/60";
const LINE_PENDING = "state-line-pending bg-border";

function mainNodeKind(state: MainState, current: string): NodeKind {
  const idx = MAIN_LINE_STATES.indexOf(state);
  const currentIdx = MAIN_LINE_STATES.indexOf(current as MainState);
  if (currentIdx >= 0) {
    if (idx < currentIdx) return "walked";
    if (idx === currentIdx) return "current";
    return "pending";
  }
  // 分支终态（REJECTED/CANCELLED）为当前：主线视为已终结（灰），分支节点实心强调
  return "terminal";
}

function Node({ name, kind }: { name: string; kind: NodeKind }) {
  const isCurrent = kind === "current";
  return (
    <div
      className={`flex flex-col items-center gap-1 shrink-0 ${KIND_STATE_CLASS[kind]}`}
      data-dom-id={`state-node-${name}`}
    >
      <span
        aria-hidden="true"
        className={`w-5 h-5 rounded-full border-2 grid place-items-center ${NODE_CLASS[kind]} ${
          isCurrent ? "ring-2 ring-primary/30 ring-offset-2 ring-offset-card" : ""
        }`}
      >
        {isCurrent && <span className="w-1.5 h-1.5 rounded-full bg-primary-foreground" />}
      </span>
      <span
        className={`text-[10px] font-mono whitespace-nowrap ${
          isCurrent ? "text-primary font-semibold" : "text-muted-foreground"
        }`}
      >
        {name}
      </span>
    </div>
  );
}

function Connector({ walked }: { walked: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex-1 min-w-3 h-0.5 rounded ${walked ? LINE_WALKED : LINE_PENDING}`}
    />
  );
}

export interface StateMachineTimelineProps {
  /** 当前状态（9 态之一；未知名按 pending 处理主线）。 */
  status: string;
}

export function StateMachineTimeline({ status }: StateMachineTimelineProps) {
  const currentIdx = MAIN_LINE_STATES.indexOf(status as MainState);
  return (
    <div data-dom-id="state-machine" className="overflow-x-auto pb-1">
      <div className="flex items-start min-w-[520px]">
        {MAIN_LINE_STATES.map((state, i) => (
          <div key={state} className="contents">
            {i > 0 && <Connector walked={currentIdx >= 0 && i <= currentIdx} />}
            <Node name={state} kind={mainNodeKind(state, status)} />
          </div>
        ))}
      </div>
      {/* 分支弱化线：REJECTED / CANCELLED（虚线连出，非当前时弱化） */}
      <div className="flex items-start gap-6 mt-2 pl-10 min-w-[520px]" data-dom-id="state-machine-branches">
        {BRANCH_STATES.map((state) => (
          <div key={state} className="flex items-center gap-1.5">
            <span aria-hidden="true" className="w-3 h-0.5 border-t border-dashed border-border" />
            <Node name={state} kind={status === state ? "current" : "branch"} />
          </div>
        ))}
      </div>
    </div>
  );
}
