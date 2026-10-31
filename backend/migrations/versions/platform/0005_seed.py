"""platform 种子数据（T5：租户 / 五角色 / 权限矩阵 / 初始用户 / API Key）。

幂等规则：全部"先查存在即跳过"（module 级 _exists helper），重复 upgrade 不产生
重复行；downgrade 仅按固定 UUID / 用户名 / slug 精确删除本次种子，不动其他数据。

种子清单与验证基线：
- 租户 default（slug='default', name='默认租户', plan='STANDARD', status='ACTIVE'）
  + platform.tenant_quotas 默认行（其余列取 0001 建表默认值）；
- 五角色（中文名 = 设计文档 13.4.4）：PLATFORM_ADMIN=平台运营 / ADMIN=工作空间管理员
  / MANAGER=数据管理员·业务负责人 / ANALYST=审计员·操作员 / SERVICE=服务主体；
- permissions 12 项（resource/action 拆列）：registry/event/evidence 的 read+write、
  decision:read+decide、action:read+execute、audit:read、tenant:admin；
- role_permissions 矩阵共 45 行：PLATFORM_ADMIN=12（全部）；ADMIN=11（除
  tenant:admin）；MANAGER=11（全部 read + decision:decide + action:execute +
  registry/event/evidence write）；ANALYST=6（全部 read，含 audit:read）；
  SERVICE=5（registry:read/write + event:read/write + evidence:read）；
- 用户 3（principal_type='HUMAN', status='ACTIVE'）：admin（is_platform_admin=true，
  display_name='平台管理员'）、manager1（'王管理'）、analyst1（'李审计'）；
  密码 argon2id 哈希，ENV EDP_ADMIN_INITIAL_PASSWORD / EDP_SEED_PASSWORD；
- tenant_members 3（status='ACTIVE'）：admin→['ADMIN']（平台运营经
  users.is_platform_admin 表达）、manager1→['MANAGER']、analyst1→['ANALYST']；
- API Key 1：principal_type='SERVICE', principal_id='agent-hub'，scopes=
  ['readonly','write:event','write:registry']，key_hash=sha256(ENV EDP_DEV_API_KEY)。

安全须知：缺省密码 'Admin@123!' 与缺省 Key 'edp-dev-agent-hub-key' 仅限 dev/CI；
生产环境必须设置环境变量 EDP_ADMIN_INITIAL_PASSWORD / EDP_SEED_PASSWORD /
EDP_DEV_API_KEY，禁止依赖缺省值。

主键 UUID 均由 uuid5(NIL, ...) 固定命名种子生成，便于测试与 downgrade 精确引用。

Revision ID: 0005_seed
Revises: 0004_misc
Create Date: 2026-09-14
"""

import hashlib
import os
from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Text, Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

# uuid.NIL 于 Python 3.14 才加入标准库；3.12 用 UUID(int=0) 等价表达 nil UUID
NIL = UUID(int=0)

# revision identifiers, used by Alembic.
revision: str = "0005_seed"
down_revision: str | None = "0004_misc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ADMIN_PASSWORD = "Admin@123!"
DEFAULT_SEED_PASSWORD = "Admin@123!"
DEFAULT_DEV_API_KEY = "edp-dev-agent-hub-key"

# ---- 种子常量 ----

ROLES: tuple[tuple[str, str], ...] = (
    ("PLATFORM_ADMIN", "平台运营"),
    ("ADMIN", "工作空间管理员"),
    ("MANAGER", "数据管理员·业务负责人"),
    ("ANALYST", "审计员·操作员"),
    ("SERVICE", "服务主体"),
)

PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("registry:read", "registry", "read"),
    ("registry:write", "registry", "write"),
    ("event:read", "event", "read"),
    ("event:write", "event", "write"),
    ("evidence:read", "evidence", "read"),
    ("evidence:write", "evidence", "write"),
    ("decision:read", "decision", "read"),
    ("decision:decide", "decision", "decide"),
    ("action:read", "action", "read"),
    ("action:execute", "action", "execute"),
    ("audit:read", "audit", "read"),
    ("tenant:admin", "tenant", "admin"),
)

_ALL = tuple(code for code, _, _ in PERMISSIONS)
_READS = tuple(code for code, _, _ in PERMISSIONS if code.endswith(":read"))
_STEWARD_WRITES = ("registry:write", "event:write", "evidence:write")

ROLE_PERMISSION_CODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PLATFORM_ADMIN", _ALL),
    ("ADMIN", tuple(code for code in _ALL if code != "tenant:admin")),
    ("MANAGER", (*_READS, "decision:decide", "action:execute", *_STEWARD_WRITES)),
    ("ANALYST", _READS),
    ("SERVICE", ("registry:read", "registry:write", "event:read", "event:write", "evidence:read")),
)

# ---- 固定 UUID（uuid5 命名种子） ----

TENANT_ID = uuid5(NIL, "edp-default-tenant")
ADMIN_USER_ID = uuid5(NIL, "edp-user-admin")
MANAGER1_USER_ID = uuid5(NIL, "edp-user-manager1")
ANALYST1_USER_ID = uuid5(NIL, "edp-user-analyst1")
API_KEY_ID = uuid5(NIL, "edp-apikey-agent-hub")
ROLE_IDS = {code: uuid5(NIL, f"edp-role-{code}") for code, _ in ROLES}
PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in PERMISSIONS}
MEMBER_IDS = {
    "admin": uuid5(NIL, "edp-member-admin"),
    "manager1": uuid5(NIL, "edp-member-manager1"),
    "analyst1": uuid5(NIL, "edp-member-analyst1"),
}
SEED_USERNAMES = ("admin", "manager1", "analyst1")


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def _exec(conn, sql: str, params: dict | None = None, array_params: Sequence[tuple] = ()) -> None:
    """执行语句；array_params = (参数名, 数组类型) 对（asyncpg 需显式数组类型）。"""
    stmt = text(sql)
    for name, type_ in array_params:
        stmt = stmt.bindparams(bindparam(name, type_=ARRAY(type_)))
    conn.execute(stmt, params or {})


def upgrade() -> None:
    from argon2 import PasswordHasher

    conn = op.get_bind()
    hasher = PasswordHasher()  # argon2id（默认参数）

    # ---- 1. 租户 + 配额 ----
    if not _exists(conn, "SELECT tenant_id FROM platform.tenants WHERE slug = 'default'"):
        _exec(
            conn,
            """
            INSERT INTO platform.tenants (tenant_id, slug, name, plan, status)
            VALUES (:tenant_id, 'default', '默认租户', 'STANDARD', 'ACTIVE')
            """,
            {"tenant_id": TENANT_ID},
        )
    tenant_id = conn.execute(
        text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
    ).scalar()
    if not _exists(
        conn, "SELECT tenant_id FROM platform.tenant_quotas WHERE tenant_id = :t", {"t": tenant_id}
    ):
        _exec(conn, "INSERT INTO platform.tenant_quotas (tenant_id) VALUES (:t)", {"t": tenant_id})

    # ---- 2. 角色 ----
    for code, name in ROLES:
        if _exists(conn, "SELECT role_id FROM platform.roles WHERE code = :code", {"code": code}):
            continue
        _exec(
            conn,
            "INSERT INTO platform.roles (role_id, code, name) VALUES (:role_id, :code, :name)",
            {"role_id": ROLE_IDS[code], "code": code, "name": name},
        )

    # ---- 3. 权限 ----
    for code, resource, action in PERMISSIONS:
        if _exists(conn, "SELECT permission_id FROM platform.permissions WHERE code = :code",
                   {"code": code}):
            continue
        _exec(
            conn,
            """
            INSERT INTO platform.permissions (permission_id, code, resource, action)
            VALUES (:permission_id, :code, :resource, :action)
            """,
            {"permission_id": PERMISSION_IDS[code], "code": code,
             "resource": resource, "action": action},
        )

    # ---- 4. 角色-权限矩阵（45 行） ----
    for role_code, perm_codes in ROLE_PERMISSION_CODES:
        for perm_code in perm_codes:
            if _exists(
                conn,
                """
                SELECT role_id FROM platform.role_permissions
                WHERE role_id = :r AND permission_id = :p
                """,
                {"r": ROLE_IDS[role_code], "p": PERMISSION_IDS[perm_code]},
            ):
                continue
            _exec(
                conn,
                """
                INSERT INTO platform.role_permissions (role_id, permission_id)
                VALUES (:r, :p)
                """,
                {"r": ROLE_IDS[role_code], "p": PERMISSION_IDS[perm_code]},
            )

    # ---- 5. 用户（argon2id） ----
    admin_password = os.environ.get("EDP_ADMIN_INITIAL_PASSWORD") or DEFAULT_ADMIN_PASSWORD
    seed_password = os.environ.get("EDP_SEED_PASSWORD") or DEFAULT_SEED_PASSWORD
    seed_users = (
        (ADMIN_USER_ID, "admin", "admin@edp.local", "平台管理员", True, admin_password),
        (MANAGER1_USER_ID, "manager1", "manager1@edp.local", "王管理", False, seed_password),
        (ANALYST1_USER_ID, "analyst1", "analyst1@edp.local", "李审计", False, seed_password),
    )
    for user_id, username, email, display_name, is_platform_admin, password in seed_users:
        if _exists(
            conn,
            "SELECT user_id FROM platform.users WHERE tenant_id = :t AND username = :u",
            {"t": tenant_id, "u": username},
        ):
            continue
        _exec(
            conn,
            """
            INSERT INTO platform.users
                (user_id, tenant_id, username, email, password_hash, display_name,
                 principal_type, is_platform_admin, status)
            VALUES
                (:user_id, :tenant_id, :username, :email, :password_hash, :display_name,
                 'HUMAN', :is_platform_admin, 'ACTIVE')
            """,
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "username": username,
                "email": email,
                "password_hash": hasher.hash(password),
                "display_name": display_name,
                "is_platform_admin": is_platform_admin,
            },
        )

    # ---- 6. 租户成员（角色绑定） ----
    member_roles = (("admin", ("ADMIN",)), ("manager1", ("MANAGER",)), ("analyst1", ("ANALYST",)))
    for username, roles in member_roles:
        user_id = conn.execute(
            text("SELECT user_id FROM platform.users WHERE tenant_id = :t AND username = :u"),
            {"t": tenant_id, "u": username},
        ).scalar()
        if _exists(
            conn,
            "SELECT member_id FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u",
            {"t": tenant_id, "u": user_id},
        ):
            continue
        _exec(
            conn,
            """
            INSERT INTO platform.tenant_members
                (member_id, tenant_id, user_id, member_roles, status)
            VALUES
                (:member_id, :tenant_id, :user_id, :member_roles, 'ACTIVE')
            """,
            {
                "member_id": MEMBER_IDS[username],
                "tenant_id": tenant_id,
                "user_id": user_id,
                "member_roles": list(roles),
            },
            array_params=(("member_roles", Text),),
        )

    # ---- 7. API Key（服务主体 agent-hub） ----
    raw_api_key = os.environ.get("EDP_DEV_API_KEY") or DEFAULT_DEV_API_KEY
    key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()
    if not _exists(
        conn,
        """
        SELECT key_id FROM platform.api_keys
        WHERE tenant_id = :t AND principal_type = 'SERVICE' AND principal_id = 'agent-hub'
        """,
        {"t": tenant_id},
    ):
        _exec(
            conn,
            """
            INSERT INTO platform.api_keys
                (key_id, key_hash, tenant_id, principal_type, principal_id, scopes, status)
            VALUES
                (:key_id, :key_hash, :tenant_id, 'SERVICE', 'agent-hub', :scopes, 'ACTIVE')
            """,
            {
                "key_id": API_KEY_ID,
                "key_hash": key_hash,
                "tenant_id": tenant_id,
                "scopes": ["readonly", "write:event", "write:registry"],
            },
            array_params=(("scopes", Text),),
        )


def downgrade() -> None:
    """逆序精确删除本次种子（固定 UUID / 用户名 / slug），不影响其他数据。"""
    conn = op.get_bind()
    _exec(
        conn,
        "DELETE FROM platform.role_permissions WHERE role_id = ANY(:ids)",
        {"ids": list(ROLE_IDS.values())},
        array_params=(("ids", Uuid),),
    )
    _exec(
        conn,
        "DELETE FROM platform.api_keys WHERE key_id = :key_id",
        {"key_id": API_KEY_ID},
    )
    _exec(
        conn,
        "DELETE FROM platform.tenant_members WHERE member_id = ANY(:ids)",
        {"ids": list(MEMBER_IDS.values())},
        array_params=(("ids", Uuid),),
    )
    _exec(
        conn,
        "DELETE FROM platform.users WHERE user_id = ANY(:ids)",
        {"ids": [ADMIN_USER_ID, MANAGER1_USER_ID, ANALYST1_USER_ID]},
        array_params=(("ids", Uuid),),
    )
    _exec(
        conn,
        "DELETE FROM platform.permissions WHERE permission_id = ANY(:ids)",
        {"ids": list(PERMISSION_IDS.values())},
        array_params=(("ids", Uuid),),
    )
    _exec(
        conn,
        "DELETE FROM platform.roles WHERE role_id = ANY(:ids)",
        {"ids": list(ROLE_IDS.values())},
        array_params=(("ids", Uuid),),
    )
    # 租户最后删（先删其配额；按 slug 精确定位）
    _exec(
        conn,
        """
        DELETE FROM platform.tenant_quotas
        WHERE tenant_id = (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')
        """,
    )
    _exec(conn, "DELETE FROM platform.tenants WHERE slug = 'default'")
