"""V1.3 实时链路基线：realtime schema（stream_offsets / stream_dlq，T44）。

- stream_offsets：消费位点（consumer_group + topic + partition 主键），
  消费侧 ON CONFLICT 推进——PG 为位点事实来源（重启用位点恢复，不依赖
  Kafka group commit）；
- stream_dlq：死信队列（解析失败信封 + 坐标 + 错误），供排障与重放。

RLS 裁定（V1.3 偏差，test_v13_realtime_migration docstring 同口径）：
realtime.* 为平台基础设施坐标表，无业务租户语义，不启用 RLS（与
outbox 承载 tenant 业务事件不同；DLQ payload 为解析失败原始信封，租户
未知是其常态）。权限收敛 edp_app（worker 运行角色）。

Revision ID: 0018_v13_realtime
Revises: 0017_v12_object_tags
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0018_v13_realtime"
down_revision: str | None = "0017_v12_object_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    return conn.execute(text(sql), params or {}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _exists(
        conn, "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'realtime'"
    ):
        op.execute("CREATE SCHEMA realtime")
    op.execute("GRANT USAGE ON SCHEMA realtime TO edp_app")

    if not _exists(conn, "SELECT to_regclass('realtime.stream_offsets')"):
        op.execute("""
            CREATE TABLE realtime.stream_offsets (
                consumer_group TEXT NOT NULL,
                topic TEXT NOT NULL,
                partition_id INTEGER NOT NULL,
                partition_offset BIGINT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (consumer_group, topic, partition_id)
            )
        """)
    if not _exists(conn, "SELECT to_regclass('realtime.stream_dlq')"):
        op.execute("""
            CREATE TABLE realtime.stream_dlq (
                dlq_id UUID PRIMARY KEY,
                topic TEXT NOT NULL,
                partition_id INTEGER NOT NULL,
                partition_offset BIGINT NOT NULL,
                error TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (topic, partition_id, partition_offset)
            )
        """)
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'realtime' AND tablename = 'stream_dlq'
          AND indexname = 'ix_stream_dlq_created'
        """,
    ):
        op.execute(
            "CREATE INDEX ix_stream_dlq_created ON realtime.stream_dlq (created_at)"
        )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON realtime.stream_offsets TO edp_app"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON realtime.stream_dlq TO edp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS realtime.stream_dlq")
    op.execute("DROP TABLE IF EXISTS realtime.stream_offsets")
    op.execute("DROP SCHEMA IF EXISTS realtime")
