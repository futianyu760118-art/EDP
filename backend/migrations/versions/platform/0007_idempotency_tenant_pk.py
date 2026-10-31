"""idempotency_keys 主键改复合 (tenant_id, key)：幂等键按租户命名空间隔离。

修复 T12 Concern #3：0001 登记项以 key 为全局主键，跨租户同 Key 字符串在
INSERT 时撞全局唯一约束（500 风险）；即使被 ON CONFLICT DO NOTHING 吸收，
后到租户的成功批次也静默失去接口层幂等存档（重放退化为数据层 duplicated
重算，语义降级）。接口层幂等语义按设计文档 7.1（幂等三层）与 3.4（租户
命名空间隔离）应以 (tenant_id, key) 为唯一维度：读档本就受 FORCE RLS 限
本租户，本迁移使写档冲突面同样收敛到租户内——幂等键不再全局互斥。

W1 新表（0001 登记项）且存档均带 TTL 短生命周期，运行库无需数据回填，
空表/少行变更无数据迁移问题。

Revision ID: 0007_idem_tenant_pk
Revises: 0006_auth_definer
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_idem_tenant_pk"
down_revision: str | None = "0006_auth_definer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform.idempotency_keys DROP CONSTRAINT idempotency_keys_pkey")
    op.execute("ALTER TABLE platform.idempotency_keys ADD PRIMARY KEY (tenant_id, key)")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.idempotency_keys DROP CONSTRAINT idempotency_keys_pkey")
    op.execute("ALTER TABLE platform.idempotency_keys ADD PRIMARY KEY (key)")
