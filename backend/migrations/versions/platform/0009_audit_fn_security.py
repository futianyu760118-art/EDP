"""审计分区函数 SECURITY DEFINER（T10 评审必办项）。

背景：main.py 应用启动（lifespan）以 edp_app 执行 SELECT platform.
ensure_audit_partitions() 滚动创建未来月分区；0008 建立的函数为默认
SECURITY INVOKER——内部 CREATE TABLE 以调用者权限执行，edp_app 对
platform schema 无建表权 → 启动调用必失败。本迁移改为 SECURITY DEFINER
（以函数属主 edp_migrator 身份执行），并沿用 0006 先例收紧调用面：
REVOKE PUBLIC + GRANT edp_app；同时固定 search_path（SECURITY DEFINER
动态 SQL 的标准加固——本函数 DDL 已全限定，此为双保险）。

Revision ID: 0009_audit_fn_security
Revises: 0008_w2_baseline
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_audit_fn_security"
down_revision: str | None = "0008_w2_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN = "platform.ensure_audit_partitions()"


def upgrade() -> None:
    op.execute(
        f"ALTER FUNCTION {_FN} SECURITY DEFINER SET search_path = platform, pg_temp"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FN} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FN} TO edp_app")


def downgrade() -> None:
    """恢复 0008 原状：SECURITY INVOKER + 默认 PUBLIC 可执行（去 search_path）。"""
    op.execute(f"ALTER FUNCTION {_FN} SECURITY INVOKER RESET search_path")
    op.execute(f"REVOKE ALL ON FUNCTION {_FN} FROM edp_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FN} TO PUBLIC")
