import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TenantSuspendedBanner } from "./TenantSuspendedBanner";
import { Topbar } from "./Topbar";

/** 壳层布局：page-shell = 固定侧边栏 + 固定顶栏 + main-stage（避让 left 250px / padding-top 66px）。 */
export function AppLayout() {
  return (
    <div className="page-shell">
      <Sidebar />
      <Topbar />
      <TenantSuspendedBanner />
      <main className="main-stage bg-background">
        <div className="page-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
