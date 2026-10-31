"""evidence/decision/action/memory/management/trace/sales/delivery/rd/support/quality/finance
12 个 schema 基线（设计文档附录 A.4~A.15 逐条转录，纯 DDL、无逻辑分支）。

表数：25；RLS 表数：25（全部含 tenant_id 且标注 "-- + RLS"）。

    evidence(2):    records, links
    decision(2):    cases, records
    action(1):      actions
    memory(1):      memories
    management(4):  objectives, kpi_definitions, kpi_values, constraints
    trace(2):       traces, tool_calls
    sales(2):       orders, order_lines
    delivery(4):    inventory, purchase_orders, supplier_lead_times, capacity
    rd(2):          projects, milestones
    support(1):     tickets
    quality(2):     inspections, exceptions
    finance(2):     receivables, revenue_snapshots

适配与纪律记录：
- 审计字段（created_at/updated_at/created_by/updated_by）仅追加于标注
  "+ 审计字段" 的表；trace.tool_calls 未标注，仅业务列。
- delivery.supplier_lead_times 业务列已显式含 updated_at（交期刷新时间），
  故仅追加 created_at/created_by/updated_by，避免与审计字段 updated_at 重复。
- 跨 schema 外键（→ platform.tenants / platform.capabilities /
  master.business_objects 及主数据 / event.events）在链式顺序
  0001→0002→0003→0004 下天然满足。
- schema 间内部依赖：action.actions.case_id → decision.cases（建表 decision
  先于 action；downgrade 反序 DROP，action 先于 decision）。

Revision ID: 0004_misc
Revises: 0003_event
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_misc"
down_revision: str | None = "0003_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 建表顺序 = 附录 A.4~A.15 顺序；downgrade 按其逆序 DROP SCHEMA CASCADE。
MISC_SCHEMAS = (
    "evidence",
    "decision",
    "action",
    "memory",
    "management",
    "trace",
    "sales",
    "delivery",
    "rd",
    "support",
    "quality",
    "finance",
)

# 全部 25 表均含 tenant_id 且标注 "-- + RLS"
RLS_TABLES = (
    "evidence.records",
    "evidence.links",
    "decision.cases",
    "decision.records",
    "action.actions",
    "memory.memories",
    "management.objectives",
    "management.kpi_definitions",
    "management.kpi_values",
    "management.constraints",
    "trace.traces",
    "trace.tool_calls",
    "sales.orders",
    "sales.order_lines",
    "delivery.inventory",
    "delivery.purchase_orders",
    "delivery.supplier_lead_times",
    "delivery.capacity",
    "rd.projects",
    "rd.milestones",
    "support.tickets",
    "quality.inspections",
    "quality.exceptions",
    "finance.receivables",
    "finance.revenue_snapshots",
)

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}")


def upgrade() -> None:
    # ---- 0. schemas ----
    for schema in MISC_SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # =====================================================================
    # A.4 evidence —— 证据快照与证据链
    # =====================================================================
    # 证据记录（source_record_id 指回源系统原始记录，追溯链终点）
    op.execute("""
        CREATE TABLE evidence.records (
            evidence_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            source_system TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
            event_id UUID REFERENCES event.events(event_id),
            content_type TEXT NOT NULL DEFAULT 'application/json',
            checksum TEXT NOT NULL,
            checksum_algo TEXT NOT NULL DEFAULT 'SHA256',
            snapshot JSONB NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_evidence_object
            ON evidence.records(tenant_id, object_id, captured_at DESC)
    """)
    op.execute("CREATE INDEX idx_evidence_event ON evidence.records(tenant_id, event_id)")
    op.execute("""
        CREATE INDEX idx_evidence_source
            ON evidence.records(tenant_id, source_system, source_record_id)
    """)

    # 证据链关联（通用逆向追溯：ref_type+ref_id → evidence）
    op.execute("""
        CREATE TABLE evidence.links (
            link_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            evidence_id UUID NOT NULL REFERENCES evidence.records(evidence_id),
            ref_type TEXT NOT NULL
                CHECK (ref_type IN ('CASE','DECISION','ACTION','RESULT','EVENT','TRACE')),
            ref_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_links_ref ON evidence.links(tenant_id, ref_type, ref_id)")
    op.execute("CREATE INDEX idx_links_evidence ON evidence.links(tenant_id, evidence_id)")

    # =====================================================================
    # A.5 decision —— 决策案例与记录（须先于 action 建，action 外键指向 cases）
    # =====================================================================
    # 决策案例
    op.execute("""
        CREATE TABLE decision.cases (
            case_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            case_no TEXT,
            question TEXT NOT NULL,
            context JSONB NOT NULL DEFAULT '{}',
            options JSONB NOT NULL DEFAULT '[]',
            risk_level TEXT CHECK (risk_level IN ('P0','P1','P2','P3')),
            source_type TEXT,
            source_id TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN','DECIDED','CANCELLED')),
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_case_no
            ON decision.cases(tenant_id, case_no)
            WHERE case_no IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX idx_cases_status
            ON decision.cases(tenant_id, status, risk_level, created_at DESC)
    """)

    # 决策记录
    op.execute("""
        CREATE TABLE decision.records (
            decision_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            case_id UUID NOT NULL REFERENCES decision.cases(case_id),
            chosen_option TEXT NOT NULL,
            decision_type TEXT NOT NULL CHECK (decision_type IN ('HUMAN','AI_SUGGESTED')),
            decided_by TEXT NOT NULL,
            decision_time TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_decision_records_case
            ON decision.records(tenant_id, case_id, decision_time)
    """)

    # =====================================================================
    # A.6 action —— 行动任务状态机
    # =====================================================================
    op.execute("""
        CREATE TABLE action.actions (
            action_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            case_id UUID REFERENCES decision.cases(case_id),
            title TEXT NOT NULL,
            description TEXT,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (status IN
                ('PROPOSED','ASSIGNED','ACCEPTED','APPROVED','EXECUTING',
                 'COMPLETED','VERIFIED','CANCELLED','REJECTED')),
            owner TEXT,
            owner_role TEXT,
            due_date TIMESTAMPTZ,
            completion_time TIMESTAMPTZ,
            verified_at TIMESTAMPTZ,
            verified_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_actions_status ON action.actions(tenant_id, status, due_date)")
    op.execute("CREATE INDEX idx_actions_case ON action.actions(tenant_id, case_id)")
    op.execute("CREATE INDEX idx_actions_owner ON action.actions(tenant_id, owner, status)")

    # =====================================================================
    # A.7 memory —— 学习记忆
    # =====================================================================
    # 记忆（候选 → 评审 → Approved/Rejected；评审逻辑 W6 由中枢接管）
    op.execute("""
        CREATE TABLE memory.memories (
            memory_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            capability_id UUID REFERENCES platform.capabilities(capability_id),
            source_type TEXT NOT NULL,
            source_id UUID NOT NULL,
            content JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'CANDIDATE'
                CHECK (status IN ('CANDIDATE','APPROVED','REJECTED')),
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            review_comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_memories_status
            ON memory.memories(tenant_id, status, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_memories_capability
            ON memory.memories(tenant_id, capability_id, status)
    """)

    # =====================================================================
    # A.8 management —— 经营目标与 KPI
    # =====================================================================
    # 经营目标
    op.execute("""
        CREATE TABLE management.objectives (
            objective_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            title TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            target_value NUMERIC(18,4) NOT NULL,
            current_value NUMERIC(18,4),
            period TEXT NOT NULL,
            owner TEXT,
            due_date TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','ACHIEVED','MISSED','CANCELLED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_objectives_tenant
            ON management.objectives(tenant_id, period, status)
    """)

    # KPI 定义（EBMS 报表预聚合来源）
    op.execute("""
        CREATE TABLE management.kpi_definitions (
            kpi_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            formula TEXT,
            unit TEXT,
            refresh_cycle TEXT NOT NULL DEFAULT 'DAILY',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_kpi_code ON management.kpi_definitions(tenant_id, code)")

    # KPI 数值
    op.execute("""
        CREATE TABLE management.kpi_values (
            value_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            kpi_id UUID NOT NULL REFERENCES management.kpi_definitions(kpi_id),
            period TEXT NOT NULL,
            value NUMERIC(18,4) NOT NULL,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            source TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_kpi_value
            ON management.kpi_values(tenant_id, kpi_id, period)
    """)

    # 硬性约束（与 Guard 策略联动）
    op.execute("""
        CREATE TABLE management.constraints (
            constraint_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            config JSONB NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('BLOCK','WARN','INFO')),
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)

    # =====================================================================
    # A.9 trace —— Agent 执行日志（高频写入，独立保留期与归档策略）
    # =====================================================================
    # 执行轨迹
    op.execute("""
        CREATE TABLE trace.traces (
            trace_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            agent_id TEXT NOT NULL,
            task_id TEXT,
            capability_id UUID REFERENCES platform.capabilities(capability_id),
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'RUNNING'
                CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','TIMEOUT','ABORTED')),
            input_context JSONB,
            llm_prompt TEXT,
            llm_response TEXT,
            output_structured JSONB,
            token_usage JSONB,
            evidence_refs UUID[] NOT NULL DEFAULT '{}',
            error JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_traces_agent
            ON trace.traces(tenant_id, agent_id, started_at DESC)
    """)
    op.execute("CREATE INDEX idx_traces_task ON trace.traces(tenant_id, task_id)")
    op.execute("""
        CREATE INDEX idx_traces_capability
            ON trace.traces(tenant_id, capability_id, started_at DESC)
    """)

    # 工具调用明细（三层留痕之执行轨迹层；A.9 未标注审计字段，仅业务列）
    op.execute("""
        CREATE TABLE trace.tool_calls (
            call_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            trace_id UUID NOT NULL REFERENCES trace.traces(trace_id),
            seq INT NOT NULL,
            tool_name TEXT NOT NULL,
            input JSONB,
            output JSONB,
            status_code INT,
            error JSONB,
            latency_ms INT,
            called_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_tool_calls_trace ON trace.tool_calls(tenant_id, trace_id, seq)")

    # =====================================================================
    # A.10 sales —— 销售域快照
    # =====================================================================
    # 订单快照（源：ERP，W2 起）
    op.execute("""
        CREATE TABLE sales.orders (
            order_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            order_no TEXT NOT NULL,
            customer_id UUID REFERENCES master.customers(customer_id),
            amount NUMERIC(18,4),
            currency TEXT NOT NULL DEFAULT 'CNY',
            status TEXT NOT NULL,
            order_date TIMESTAMPTZ,
            delivery_date TIMESTAMPTZ,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_sales_order_no ON sales.orders(tenant_id, order_no)")
    op.execute("""
        CREATE INDEX idx_sales_orders_customer
            ON sales.orders(tenant_id, customer_id, snapshot_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_sales_orders_status
            ON sales.orders(tenant_id, status, delivery_date)
    """)

    # 订单行
    op.execute("""
        CREATE TABLE sales.order_lines (
            line_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            order_id UUID NOT NULL REFERENCES sales.orders(order_id),
            product_id UUID REFERENCES master.products(product_id),
            material_id UUID REFERENCES master.materials(material_id),
            quantity NUMERIC(18,4) NOT NULL,
            unit_price NUMERIC(18,4),
            amount NUMERIC(18,4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_order_lines_order ON sales.order_lines(tenant_id, order_id)")

    # =====================================================================
    # A.11 delivery —— 交付域快照
    # =====================================================================
    # 库存快照
    op.execute("""
        CREATE TABLE delivery.inventory (
            inv_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            material_id UUID NOT NULL REFERENCES master.materials(material_id),
            warehouse TEXT,
            quantity_available NUMERIC(18,4) NOT NULL DEFAULT 0,
            quantity_reserved NUMERIC(18,4) NOT NULL DEFAULT 0,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_inventory_material
            ON delivery.inventory(tenant_id, material_id, snapshot_at DESC)
    """)

    # 采购单快照
    op.execute("""
        CREATE TABLE delivery.purchase_orders (
            po_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            po_no TEXT NOT NULL,
            supplier_id UUID REFERENCES master.suppliers(supplier_id),
            material_id UUID REFERENCES master.materials(material_id),
            quantity NUMERIC(18,4) NOT NULL,
            expected_date TIMESTAMPTZ,
            status TEXT NOT NULL,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_delivery_po_no
            ON delivery.purchase_orders(tenant_id, po_no)
    """)
    op.execute("""
        CREATE INDEX idx_po_material_status
            ON delivery.purchase_orders(tenant_id, material_id, status, expected_date)
    """)

    # 供应商交期（OrderRisk 能力关键输入）
    # 注：业务列已显式含 updated_at，故仅追加 created_at/created_by/updated_by
    op.execute("""
        CREATE TABLE delivery.supplier_lead_times (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            supplier_id UUID NOT NULL REFERENCES master.suppliers(supplier_id),
            material_id UUID REFERENCES master.materials(material_id),
            lead_time_days INT NOT NULL CHECK (lead_time_days >= 0),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_lead_time
            ON delivery.supplier_lead_times(tenant_id, supplier_id, material_id)
    """)

    # 产能快照（W3 按能力需要启用）
    op.execute("""
        CREATE TABLE delivery.capacity (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            product_line TEXT NOT NULL,
            period TEXT NOT NULL,
            capacity_qty NUMERIC(18,4) NOT NULL,
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_capacity
            ON delivery.capacity(tenant_id, product_line, period, snapshot_at)
    """)

    # =====================================================================
    # A.12 rd —— 研发域快照
    # =====================================================================
    # 研发项目
    op.execute("""
        CREATE TABLE rd.projects (
            project_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            project_no TEXT NOT NULL,
            product_id UUID REFERENCES master.products(product_id),
            status TEXT NOT NULL,
            stage TEXT,
            readiness_level TEXT,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_rd_project_no ON rd.projects(tenant_id, project_no)")

    # 项目里程碑
    op.execute("""
        CREATE TABLE rd.milestones (
            milestone_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            project_id UUID NOT NULL REFERENCES rd.projects(project_id),
            name TEXT NOT NULL,
            due_date TIMESTAMPTZ,
            actual_date TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','IN_PROGRESS','DONE','OVERDUE')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_milestones_project
            ON rd.milestones(tenant_id, project_id, due_date)
    """)

    # =====================================================================
    # A.13 support —— 支持域快照
    # =====================================================================
    # 工单
    op.execute("""
        CREATE TABLE support.tickets (
            ticket_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            ticket_no TEXT NOT NULL,
            customer_id UUID REFERENCES master.customers(customer_id),
            type TEXT,
            severity TEXT CHECK (severity IN ('P0','P1','P2','P3')),
            status TEXT NOT NULL,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_support_ticket_no ON support.tickets(tenant_id, ticket_no)")

    # =====================================================================
    # A.14 quality —— 品控域快照
    # =====================================================================
    # 质检记录
    op.execute("""
        CREATE TABLE quality.inspections (
            inspection_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            inspection_no TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id UUID NOT NULL,
            result TEXT NOT NULL CHECK (result IN ('PASS','FAIL','CONDITIONAL')),
            defect_qty NUMERIC(18,4),
            inspected_at TIMESTAMPTZ,
            snapshot_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_inspection_no
            ON quality.inspections(tenant_id, inspection_no)
    """)

    # 质量异常
    op.execute("""
        CREATE TABLE quality.exceptions (
            exception_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            source TEXT NOT NULL,
            severity TEXT CHECK (severity IN ('P0','P1','P2','P3')),
            status TEXT NOT NULL DEFAULT 'OPEN',
            description TEXT NOT NULL,
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_quality_exceptions
            ON quality.exceptions(tenant_id, status, severity)
    """)

    # =====================================================================
    # A.15 finance —— 财务域快照
    # =====================================================================
    # 应收
    op.execute("""
        CREATE TABLE finance.receivables (
            ar_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            customer_id UUID REFERENCES master.customers(customer_id),
            amount NUMERIC(18,4) NOT NULL,
            due_date TIMESTAMPTZ,
            overdue_days INT NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_ar_customer
            ON finance.receivables(tenant_id, customer_id, due_date)
    """)

    # 收入快照（预聚合）
    op.execute("""
        CREATE TABLE finance.revenue_snapshots (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            period TEXT NOT NULL,
            revenue NUMERIC(18,4) NOT NULL,
            cost NUMERIC(18,4),
            gross_margin NUMERIC(10,4),
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_revenue_period
            ON finance.revenue_snapshots(tenant_id, period, snapshot_at)
    """)

    # ---- RLS：ENABLE + FORCE + tenant_isolation（全部 25 表） ----
    for table in RLS_TABLES:
        _enable_rls(table)

    # ---- 尾部统一授权（逐 schema） ----
    for schema in MISC_SCHEMAS:
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO edp_app")
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO edp_app"
        )
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO edp_app")


def downgrade() -> None:
    # 逆序清理：策略 → schema（CASCADE 连带全部表/索引）。
    # 顺序 = 建表顺序的逆序：依赖方先删（action 先于 decision），被依赖的后删。
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")

    for schema in reversed(MISC_SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
