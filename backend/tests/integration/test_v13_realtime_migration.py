"""V1.3 T44c 集成测试：0018 迁移语义（realtime schema：stream_offsets/stream_dlq）。

覆盖：
1. realtime schema 存在，两表列集精确（位点表 / DLQ 表）；
2. stream_offsets 以 (consumer_group, topic, partition_id) 为主键，
   ON CONFLICT 位点推进可用（消费侧幂等写法）；
3. stream_dlq 可插入并读回（payload JSONB / error 文本 / 坐标齐备）；
4. edp_app 角色对两表有写权限（worker 运行角色）。

RLS 裁定（V1.3 偏差，见迁移 docstring）：realtime.* 为平台基础设施
坐标表（Kafka 位点 / 死信队列），无业务租户语义，不启用 RLS——与
outbox（事件底账，tenant_id 业务列）不同，位点/DLQ 行不承载租户数据
（DLQ payload 为解析失败的原始信封，租户未知是其常态）。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

OFFSET_COLUMNS = {
    "consumer_group",
    "topic",
    "partition_id",
    "partition_offset",
    "updated_at",
}

DLQ_COLUMNS = {
    "dlq_id",
    "topic",
    "partition_id",
    "partition_offset",
    "error",
    "payload",
    "created_at",
}


async def test_realtime_tables_exist(db_session: AsyncSession) -> None:
    """两表建成，列集精确。"""
    offset_cols = set(
        (
            await db_session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'realtime' AND table_name = 'stream_offsets'
                """)
            )
        ).scalars()
    )
    assert offset_cols == OFFSET_COLUMNS

    dlq_cols = set(
        (
            await db_session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'realtime' AND table_name = 'stream_dlq'
                """)
            )
        ).scalars()
    )
    assert dlq_cols == DLQ_COLUMNS


async def test_stream_offsets_conflict_upsert_advances(db_session: AsyncSession) -> None:
    """同 (group, topic, partition) 重复写以 ON CONFLICT 推进位点（幂等）。"""
    await db_session.execute(
        text("""
            INSERT INTO realtime.stream_offsets
                (consumer_group, topic, partition_id, partition_offset)
            VALUES ('edp-worker', 'edp.default.scm.orders', 0, 41)
            ON CONFLICT (consumer_group, topic, partition_id)
            DO UPDATE SET partition_offset = EXCLUDED.partition_offset,
                          updated_at = now()
        """)
    )
    await db_session.execute(
        text("""
            INSERT INTO realtime.stream_offsets
                (consumer_group, topic, partition_id, partition_offset)
            VALUES ('edp-worker', 'edp.default.scm.orders', 0, 42)
            ON CONFLICT (consumer_group, topic, partition_id)
            DO UPDATE SET partition_offset = EXCLUDED.partition_offset,
                          updated_at = now()
        """)
    )
    row = (
        await db_session.execute(
            text("""
                SELECT partition_offset FROM realtime.stream_offsets
                WHERE consumer_group = 'edp-worker'
                  AND topic = 'edp.default.scm.orders' AND partition_id = 0
            """)
        )
    ).scalar_one()
    assert row == 42
    await db_session.rollback()  # 造数不落库


async def test_stream_dlq_roundtrip(db_session: AsyncSession) -> None:
    """DLQ 插入/读回：坐标 + error + payload JSONB。"""
    from uuid import uuid4

    dlq_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO realtime.stream_dlq
                (dlq_id, topic, partition_id, partition_offset, error, payload)
            VALUES (:dlq_id, 'edp.default.scm.orders', 0, 7, :error,
                    CAST(:payload AS jsonb))
        """),
        {
            "dlq_id": dlq_id,
            "error": "payload.ts_ms 缺失",
            "payload": '{"payload": {"op": "c"}}',
        },
    )
    row = (
        await db_session.execute(
            text("SELECT topic, error, payload FROM realtime.stream_dlq WHERE dlq_id = :d"),
            {"d": dlq_id},
        )
    ).mappings().one()
    assert row["topic"] == "edp.default.scm.orders"
    assert row["error"] == "payload.ts_ms 缺失"
    assert row["payload"]["payload"]["op"] == "c"
    await db_session.rollback()


async def test_edp_app_can_write_realtime(app_role_engine: AsyncEngine) -> None:
    """worker 运行角色（edp_app）对两表有写权限。"""
    from uuid import uuid4

    factory = async_sessionmaker(app_role_engine)
    async with factory.begin() as sess:
        await sess.execute(
            text("""
                INSERT INTO realtime.stream_offsets
                    (consumer_group, topic, partition_id, partition_offset)
                VALUES ('probe-group', 'probe-topic', 0, 0)
                ON CONFLICT (consumer_group, topic, partition_id)
                DO UPDATE SET partition_offset = EXCLUDED.partition_offset
            """)
        )
        await sess.execute(
            text("""
                INSERT INTO realtime.stream_dlq
                    (dlq_id, topic, partition_id, partition_offset, error, payload)
                VALUES (:d, 'probe-topic', 0, 0, 'probe', '"{}"'::jsonb)
            """),
            {"d": uuid4()},
        )
    async with factory() as sess:
        n = (
            await sess.execute(
                text("SELECT count(*) FROM realtime.stream_offsets WHERE topic = 'probe-topic'")
            )
        ).scalar_one()
        assert n == 1
    async with factory.begin() as sess:
        await sess.execute(text("DELETE FROM realtime.stream_offsets WHERE topic = 'probe-topic'"))
        await sess.execute(text("DELETE FROM realtime.stream_dlq WHERE topic = 'probe-topic'"))
