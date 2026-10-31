import { adapterHandlers } from "./handlers/adapters";
import { actionHandlers } from "./handlers/actions";
import { auditHandlers } from "./handlers/audit";
import { authHandlers } from "./handlers/auth";
import { caseHandlers } from "./handlers/cases";
import { catalogHandlers } from "./handlers/catalog";
import { decisionHandlers } from "./handlers/decisions";
import { drillHandlers } from "./handlers/drills";
import { ebmsHandlers } from "./handlers/ebms";
import { eventHandlers } from "./handlers/events";
import { evidenceHandlers } from "./handlers/evidence";
import { healthHandlers } from "./handlers/health";
import { memoryHandlers } from "./handlers/memory";
import { qualityHandlers } from "./handlers/quality";
import { registryHandlers } from "./handlers/registry";
import { searchHandlers } from "./handlers/search";
import { tenantHandlers } from "./handlers/tenant";
import { toolHandlers } from "./handlers/tools";
import { traceHandlers } from "./handlers/traces";

/** W2+W3 六页 + W4 闭环案例/决策/行动 + W5 租户/演练/Agent 工具·Trace·记忆 + W6 全局搜索 MSW 数据层聚合（spec §3 端点清单 + EDP-403/404/502/503）。 */
export const handlers = [
  ...authHandlers,
  ...tenantHandlers,
  ...registryHandlers,
  ...eventHandlers,
  ...evidenceHandlers,
  ...qualityHandlers,
  ...healthHandlers,
  ...adapterHandlers,
  ...ebmsHandlers,
  ...auditHandlers,
  ...caseHandlers,
  ...decisionHandlers,
  ...actionHandlers,
  ...drillHandlers,
  ...catalogHandlers,
  ...toolHandlers,
  ...traceHandlers,
  ...memoryHandlers,
  ...searchHandlers,
];
