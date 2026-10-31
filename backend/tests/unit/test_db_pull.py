"""V1.3 T50 单测：通用 DbPullAdapter 纯逻辑（不碰真实 DB）。

覆盖（承接 T49 test_spc_pull 全部语义 + 通用化扩展）：
1. 表规格配置驱动：任意增量列名（update_time/updated_at/None）、敏感列排除；
2. SELECT 构造：敏感列不进查询列（SQL 级排除，非事后剔除）；
3. 行→SourceRecord 映射：occurred_at 取增量列值、无时间表固定纪元
   （确定性重放，禁 now()）、object_type=表名大写、source_id=str(id)、
   owner_domain 注入、source_system=适配器名（多系统并存）；
4. 增量 SQL：有增量列表带 WHERE > since；全量表无 WHERE；
5. 水位归一（naive UTC + datetime.min 哨兵降级）。
"""

from datetime import UTC, datetime

from edp_adapters.db_pull import (
    FULL_PULL_OCCURRED_AT,
    DbPullAdapter,
    DbTableSpec,
    build_fetch_sql,
    build_select_columns,
    row_to_record,
)


def _spc_specs() -> list[DbTableSpec]:
    return [
        DbTableSpec("scm_material", "update_time", "master"),
        DbTableSpec(
            "scm_supplier",
            "update_time",
            "procurement",
            ("contact_person", "contact_phone", "fax", "address"),
        ),
        DbTableSpec("scm_customer", "update_time", "master", ("credit_code",)),
        DbTableSpec("scm_product", "update_time", "master"),
        DbTableSpec("scm_bom", "update_time", "rd"),
        DbTableSpec("scm_bom_detail", "update_time", "rd"),
        DbTableSpec("scm_warehouse", "updated_at", "delivery"),
        DbTableSpec("scm_location", "updated_at", "delivery"),
        DbTableSpec("scm_process", None, "production"),
        DbTableSpec("scm_organization", None, "master"),
    ]


def test_specs_config_driven():
    """多系统同构：同一驱动，不同 name/表规格 → 不同 source_system。"""
    spc = DbPullAdapter("spc", "postgresql://a/b", _spc_specs())
    erp = DbPullAdapter("erp", "postgresql://c/d", [DbTableSpec("vendor", "updated_at", "master")])
    assert spc.name == "spc"
    assert erp.name == "erp"
    assert spc._specs[0].increment_column == "update_time"
    assert erp._specs[0].increment_column == "updated_at"


def test_sensitive_columns_excluded_in_specs():
    by_table = {s.table: s for s in _spc_specs()}
    assert "contact_person" in by_table["scm_supplier"].excluded_columns
    assert "contact_phone" in by_table["scm_supplier"].excluded_columns
    assert "fax" in by_table["scm_supplier"].excluded_columns
    assert "address" in by_table["scm_supplier"].excluded_columns
    assert "credit_code" in by_table["scm_customer"].excluded_columns


def test_build_select_columns_drops_sensitive():
    columns = ["id", "code", "name", "contact_person", "contact_phone", "address", "fax"]
    selected = build_select_columns(
        columns, ("contact_person", "contact_phone", "address", "fax")
    )
    assert selected == ['"id"', '"code"', '"name"']


def test_row_to_record_uses_increment_column_as_occurred_at():
    spec = DbTableSpec("scm_material", "update_time", "master")
    ts = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    record = row_to_record(spec, {"id": 7, "code": "M-1", "update_time": ts}, "spc")
    assert record.source_system == "spc"
    assert record.object_type == "SCM_MATERIAL"
    assert record.source_id == "7"
    assert record.occurred_at == ts
    assert record.payload["owner_domain"] == "master"
    assert record.payload["code"] == "M-1"


def test_row_to_record_source_system_is_adapter_name():
    """双系统并存：同名表不同适配器 → source_system 各自归并。"""
    spec = DbTableSpec("material", "update_time", "master")
    ts = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    row = {"id": 1, "update_time": ts}
    assert row_to_record(spec, row, "erp").source_system == "erp"
    assert row_to_record(spec, row, "mes").source_system == "mes"


def test_row_to_record_full_pull_uses_fixed_epoch():
    spec = DbTableSpec("scm_process", None, "production")
    record = row_to_record(spec, {"id": 1, "name": "SMT"}, "spc")
    assert record.occurred_at == FULL_PULL_OCCURRED_AT  # 常量纪元：确定性重放
    assert record.object_type == "SCM_PROCESS"


def test_row_to_record_naive_timestamp_assumes_utc():
    spec = DbTableSpec("scm_material", "update_time", "master")
    naive = datetime(2026, 10, 15, 8, 0)
    record = row_to_record(spec, {"id": 1, "update_time": naive}, "spc")
    assert record.occurred_at.tzinfo is not None


def test_build_fetch_sql_incremental_has_where():
    spec = DbTableSpec("scm_material", "update_time", "master")
    sql = build_fetch_sql(spec, ['"id"', '"code"'], incremental=True)
    assert "WHERE" in sql and '"update_time"' in sql and ">" in sql


def test_build_fetch_sql_full_pull_no_where():
    spec = DbTableSpec("scm_process", None, "production")
    sql = build_fetch_sql(spec, ['"id"', '"name"'], incremental=True)
    assert "WHERE" not in sql  # 全量表：增量模式也拉全集（幂等去重）


def test_naive_utc_normalization():
    from edp_adapters.db_pull import _naive_utc

    aware = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    assert _naive_utc(aware) == datetime(2026, 10, 15, 8, 0)  # naive UTC

    # 纪元哨兵（datetime.min，ingest _EPOCH）：astimezone 会 OverflowError
    # → 降级直接去 tz（不做 astimezone）
    sentinel = datetime.min.replace(tzinfo=UTC)
    assert _naive_utc(sentinel) == datetime.min

    naive = datetime(2026, 10, 15, 8, 0)
    assert _naive_utc(naive) is naive  # 已 naive 原样返回
