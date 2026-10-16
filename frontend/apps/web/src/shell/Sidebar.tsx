import {
  Activity,
  Brain,
  Briefcase,
  Building2,
  ChevronDown,
  History,
  Layers,
  LayoutDashboard,
  ListChecks,
  Plug,
  Route as RouteIcon,
  Scale,
  ScrollText,
  Settings,
  ShieldCheck,
  TriangleAlert,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { canSeeGroup, planLabel, roleLabel } from "@edp/shared";
import { useSessionStore } from "../features/auth/session-store";
import { initials } from "../lib/labels";
import { TenantSwitchModal } from "./TenantSwitchModal";

interface NavEntry {
  to: string;
  domId: string;
  nav: string;
  label: string;
  icon: LucideIcon;
}

const OVERVIEW: NavEntry = {
  to: "/admin/overview",
  domId: "nav-overview",
  nav: "overview",
  label: "运营总览",
  icon: LayoutDashboard,
};

const WORKBENCH: NavEntry[] = [
  { to: "/admin/registry", domId: "nav-objects", nav: "objects", label: "业务对象", icon: Layers },
  { to: "/admin/events", domId: "nav-events", nav: "events", label: "事件流", icon: Zap },
  { to: "/admin/evidence", domId: "nav-evidence", nav: "evidence", label: "证据库", icon: ShieldCheck },
];

const OPS_MONITOR: NavEntry[] = [
  { to: "/admin/quality", domId: "nav-quality", nav: "quality", label: "数据质量", icon: TriangleAlert },
  { to: "/admin/audit", domId: "nav-governance", nav: "governance", label: "审计日志", icon: ScrollText },
  { to: "/admin/adapters", domId: "nav-adapters", nav: "adapters", label: "适配器管理", icon: Plug },
  { to: "/admin/systems", domId: "nav-systems", nav: "systems", label: "系统健康", icon: Activity },
];

const PLATFORM_CONFIG: NavEntry[] = [
  { to: "/tenants", domId: "nav-tenants", nav: "tenants", label: "租户管理", icon: Building2 },
];

const CLOSED_LOOP: NavEntry[] = [
  { to: "/cases", domId: "nav-cases", nav: "cases", label: "闭环案例", icon: Briefcase },
  { to: "/decisions", domId: "nav-decisions", nav: "decisions", label: "决策", icon: Scale },
  { to: "/actions", domId: "nav-actions", nav: "actions", label: "行动", icon: ListChecks },
  { to: "/admin/tools", domId: "nav-tools", nav: "tools", label: "Agent 工具", icon: Wrench },
  { to: "/admin/traces", domId: "nav-traces", nav: "traces", label: "Trace 检索", icon: RouteIcon },
  { to: "/admin/memory", domId: "nav-memory", nav: "memory", label: "候选记忆", icon: Brain },
  { to: "/admin/drills", domId: "nav-drills", nav: "drills", label: "演练回放", icon: History },
];

function NavItemLink({ entry }: { entry: NavEntry }) {
  const { pathname } = useLocation();
  const active = pathname === entry.to;
  const Icon = entry.icon;
  return (
    <NavLink
      to={entry.to}
      data-dom-id={entry.domId}
      data-nav={entry.nav}
      data-active={active ? "true" : undefined}
      className={`nav-item w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-xs font-medium text-left transition-colors${
        active ? " active" : " hover:bg-muted"
      }`}
    >
      <Icon className="w-[18px] h-[18px]" aria-hidden="true" />
      <span>{entry.label}</span>
    </NavLink>
  );
}

function NavGroupTitle({ title }: { title: string }) {
  return (
    <div className="px-3 pt-3 pb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
      {title}
    </div>
  );
}

/** 侧边栏（结构/class/尺寸照抄原型 运营总览.html 行 239~306）。 */
export function Sidebar() {
  const navigate = useNavigate();
  const user = useSessionStore((s) => s.user);
  const tenant = useSessionStore((s) => s.tenant);
  const [switchOpen, setSwitchOpen] = useState(false);

  const displayName = user?.display_name || user?.username || "未登录";
  const tenantName = tenant?.name ?? "ACME · 华东事业群";
  const tenantSubtitle = tenant ? `${planLabel(tenant.plan)} · 生产环境` : "Enterprise · 生产环境";

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-[250px] bg-card border-r border-border z-20 flex flex-col sidebar">
      <div className="h-[70px] flex items-center px-4 border-b border-border">
        <div className="w-9 h-9 rounded-lg bg-primary text-primary-foreground grid place-items-center font-extrabold text-lg shadow-sm">
          E
        </div>
        <div className="ml-2.5">
          <b className="text-sm">AEOS EDP</b>
          <span className="block text-[10px] text-muted-foreground">Evidence Data Platform</span>
        </div>
      </div>
      <div className="p-3.5">
        <button
          type="button"
          className="w-full border border-border bg-card rounded-xl p-2.5 flex items-center gap-2 hover:bg-muted transition-colors"
          data-dom-id="tenant-switch"
          onClick={() => setSwitchOpen(true)}
        >
          <div className="w-7 h-7 rounded-lg bg-primary-50 text-primary grid place-items-center text-xs font-extrabold">
            {initials(tenantName)}
          </div>
          <div className="min-w-0 flex-1 text-left">
            <b className="text-xs block truncate">{tenantName}</b>
            <span className="text-[10px] text-muted-foreground block truncate">{tenantSubtitle}</span>
          </div>
          <ChevronDown className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
        </button>
      </div>
      <nav className="flex-1 px-2.5 py-2 overflow-y-auto">
        <NavItemLink entry={OVERVIEW} />
        <NavGroupTitle title="数据工作台" />
        {WORKBENCH.map((entry) => (
          <NavItemLink key={entry.domId} entry={entry} />
        ))}
        <NavGroupTitle title="运维监控" />
        {OPS_MONITOR.map((entry) => (
          <NavItemLink key={entry.domId} entry={entry} />
        ))}
        <NavGroupTitle title="平台配置" />
        {PLATFORM_CONFIG.map((entry) => (
          <NavItemLink key={entry.domId} entry={entry} />
        ))}
        {canSeeGroup("closed_loop", user?.roles ?? [], Boolean(user?.is_platform_admin)) && (
          <>
            <NavGroupTitle title="智能闭环" />
            {CLOSED_LOOP.map((entry) => (
              <NavItemLink key={entry.domId} entry={entry} />
            ))}
          </>
        )}
      </nav>
      <div className="p-3.5 border-t border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-primary-50 text-primary grid place-items-center text-[11px] font-extrabold">
            {initials(displayName)}
          </div>
          <div className="flex-1 min-w-0">
            <b className="text-xs block truncate">{displayName}</b>
            <span className="text-[10px] text-muted-foreground block truncate">
              {roleLabel(user?.roles?.[0])}
            </span>
          </div>
          <button
            type="button"
            className="w-8 h-8 rounded-lg border border-border bg-card grid place-items-center text-muted-foreground hover:bg-muted"
            data-dom-id="settings-btn"
            onClick={() => void navigate("/profile")}
          >
            <Settings className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <TenantSwitchModal open={switchOpen} onClose={() => setSwitchOpen(false)} />
    </aside>
  );
}
