"""认证路径安全例外：api_keys 查询的 SECURITY DEFINER 函数（解决 T8 Concern #1）。

背景：platform.api_keys 启用 FORCE RLS，而认证发生在租户绑定之前——请求到达时
app.tenant_id 尚未写入，RLS 使 edp_app（NOBYPASSRLS）永远查不到任何 Key 行，
认证与租户绑定形成死锁。本迁移创建 platform.lookup_api_key(kh)：以属主身份
（迁移执行者 edp_migrator，BYPASSRLS）执行的单行查表函数，仅暴露认证所需
最小列，并内置 status='ACTIVE' 与未过期过滤。

安全性论证：
- 输入 kh 为 SHA-256 hex 摘要（64 位十六进制），非明文 Key；以哈希探测函数
  不会泄露库内存储的任何信息（输出列不含 key_hash 本体）；
- REVOKE PUBLIC + GRANT edp_app：仅应用角色可调用；
- api_keys 表的 RLS 策略保持不动——业务路径仍受租户隔离约束，本函数是
  "认证先于租户绑定"的唯一例外入口。

Revision ID: 0006_auth_definer
Revises: 0005_seed
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_auth_definer"
down_revision: str | None = "0005_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform.lookup_api_key(kh TEXT)
        RETURNS TABLE(key_id UUID, tenant_id UUID, principal_type TEXT,
                      principal_id TEXT, scopes TEXT[], tenant_status TEXT)
        LANGUAGE sql SECURITY DEFINER SET search_path = platform, public AS $$
            SELECT ak.key_id, ak.tenant_id, ak.principal_type, ak.principal_id,
                   ak.scopes, t.status
            FROM platform.api_keys ak JOIN platform.tenants t USING (tenant_id)
            WHERE ak.key_hash = kh AND ak.status = 'ACTIVE'
              AND (ak.expires_at IS NULL OR ak.expires_at > now())
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.lookup_api_key(TEXT) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.lookup_api_key(TEXT) TO edp_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform.lookup_api_key(TEXT)")
