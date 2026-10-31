import type { AdapterSummary } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";

/** B.12 + 13.6 适配器页 7 列。plm=降级（呼应场景 10）；mode=mock（Mock 适配器为基线交付）。 */
export const adapters: AdapterSummary[] = [
  { adapter: "erp", mode: "mock", access: "REST 拉取", team: "数据平台组", last_sync: minutesBefore(12), health: "OK", health_pct: 99.9, status: "运行中", isolation: "租户级" },
  { adapter: "mes", mode: "mock", access: "REST 拉取", team: "制造运营组", last_sync: minutesBefore(26), health: "OK", health_pct: 99.7, status: "运行中", isolation: "租户级" },
  { adapter: "plm", mode: "mock", access: "REST 拉取", team: "研发效能组", last_sync: hoursBefore(3), health: "DEGRADED", health_pct: 96.2, status: "降级", isolation: "租户级" },
  { adapter: "mdm", mode: "mock", access: "DB 拉取", team: "数据平台组", last_sync: minutesBefore(40), health: "OK", health_pct: 99.9, status: "运行中", isolation: "租户级" },
  { adapter: "crm", mode: "mock", access: "REST 推送", team: "销售运营组", last_sync: hoursBefore(1), health: "OK", health_pct: 99.8, status: "运行中", isolation: "租户级" },
];
