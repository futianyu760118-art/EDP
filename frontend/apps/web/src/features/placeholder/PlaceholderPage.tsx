import { ArrowLeft, Construction, RefreshCw, ServerCrash, ShieldX } from "lucide-react";
import { useNavigate } from "react-router-dom";

function BackToOverview({ domId }: { domId: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      data-dom-id={domId}
      onClick={() => navigate("/admin/overview")}
      className="h-9 px-4 mt-6 border border-border bg-card rounded-lg text-xs font-medium text-foreground hover:bg-muted flex items-center gap-1.5"
    >
      <ArrowLeft className="w-4 h-4" aria-hidden="true" />
      返回总览
    </button>
  );
}

/** W1 占位页：除登录/壳层外的全部路由统一挂载，后续周次逐页替换。 */
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div
      data-dom-id="page-placeholder"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <Construction className="w-10 h-10 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">{title}</h1>
      <p className="text-xs text-muted-foreground mt-2">该页面将在后续周次交付</p>
      <BackToOverview domId="placeholder-back" />
    </div>
  );
}

export function ForbiddenPage() {
  return (
    <div
      data-dom-id="page-403"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <ShieldX className="w-10 h-10 text-state-error" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">无权访问</h1>
      <p className="text-xs text-muted-foreground mt-2">您没有访问该页面的权限，请联系管理员</p>
      <BackToOverview domId="forbidden-back" />
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div
      data-dom-id="page-404"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <Construction className="w-10 h-10 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">页面不存在</h1>
      <p className="text-xs text-muted-foreground mt-2">您访问的页面不存在或已被移动</p>
      <BackToOverview domId="notfound-back" />
    </div>
  );
}

/** 500 错误页（EDP-601；无独立设计稿，沿 403/404 文案风格自拟）：重试 reload + 返回总览。 */
export function ServerErrorPage() {
  const navigate = useNavigate();
  return (
    <div
      data-dom-id="page-500"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <ServerCrash className="w-10 h-10 text-state-error" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">服务暂时不可用</h1>
      <p className="text-xs text-muted-foreground mt-2">服务出现异常，请稍后重试；若持续出现请联系管理员</p>
      <div className="flex items-center gap-3 mt-6">
        <button
          type="button"
          data-dom-id="server-error-retry"
          onClick={() => window.location.reload()}
          className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
        >
          <RefreshCw className="w-4 h-4" aria-hidden="true" />
          重试
        </button>
        <button
          type="button"
          data-dom-id="server-error-back"
          onClick={() => navigate("/admin/overview")}
          className="h-9 px-4 border border-border bg-card rounded-lg text-xs font-medium text-foreground hover:bg-muted flex items-center gap-1.5"
        >
          <ArrowLeft className="w-4 h-4" aria-hidden="true" />
          返回总览
        </button>
      </div>
    </div>
  );
}
