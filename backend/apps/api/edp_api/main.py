"""应用工厂：create_app() 组合根（审计切面 + 中间件链 + 错误处理器 + 路由装配）。

extra_routers 供集成测试注入探针路由（测试内组装，生产代码不含测试面）；
模块级 app 保留为 uvicorn 入口（edp_api.main:app）。lifespan 启动钩子滚动
创建审计月分区（0009 起 SECURITY DEFINER，edp_app 可执行）——失败仅记日志
不阻断启动（分区另由迁移 0008 预建，双保险）。
"""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from edp_api.core import db as core_db
from edp_api.core.contextvars import RequestIDMiddleware
from edp_api.core.errors import install_error_handlers
from edp_api.modules.actions.router import router as actions_router
from edp_api.modules.adapters_admin.router import router as adapters_admin_router
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.audit.router import router as audit_router
from edp_api.modules.audit_policies.router import router as audit_policies_router
from edp_api.modules.catalog.router import router as catalog_router
from edp_api.modules.decisions.router import router as decisions_router
from edp_api.modules.ebms.router import router as ebms_router
from edp_api.modules.events.router import router as events_router
from edp_api.modules.evidence.router import admin_router as evidence_admin_router
from edp_api.modules.evidence.router import router as evidence_router
from edp_api.modules.governance.router import router as governance_router
from edp_api.modules.health.router import router as health_router
from edp_api.modules.ingest.router import router as ingest_router
from edp_api.modules.lineage.router import router as lineage_router
from edp_api.modules.memories.router import router as memories_router
from edp_api.modules.metric.router import router as metric_router
from edp_api.modules.period.router import router as period_router
from edp_api.modules.platform.router import router as platform_router
from edp_api.modules.quality.router import drills_router as quality_drills_router
from edp_api.modules.quality.router import outbox_router as quality_outbox_router
from edp_api.modules.quality.router import router as quality_router
from edp_api.modules.registry.router import router as registry_router
from edp_api.modules.result.router import router as result_router
from edp_api.modules.search.router import router as search_router
from edp_api.modules.tenantmgmt.platform_router import admin_router as tenant_admin_router
from edp_api.modules.tenantmgmt.platform_router import router as tenant_platform_router
from edp_api.modules.tenantmgmt.router import router as tenantmgmt_router
from edp_api.modules.tools.router import router as tools_router
from edp_api.modules.traces.router import router as traces_router
from edp_api.modules.value.router import router as value_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动钩子：滚动创建当月起三个月审计分区；失败记日志不阻断启动。"""
    try:
        engine = core_db.get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT platform.ensure_audit_partitions()"))
            await conn.commit()
    except Exception:
        logger.warning("ensure_audit_partitions 启动执行失败", exc_info=True)
    yield


def create_app(extra_routers: Sequence[APIRouter] = ()) -> FastAPI:
    """构建 FastAPI 应用；extra_routers 追加注册（默认空）。"""
    # 审计切面（Session 级 before_flush）：任何会话使用前注册（幂等）
    install_audit_aspect()
    # 路由前缀已含 /api/v1（契约路径完整自包含），故不设 servers
    app = FastAPI(
        title="EDP Data Platform API",
        version="1.0.0",
        description="EDP 数据平台开放 API：认证、主数据登记（registry）与事件批量入库（events）。",
        lifespan=_lifespan,
    )

    app.add_middleware(RequestIDMiddleware)
    install_error_handlers(app)

    # auth 路由：平台级（不挂租户绑定）；get_db 在路由内提供请求级会话，
    # get_principal 仅对 /me 生效（Bearer 优先，X-API-Key 走 lookup_api_key）
    app.include_router(platform_router)
    # registry 路由（B.2）：业务面，统一挂 tenant_scoped（RLS 隔离）
    app.include_router(registry_router)
    # events 路由（B.3）：业务面，统一挂 tenant_scoped（RLS 隔离）
    app.include_router(events_router)
    # tenantmgmt 路由：GET /tenants/current（tenant_scoped；租户管理 CRUD W2+）
    app.include_router(tenantmgmt_router)
    # tenantmgmt 平台级路由（EDP-024）：租户生命周期（开通/清单/详情/暂停/
    # 恢复/注销）——require_platform_admin 守卫，平台级无租户绑定（不挂
    # tenant_scoped）；后于 /current 注册，避免 /{tenant_id} 先匹配吞并
    app.include_router(tenant_platform_router)
    # tenantmgmt 平台用户目录（W5-11 收口）：GET /admin/users——邀请成员
    # 下拉真数据源（require_platform_admin，简投影游标分页）
    app.include_router(tenant_admin_router)
    # audit 路由（B.6）：查询面，统一挂 tenant_scoped（租户收敛见 service）
    app.include_router(audit_router)
    # audit_policies 路由（EDP-032 最小版）：/admin/audit-policies CRUD，
    # 命中打标经 audit.aspect 消费 audit_policies.service.matching
    app.include_router(audit_policies_router)
    # evidence 路由（B.4）：证据面，统一挂 tenant_scoped（RLS 隔离）
    app.include_router(evidence_router)
    # evidence 管理路由（W3-04 收口）：/admin/evidence/reindex（quality:run
    # 复用口径，任务轨道复用 quality tasks 端点）
    app.include_router(evidence_admin_router)
    # adapters_admin 路由（B.12）：sync 触发/状态/清单，统一挂 tenant_scoped
    app.include_router(adapters_admin_router)
    # tools 路由（B.8）：Agent 数据工具（Read-Only 三层，仅 GET）
    app.include_router(tools_router)
    # decisions 路由（B.5）：决策案例（EDP-018 最小版；records Human-Only）
    app.include_router(decisions_router)
    # actions 路由（B.5）：行动任务状态机（EDP-020；Human-Only 两转移）
    app.include_router(actions_router)
    # ebms 路由（B.9 子集）：EBMS 查询聚合（EDP-012，本轮 exceptions）
    app.include_router(ebms_router)
    # catalog 路由（B.7）：注册中心 systems/capabilities/skills（EDP-011）
    app.include_router(catalog_router)
    # traces 路由（B.10）：Agent 执行轨迹写入/查询（EDP-013）
    app.include_router(traces_router)
    # memories 路由（B.11）：学习记忆候选 + Human-Only 评审（EDP-014）
    app.include_router(memories_router)
    # health 路由（B.13 子集）：基础健康 + ops_metrics（事件流页 KPI 真数据源）
    app.include_router(health_router)
    # quality 路由（B.13 上半）：质量报告/覆盖率（EDP-030；rechecks/tasks T4 起）
    app.include_router(quality_router)
    # quality drills 路由（EDP-502 / W5 T7）：/admin/drills 演练记录只读归档
    # （drill-records.json；复用 quality:read 口径，无 DB 访问）
    app.include_router(quality_drills_router)
    # quality outbox 路由（W5-05 收口）：/admin/outbox/status——event.outbox
    # 聚合（quality:read；运营报告/健康页 Outbox 积压卡数据源）
    app.include_router(quality_outbox_router)
    # search 路由（W6 T1）：全局搜索三组聚合（对象/事件/证据，RLS 收敛）
    app.include_router(search_router)
    # governance 路由（V1.2 Phase 2）：规则/别名/分类注册 + RAW 只读 + 准入审核
    app.include_router(governance_router)
    # lineage 路由（V1.2 Phase 3）：数据血缘只读（governance:read 轨道）
    app.include_router(lineage_router)
    # result 路由（V1.2 Phase 3）：经营结果创建/列表/详情/核验
    app.include_router(result_router)
    # metric 路由（V1.2 Phase 4）：指标口径注册 + 计量值
    app.include_router(metric_router)
    # period 路由（V1.2 Phase 4）：AEOS 经营窗口 + 周期枚举
    app.include_router(period_router)
    # value 路由（V1.2 Phase 4）：价值账本（复用 metric 权限轨道）
    app.include_router(value_router)
    # ingest 文件导入路由（V1.2 Phase 5 / T30）：Excel/CSV 通道
    app.include_router(ingest_router)
    for router in extra_routers:
        app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
