"""platform schema 基线（设计文档附录 A.1 逐条转录 + W1 idempotency_keys 登记项）。

15 张表（\\dt platform.* 应为 15 行）：
    tenants, tenant_members, tenant_quotas, tenant_usage_daily, organizations,
    users, roles, permissions, role_permissions, api_keys, systems,
    capabilities, skills, audit_logs, idempotency_keys（W1 登记项，附录 A 之外）

约定：
- 角色：edp_app（LOGIN，受 RLS 约束的应用角色）由本迁移 DO 块幂等创建；
  edp_migrator（属主 + BYPASSRLS）由环境供给（容器 env / testcontainers），迁移不创建。
- RLS（ENABLE + FORCE + tenant_isolation 策略）：A.1 中标注 "-- + RLS" 的表，即
  tenant_members / organizations / users / api_keys / systems / capabilities /
  skills，外加 W1 登记的 idempotency_keys；控制面表 tenants / tenant_quotas /
  tenant_usage_daily / roles / permissions / role_permissions / audit_logs 不启用。
- 审计字段（created_at/updated_at/created_by/updated_by）仅追加于 A.1 标注
  "+ 审计字段" 的表；permissions / role_permissions（全局模板，A.1 未标注）与
  audit_logs（日志表自身）不追加。
- PG16 适配：分区表暂不支持 identity 列，audit_logs.audit_id 以 BIGSERIAL 实现
  （语义等价；PG17 起可改回 GENERATED ALWAYS AS IDENTITY）。

Revision ID: 0001_platform
Revises:
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_platform"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A.1 中标注 "-- + RLS" 的业务表 + W1 登记的 idempotency_keys
RLS_TABLES = (
    "platform.tenant_members",
    "platform.organizations",
    "platform.users",
    "platform.api_keys",
    "platform.systems",
    "platform.capabilities",
    "platform.skills",
    "platform.idempotency_keys",
)

POLICY = "tenant_isolation"
# NULLIF 防御：事务级 set_config 提交/回滚后复位为空串（''::uuid 会抛错），
# 空串统一归一为 NULL → 隔离判空（0 行），未绑定请求不致 500
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}")


def upgrade() -> None:
    # ---- 0. 角色守卫与 schema（幂等） ----
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'edp_app') THEN
                CREATE ROLE edp_app LOGIN PASSWORD 'edp_app';
            END IF;
        END $$
    """)
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.execute("GRANT USAGE ON SCHEMA platform TO edp_app")

    # ---- 1. 控制平面（不启用 RLS） ----
    # 租户主表（平台根实体）
    op.execute("""
        CREATE TABLE platform.tenants (
            tenant_id UUID PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'STANDARD'
                CHECK (plan IN ('TRIAL','STANDARD','PREMIUM','DEDICATED')),
            status TEXT NOT NULL DEFAULT 'PROVISIONING'
                CHECK (status IN ('PROVISIONING','ACTIVE','SUSPENDED','CANCELLED')),
            tenant_shard INT NOT NULL DEFAULT 0,
            cancel_scheduled_at TIMESTAMPTZ,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_tenants_status ON platform.tenants(status)")

    # 租户配额（3.5 防护配置）
    op.execute("""
        CREATE TABLE platform.tenant_quotas (
            tenant_id UUID PRIMARY KEY REFERENCES platform.tenants(tenant_id),
            api_rate_limit INT NOT NULL DEFAULT 100,
            batch_max_events INT NOT NULL DEFAULT 1000,
            query_timeout_ms INT NOT NULL DEFAULT 5000,
            pool_share NUMERIC(5,2) NOT NULL DEFAULT 2.0,
            storage_gb INT NOT NULL DEFAULT 50,
            events_per_month INT NOT NULL DEFAULT 1000000,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)

    # 使用量统计（日粒度；Phase 2 计费输入）
    op.execute("""
        CREATE TABLE platform.tenant_usage_daily (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            usage_date DATE NOT NULL,
            api_calls BIGINT NOT NULL DEFAULT 0,
            events_in BIGINT NOT NULL DEFAULT 0,
            storage_gb NUMERIC(12,2) NOT NULL DEFAULT 0,
            throttled_429 BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_usage_daily
            ON platform.tenant_usage_daily(tenant_id, usage_date)
    """)

    # ---- 2. 业务表（含 tenant_id + RLS） ----
    # 组织（租户内层级，非隔离边界）
    op.execute("""
        CREATE TABLE platform.organizations (
            org_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            name TEXT NOT NULL,
            parent_org_id UUID REFERENCES platform.organizations(org_id),
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','DISABLED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_orgs_tenant ON platform.organizations(tenant_id)")

    # 用户（全局身份；租户归属经 tenant_members）
    op.execute("""
        CREATE TABLE platform.users (
            user_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            org_id UUID REFERENCES platform.organizations(org_id),
            principal_type TEXT NOT NULL DEFAULT 'HUMAN'
                CHECK (principal_type IN ('HUMAN','AI')),
            is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','DISABLED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_users_username ON platform.users(tenant_id, username)")
    op.execute("CREATE UNIQUE INDEX uq_users_email ON platform.users(tenant_id, email)")

    # 租户成员（用户↔租户绑定 + 租户内角色；替代独立 user_roles 表）
    op.execute("""
        CREATE TABLE platform.tenant_members (
            member_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            user_id UUID NOT NULL REFERENCES platform.users(user_id),
            member_roles TEXT[] NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('INVITED','ACTIVE','DISABLED')),
            invited_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_tenant_member
            ON platform.tenant_members(tenant_id, user_id)
    """)

    # ---- 3. 角色 / 权限 / 授权（全局模板，不启用 RLS） ----
    op.execute("""
        CREATE TABLE platform.roles (
            role_id UUID PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)

    op.execute("""
        CREATE TABLE platform.permissions (
            permission_id UUID PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            resource TEXT NOT NULL,
            action TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE platform.role_permissions (
            role_id UUID REFERENCES platform.roles(role_id),
            permission_id UUID REFERENCES platform.permissions(permission_id),
            PRIMARY KEY (role_id, permission_id)
        )
    """)

    # ---- 4. 服务主体 / 系统与能力注册 ----
    # API 密钥（服务主体；绑定租户）
    op.execute("""
        CREATE TABLE platform.api_keys (
            key_id UUID PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            principal_type TEXT NOT NULL DEFAULT 'SERVICE'
                CHECK (principal_type IN ('SERVICE','AI')),
            principal_id TEXT NOT NULL,
            scopes TEXT[] NOT NULL DEFAULT '{}',
            expires_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','REVOKED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_api_keys_tenant
            ON platform.api_keys(tenant_id, principal_type, principal_id)
    """)

    # 系统注册（按租户的源系统/消费方连接配置）
    op.execute("""
        CREATE TABLE platform.systems (
            system_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            endpoint TEXT,
            adapter_mode TEXT NOT NULL DEFAULT 'mock'
                CHECK (adapter_mode IN ('mock','real')),
            auth_config JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','DISABLED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_systems_name ON platform.systems(tenant_id, name)")

    # 能力注册（Agent 中枢能力的存储，按租户）
    op.execute("""
        CREATE TABLE platform.capabilities (
            capability_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            input_schema JSONB NOT NULL,
            output_schema JSONB NOT NULL,
            risk_level TEXT NOT NULL CHECK (risk_level IN ('L0','L1','L2','L3')),
            permission TEXT NOT NULL
                CHECK (permission IN ('HUMAN_ONLY','READ_ONLY','AUTO_ALLOWED')),
            endpoint TEXT,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_capability_name ON platform.capabilities(tenant_id, name)")

    # 技能（Prompt/模型版本）
    op.execute("""
        CREATE TABLE platform.skills (
            skill_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            capability_id UUID NOT NULL
                REFERENCES platform.capabilities(capability_id),
            prompt TEXT NOT NULL,
            model_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_skills_capability
            ON platform.skills(tenant_id, capability_id, status)
    """)

    # ---- 5. 审计日志（仅追加，按月分区；控制面，不启用 RLS） ----
    op.execute("""
        CREATE TABLE platform.audit_logs (
            audit_id BIGSERIAL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID,
            actor_type TEXT NOT NULL CHECK (actor_type IN ('HUMAN','SERVICE','AI')),
            actor_id TEXT NOT NULL,
            request_id UUID,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            detail JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (audit_id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
    """)
    op.execute("CREATE INDEX idx_audit_tenant ON platform.audit_logs(tenant_id, occurred_at)")
    op.execute("""
        CREATE INDEX idx_audit_actor
            ON platform.audit_logs(actor_type, actor_id, occurred_at)
    """)
    op.execute("""
        CREATE INDEX idx_audit_resource
            ON platform.audit_logs(resource_type, resource_id, occurred_at)
    """)
    op.execute("CREATE INDEX idx_audit_action ON platform.audit_logs(action, occurred_at)")

    # ---- 6. W1 登记项：接口层幂等表（附录 A 之外） ----
    op.execute("""
        CREATE TABLE platform.idempotency_keys (
            key TEXT PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            endpoint TEXT NOT NULL,
            response_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX idx_idem_expires ON platform.idempotency_keys(expires_at)")

    # ---- 7. RLS：ENABLE + FORCE + tenant_isolation ----
    for table in RLS_TABLES:
        _enable_rls(table)

    # ---- 8. 尾部统一授权 ----
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA platform TO edp_app
    """)
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA platform TO edp_app
    """)


def downgrade() -> None:
    # 逆序清理：策略 → 表（子先父后）→ schema。
    # 角色不删除：edp_app / edp_migrator 的生命周期归环境/运维管理。
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")

    for table in (
        "platform.idempotency_keys",
        "platform.audit_logs",
        "platform.skills",
        "platform.capabilities",
        "platform.systems",
        "platform.api_keys",
        "platform.role_permissions",
        "platform.permissions",
        "platform.roles",
        "platform.tenant_members",
        "platform.users",
        "platform.organizations",
        "platform.tenant_usage_daily",
        "platform.tenant_quotas",
        "platform.tenants",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")

    op.execute("DROP SCHEMA IF EXISTS platform CASCADE")
