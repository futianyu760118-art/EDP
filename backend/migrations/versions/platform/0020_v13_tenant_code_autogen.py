"""V1.3 租户编码自动生成：计数表 + 存量重写（ten-YYYY-NNNN，设计
docs/superpowers/specs/2026-10-16-tenant-code-autogen-design.md）。

- platform.tenant_code_seq(year PK, last_no)：取号计数表（控制面，无 RLS
  ——无租户语义，与 tenants/tenant_quotas 同级；权限收敛 edp_app）。开通
  路径单条 upsert-returning 原子取号（service.next_tenant_code），行锁
  串行化保证不重号，无竞态无重试；
- 存量租户 slug 重写为 ten-<创建年>-<序号>：按年分组、组内
  (created_at, tenant_id) 升序确定性编号（lpad 四位，>9999 自然 5 位）；
  已是 ten-* 格式的行幂等跳过；与现存 slug 冲突时顺延取号（防御人工
  预置 ten-* 行的场景）；
- default 锚点除外（登录 tenant_slug 缺省解析与 demo/ingest CLI
  --tenant-slug 均锚定 default，见设计 §5——迁移零波及登录与 CLI）；
- 旧 slug 备份 attributes.legacy_slug（downgrade 精确还原）；计数表回填
  各年存量最大序号，后续 API 取号从存量后续起。

downgrade 裁定：还原全部带 legacy_slug 的行后删计数表；迁移期间新建、
无 legacy_slug 的 ten-* 租户保持新格式不回滚（无旧值可还原，不阻塞降级）。

Revision ID: 0020_v13_tenant_code_autogen
Revises: 0019_v13_adapter_config
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0020_v13_tenant_code_autogen"
down_revision: str | None = "0019_v13_adapter_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 已是新格式的判定（含 5 位溢出形态）；default 为登录/CLI 缺省锚点除外
_NEW_FORMAT = r"^ten-[0-9]{4}-[0-9]{4,}$"


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    return conn.execute(text(sql), params or {}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ---- 1. 取号计数表（幂等） ----
    if not _exists(
        conn,
        """
        SELECT to_regclass('platform.tenant_code_seq')
        """,
    ):
        op.execute("""
            CREATE TABLE platform.tenant_code_seq (
                year INTEGER PRIMARY KEY,
                last_no INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON platform.tenant_code_seq TO edp_app"
    )

    # ---- 2. 存量重写：按年分组确定性编号（default 与已是新格式者除外） ----
    ranked = conn.execute(
        text("""
            SELECT tenant_id, slug,
                   (extract(year FROM created_at))::int AS yr,
                   row_number() OVER (
                       PARTITION BY (extract(year FROM created_at))::int
                       ORDER BY created_at, tenant_id
                   )::int AS rn
            FROM platform.tenants
            WHERE slug <> 'default' AND slug !~ :fmt
            ORDER BY yr, rn
        """),
        {"fmt": _NEW_FORMAT},
    ).mappings().all()
    taken = set(conn.execute(text("SELECT slug FROM platform.tenants")).scalars())
    for row in ranked:
        no = int(row["rn"])
        new_slug = f"ten-{row['yr']}-{no:04d}"
        # 防御：与人工预置的 ten-* 现存行撞号时顺延（计数表回填取最终最大值）
        while new_slug in taken:
            no += 1
            new_slug = f"ten-{row['yr']}-{no:04d}"
        taken.discard(row["slug"])
        taken.add(new_slug)
        conn.execute(
            text("""
                UPDATE platform.tenants
                SET slug = :new_slug,
                    attributes = attributes
                        || jsonb_build_object(
                            'legacy_slug', CAST(:legacy AS text)),
                    updated_at = now()
                WHERE tenant_id = :tid
            """),
            {"new_slug": new_slug, "legacy": row["slug"], "tid": row["tenant_id"]},
        )

    # ---- 3. 计数表回填：各年存量最大序号（后续取号从存量后续起） ----
    op.execute("""
        INSERT INTO platform.tenant_code_seq (year, last_no)
        SELECT (substring(slug from '^ten-([0-9]{4})-'))::int AS yr,
               max((substring(slug from '^ten-[0-9]{4}-([0-9]+)$'))::int)
        FROM platform.tenants
        WHERE slug ~ '^ten-[0-9]{4}-[0-9]{4,}$'
        GROUP BY 1
        ON CONFLICT (year) DO UPDATE
        SET last_no = GREATEST(
                platform.tenant_code_seq.last_no, EXCLUDED.last_no),
            updated_at = now()
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE platform.tenants
        SET slug = attributes->>'legacy_slug',
            attributes = attributes - 'legacy_slug',
            updated_at = now()
        WHERE attributes ? 'legacy_slug'
    """)
    op.execute("DROP TABLE IF EXISTS platform.tenant_code_seq")
