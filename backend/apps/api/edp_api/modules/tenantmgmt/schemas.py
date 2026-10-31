"""tenantmgmt 请求/响应模型（当前租户信息 + W2 生命周期 EDP-024/B.14 +
W5 B.14 补齐：PATCH/context/members/quotas，EDP-501 后端）。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TenantPlan = Literal["TRIAL", "STANDARD", "PREMIUM", "DEDICATED"]
LifecycleOperation = Literal["suspend", "resume", "cancel"]


class TenantInfo(BaseModel):
    """当前租户信息（GET /api/v1/tenants/current）：id/slug/name/plan/status。"""

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str


class TenantAdminCreate(BaseModel):
    """初始管理员（B.14）：password 未携带时服务端生成临时口令并在开通
    响应中回传一次（temporary_password）。"""

    username: str = Field(min_length=2, max_length=64, description="租户内唯一")
    email: str = Field(
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        max_length=320,
        description="租户内唯一",
    )
    display_name: str = Field(min_length=1, max_length=128)
    password: str | None = Field(
        default=None, min_length=8, max_length=128, description="缺省时生成临时口令"
    )


class TenantCreateRequest(BaseModel):
    """开通租户请求（B.14）：编码由服务端自动生成（ten-YYYY-NNNN），
    请求体不携带 slug；传入的 slug 字段被忽略（完全自动，不支持自定义）。"""

    name: str = Field(min_length=1, max_length=128)
    plan: TenantPlan
    admin: TenantAdminCreate


class TenantCreateResponse(BaseModel):
    """开通响应；temporary_password 仅在请求未携带 admin.password 时非空。"""

    tenant_id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime
    initial_admin_user_id: UUID
    temporary_password: str | None = Field(
        default=None,
        description=(
            "B.14 扩展：请求未携带 admin.password 时服务端生成的一次性临时口令，"
            "仅本次响应返回，请立即交付管理员并要求首登修改"
        ),
    )


class TenantLifecycleResponse(BaseModel):
    """生命周期操作受理响应（202）。"""

    tenant_id: UUID
    status: str
    operation: LifecycleOperation
    occurred_at: datetime


class TenantCancelRequest(BaseModel):
    """注销强确认请求：confirm=true 且 reason 非空才受理。"""

    confirm: bool
    reason: str = Field(min_length=1, max_length=512)


class TenantSummary(BaseModel):
    """租户清单项（GET /api/v1/tenants）。"""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str
    created_at: datetime


class TenantQuotaInfo(BaseModel):
    """租户配额（plan 默认值由 PLAN_QUOTAS 落库，可运维调整）。"""

    model_config = ConfigDict(from_attributes=True)

    storage_gb: int
    events_per_month: int
    api_rate_limit: int
    batch_max_events: int
    query_timeout_ms: int
    pool_share: Decimal


class TenantUsage(BaseModel):
    """用量聚合（MVP 占位：字段恒 None，W3 计量接入后由
    tenant_usage_daily 聚合回填）。"""

    storage_used_gb: float | None = None
    events_this_month: int | None = None
    api_calls_today: int | None = None


class TenantDetail(BaseModel):
    """租户详情（GET /api/v1/tenants/{tenant_id}）：详情 + 配额/用量（可空）。"""

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str
    cancel_scheduled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    quotas: TenantQuotaInfo | None = None
    usage: TenantUsage | None = None


class UsageItem(BaseModel):
    """GET /tenants/{id}/usage 列表项（B.14 字段 + events_duplicated 超集）。"""

    model_config = ConfigDict(from_attributes=True)

    usage_date: date
    api_calls: int
    events_in: int
    events_duplicated: int
    storage_gb: Decimal
    throttled_429: int


# ---- W5 B.14 租户 API 补齐（EDP-501 后端，T2） ----

TenantMemberStatus = Literal["INVITED", "ACTIVE", "DISABLED"]


class TenantUpdateRequest(BaseModel):
    """PATCH /tenants/{id} 请求（B.14）：name / plan 均可选；plan 变更仅
    记录（租户对象 + 审计行），不联动配额调整（见 service.update_tenant）。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    plan: TenantPlan | None = None


class TenantContextResponse(BaseModel):
    """POST /tenants/{id}/context 响应（B.14 逐字段 + access_token）。

    B.14 未定义新 token 的下发通道；本实现以响应体 access_token 返回
    （最小可行口径，docstring 留痕见 platform_router/service）。
    """

    tenant_id: UUID
    switched_at: datetime
    note: str
    access_token: str


class TenantMemberItem(BaseModel):
    """成员投影（B.14 GET members）：display_name 经 join platform.users；
    joined_at = tenant_members.created_at（加入时间）。"""

    member_id: UUID
    user_id: UUID
    display_name: str | None = None
    member_roles: list[str]
    status: str
    joined_at: datetime


class AdminUserItem(BaseModel):
    """平台用户目录简投影（GET /api/v1/admin/users；W5-11 收口——邀请成员
    下拉真数据源）；display_name 可空透传。"""

    user_id: UUID
    username: str
    display_name: str | None = None


class TenantMemberCreateRequest(BaseModel):
    """POST members 请求（B.14）：user_id 须为目标租户内 ACTIVE 用户；
    member_roles 空数组的语义拒绝（422）由 service 判定。"""

    user_id: UUID
    member_roles: list[str] = Field(default_factory=list)


class TenantMemberUpdateRequest(BaseModel):
    """PATCH member 请求（B.14：改角色/禁用）；member_roles 提供且为空 →
    422（service 判定）；不可禁用最后一个 ACTIVE ADMIN（400，service 判定）。"""

    member_roles: list[str] | None = None
    status: TenantMemberStatus | None = None


class TenantQuotaDetail(BaseModel):
    """完整配额对象（B.14 七字段 + tenant_id；PATCH /tenants 响应同形）。"""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    api_rate_limit: int
    batch_max_events: int
    query_timeout_ms: int
    pool_share: Decimal
    storage_gb: int
    events_per_month: int
    updated_at: datetime | None = None


class TenantQuotaUpdateRequest(BaseModel):
    """PATCH quotas 请求（B.14 临时提额）：仅 api_rate_limit / storage_gb /
    events_per_month 三字段可调；reason 必填非空（422，service 判定——
    临时提额留痕，审计行 detail 携带）。"""

    api_rate_limit: int | None = Field(default=None, ge=1)
    storage_gb: int | None = Field(default=None, ge=1)
    events_per_month: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=512)
