import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

let showBanner: () => void = () => {};

/** main.tsx 在 setTenantSuspendedNotifier 中调用（经 api-sdk 拦截器触发）。 */
export function notifyTenantSuspended(): void {
  showBanner();
}

/** TENANT_SUSPENDED 常驻横幅（13.8）：挂载于 AppLayout 顶栏下方，仅此一份实例接收桥接调用。 */
export function TenantSuspendedBanner() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    showBanner = () => setVisible(true);
    return () => {
      showBanner = () => {};
    };
  }, []);
  if (!visible) return null;
  return (
    <div
      data-dom-id="tenant-suspended-banner"
      className="fixed top-[66px] left-[250px] right-0 z-30 bg-state-warning-bg text-state-warning text-xs font-medium px-4 py-2 flex items-center gap-2 border-b border-border"
    >
      <TriangleAlert className="w-4 h-4" aria-hidden="true" />
      当前租户已暂停，请联系平台管理员
      <button type="button" className="ml-auto underline" onClick={() => setVisible(false)}>
        知道了
      </button>
    </div>
  );
}
