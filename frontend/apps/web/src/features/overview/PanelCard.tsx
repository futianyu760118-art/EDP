import type { ReactNode } from "react";
import { Skeleton } from "antd";

/** 面板级降级容器：loading/error/empty/children 四态独立承接，单面板故障不影响整页。 */
export function PanelCard({ domId, title, loading, error, empty, action, children }: {
  domId: string;
  title: string;
  loading: boolean;
  error: unknown;
  empty?: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section data-dom-id={domId} className="bg-card border border-border rounded-xl p-5">
      <header className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {action}
      </header>
      {loading ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : error ? (
        <div className="text-xs text-muted-foreground py-6 text-center" data-dom-id={`${domId}-error`}>
          该面板暂不可用
        </div>
      ) : empty ? (
        <div className="text-xs text-muted-foreground py-6 text-center" data-dom-id={`${domId}-empty`}>
          暂无数据
        </div>
      ) : (
        children
      )}
    </section>
  );
}
