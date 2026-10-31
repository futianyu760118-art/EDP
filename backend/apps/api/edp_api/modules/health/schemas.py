"""health 响应模型（设计文档附录 B.13 子集 + MSW ops_metrics 字段名逐字对齐）。

字段事实来源：
- 基础字段 status/db/db_ha/outbox_pending/last_sync/version = B.13 示例；
- ``ops_metrics`` = 前端 ``mocks/types.ts`` ``HealthResponse.ops_metrics`` 的
  KPI 子集（events_24h/ingest_peak_24h/p95_latency_ms/idempotency_hit_rate/
  dlq/evidence_count）——事件流页 KPI 带真数据源（spec §6.3）；
- ``db_ha`` 仅 ``?deep=true`` 填充（路由 ``response_model_exclude_none`` 下
  非 deep 响应不含该键）；
- W6 扩展 5 可选字段（backup/audit_events_7d/policy_hits_today/
  adapters_success_rate/evidence_valid_rate，全 ``| None = None`` 向后兼容，
  exclude_none 语义下无数据不出现）——总览页 KPI 真数据源（W5-11/05 +
  EDP-034 数据源批；派生口径见 service docstring）。
"""

from pydantic import BaseModel


class DbHa(BaseModel):
    """数据库高可用状态（仅 deep=true；开发库 replicas=0、lag=0）。"""

    role: str
    replication_lag_mb: float
    replicas: int


class BackupMetric(BaseModel):
    """备份读数派生（drills JSON 备份相关演练；source 恒 "drills"）。"""

    last_backup_at: str
    status: str
    source: str


class OpsMetrics(BaseModel):
    """运行指标（近 24h 窗口；字段名与 MSW ``HealthResponse.ops_metrics`` 逐字一致；
    W6 扩展 5 字段可选——无数据不出现（exclude_none））。"""

    events_24h: int
    ingest_peak_24h: int
    p95_latency_ms: int
    idempotency_hit_rate: float
    dlq: int
    evidence_count: int
    backup: BackupMetric | None = None
    audit_events_7d: int | None = None
    policy_hits_today: int | None = None
    adapters_success_rate: float | None = None
    evidence_valid_rate: float | None = None


class HealthResponse(BaseModel):
    """GET /api/v1/health 响应（B.13 子集）。"""

    status: str
    db: str
    db_ha: DbHa | None = None
    outbox_pending: int
    last_sync: dict[str, str]
    version: str
    ops_metrics: OpsMetrics
