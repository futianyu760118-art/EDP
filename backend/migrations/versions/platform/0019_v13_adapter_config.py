"""V1.3 T50 适配器可配置化基线：systems.adapter_config（DB 拉取驱动配置）。

- adapter_config：JSONB（可空无默认）——DbPullAdapter 配置（dsn + tables
  表规格列表），存在即该 systems 行可装配为真实拉取适配器；
- adapter_mode 语义（T50 裁定）：携带 adapter_config 的注册行置 'real'
  （清单展示与装配判据），无则保持 DDL 默认 'mock'。

Revision ID: 0019_v13_adapter_config
Revises: 0018_v13_realtime
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0019_v13_adapter_config"
down_revision: str | None = "0018_v13_realtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    has = conn.execute(
        text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'platform' AND table_name = 'systems'
              AND column_name = 'adapter_config'
        """)
    ).scalar() is not None
    if not has:
        op.execute("ALTER TABLE platform.systems ADD COLUMN adapter_config JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.systems DROP COLUMN IF EXISTS adapter_config")
