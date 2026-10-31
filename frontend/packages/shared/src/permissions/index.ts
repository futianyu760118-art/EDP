/**
 * 13.8 导航权限：侧边栏分组可见角色矩阵（设计文档 13.6.5 导航权限行）。
 * - 数据工作台 / 运维监控：全角色（ANALYST 只读，写按钮隐藏，后端 RBAC 兜底）；
 * - 平台配置（租户管理）：仅 PLATFORM_ADMIN；
 * - 智能闭环：PLATFORM_ADMIN / ADMIN（13.5）。
 * is_platform_admin（平台运营）通行全组。
 */

export type NavGroup = "workbench" | "ops_monitor" | "platform_config" | "closed_loop";

/** 四组导航可见角色矩阵："all" = 全角色可见；数组 = 命中任一角色可见。 */
export const NAV_GROUP_RULES: Record<NavGroup, readonly string[] | "all"> = {
  workbench: "all",
  ops_monitor: "all",
  platform_config: ["PLATFORM_ADMIN"],
  closed_loop: ["PLATFORM_ADMIN", "ADMIN"],
};

/** 分组对当前主体是否可见：平台管理员通行；否则按角色矩阵判定。 */
export function canSeeGroup(
  group: NavGroup,
  roles: readonly string[],
  isPlatformAdmin: boolean,
): boolean {
  if (isPlatformAdmin) return true;
  const rule = NAV_GROUP_RULES[group];
  if (rule === "all") return true;
  return rule.some((role) => roles.includes(role));
}
