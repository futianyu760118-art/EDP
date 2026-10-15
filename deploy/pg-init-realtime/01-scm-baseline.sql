-- V1.3 T42/T43：模拟供应链源库初始化（仅 scm-db 首次建库执行）
-- 真实对端条件清单见 docs/V1.3_对端条件清单.md（wal_level/publication/
-- 只读账号/主键基线——本目录为 dev 等价物）。

CREATE TABLE IF NOT EXISTS orders (
    order_no   TEXT PRIMARY KEY,
    amount     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'OPEN',
    owner_domain TEXT NOT NULL DEFAULT 'sales',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory (
    warehouse_code TEXT NOT NULL,
    sku_code       TEXT NOT NULL,
    qty            INTEGER NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (warehouse_code, sku_code)
);

-- CDC 只读账号（密码 dev 专用；真实环境由 DBA 最小化授权）
CREATE ROLE scm_cdc LOGIN PASSWORD 'scm_cdc_dev';
GRANT CONNECT ON DATABASE scm TO scm_cdc;
GRANT USAGE ON SCHEMA public TO scm_cdc;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO scm_cdc;

-- 逻辑复制 publication（Debezium 快照 + 流式读取）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication WHERE pubname = 'scm_pub'
    ) THEN
        CREATE PUBLICATION scm_pub FOR TABLE orders, inventory;
    END IF;
END $$;

-- 种子行（快照链路立即可验）
INSERT INTO orders (order_no, amount, status)
VALUES ('SO-DEV-001', 100.00, 'OPEN'), ('SO-DEV-002', 250.50, 'OPEN')
ON CONFLICT (order_no) DO NOTHING;

INSERT INTO inventory (warehouse_code, sku_code, qty)
VALUES ('WH-01', 'SKU-001', 42)
ON CONFLICT (warehouse_code, sku_code) DO NOTHING;
