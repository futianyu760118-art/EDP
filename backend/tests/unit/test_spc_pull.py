"""V1.3 T49 单测：SPC 主数据拉取适配器纯逻辑（不碰真实 DB）。

覆盖：
1. 表规格：10 张 C.2 表、增量列名（update_time/updated_at/无）、敏感列排除；
2. SELECT 构造：敏感列不进查询列（SQL 级排除，非事后剔除）；
3. 行→SourceRecord 映射：occurred_at 取增量列值、无时间表用固定纪元
   （确定性重放，禁 now()）、object_type=表名大写、source_id=str(id)、
   owner_domain 注入；
4. 增量 SQL：有增量列表带 WHERE > since；全量表无 WHERE。
"""

from datetime import UTC, datetime

from edp_adapters.spc_pull import (
    FULL_PULL_OCCURRED_AT,
    SpcPullAdapter,
    SpcTableSpec,
    build_fetch_sql,
    build_select_columns,
    row_to_record,
)


def test_table_specs_cover_c2_whitelist():
    tables = {spec.table for spec in SpcPullAdapter.TABLE_SPECS}
    assert tables == {
        "scm_material", "scm_supplier", "scm_customer", "scm_product",
        "scm_bom", "scm_bom_detail", "scm_warehouse", "scm_location",
        "scm_process", "scm_organization",
    }


def test_sensitive_columns_excluded_in_specs():
    by_table = {s.table: s for s in SpcPullAdapter.TABLE_SPECS}
    assert "contact_person" in by_table["scm_supplier"].excluded_columns
    assert "contact_phone" in by_table["scm_supplier"].excluded_columns
    assert "fax" in by_table["scm_supplier"].excluded_columns
    assert "address" in by_table["scm_supplier"].excluded_columns
    assert "credit_code" in by_table["scm_customer"].excluded_columns


def test_increment_column_names():
    by_table = {s.table: s for s in SpcPullAdapter.TABLE_SPECS}
    assert by_table["scm_material"].increment_column == "update_time"  # 非 updated_at
    assert by_table["scm_warehouse"].increment_column == "updated_at"
    assert by_table["scm_process"].increment_column is None  # 全量
    assert by_table["scm_organization"].increment_column is None


def test_build_select_columns_drops_sensitive():
    columns = ["id", "code", "name", "contact_person", "contact_phone", "address", "fax"]
    selected = build_select_columns(
        columns, ("contact_person", "contact_phone", "address", "fax")
    )
    assert selected == ['"id"', '"code"', '"name"']


def test_row_to_record_uses_increment_column_as_occurred_at():
    spec = SpcTableSpec(
        table="scm_material",
        increment_column="update_time",
        owner_domain="master",
        excluded_columns=(),
    )
    ts = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    record = row_to_record(spec, {"id": 7, "code": "M-1", "update_time": ts})
    assert record.source_system == "spc"
    assert record.object_type == "SCM_MATERIAL"
    assert record.source_id == "7"
    assert record.occurred_at == ts
    assert record.payload["owner_domain"] == "master"
    assert record.payload["code"] == "M-1"


def test_row_to_record_full_pull_uses_fixed_epoch():
    spec = SpcTableSpec(
        table="scm_process",
        increment_column=None,
        owner_domain="production",
        excluded_columns=(),
    )
    record = row_to_record(spec, {"id": 1, "name": "SMT"})
    assert record.occurred_at == FULL_PULL_OCCURRED_AT  # 常量纪元：确定性重放
    assert record.object_type == "SCM_PROCESS"


def test_row_to_record_naive_timestamp_assumes_utc():
    spec = SpcTableSpec(
        table="scm_material",
        increment_column="update_time",
        owner_domain="master",
        excluded_columns=(),
    )
    naive = datetime(2026, 10, 15, 8, 0)
    record = row_to_record(spec, {"id": 1, "update_time": naive})
    assert record.occurred_at.tzinfo is not None


def test_build_fetch_sql_incremental_has_where():
    spec = SpcTableSpec(
        table="scm_material",
        increment_column="update_time",
        owner_domain="master",
        excluded_columns=(),
    )
    sql = build_fetch_sql(spec, ['"id"', '"code"'], incremental=True)
    assert "WHERE" in sql and '"update_time"' in sql and ">" in sql


def test_build_fetch_sql_full_pull_no_where():
    spec = SpcTableSpec(
        table="scm_process",
        increment_column=None,
        owner_domain="production",
        excluded_columns=(),
    )
    sql = build_fetch_sql(spec, ['"id"', '"name"'], incremental=True)
    assert "WHERE" not in sql  # 全量表：增量模式也拉全集（幂等去重）


def test_adapter_meta():
    adapter = SpcPullAdapter(dsn="postgresql://x/y")
    assert adapter.name == "spc"


def test_naive_utc_normalization():
    from edp_adapters.spc_pull import _naive_utc

    aware = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    assert _naive_utc(aware) == datetime(2026, 10, 15, 8, 0)  # naive UTC

    # 纪元哨兵（datetime.min，ingest _EPOCH）：astimezone 会 OverflowError
    # → 降级直接去 tz（不做 astimezone）
    sentinel = datetime.min.replace(tzinfo=UTC)
    assert _naive_utc(sentinel) == datetime.min

    naive = datetime(2026, 10, 15, 8, 0)
    assert _naive_utc(naive) is naive  # 已 naive 原样返回
