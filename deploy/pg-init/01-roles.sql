-- dev/CI 初始化：edp_migrator 由容器 POSTGRES_USER 环境变量创建；
-- 此处创建受 RLS 约束的应用登录角色（prod 环境角色由运维创建，见 contracts/README.md）
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'edp_app') THEN
        CREATE ROLE edp_app LOGIN PASSWORD 'edp_app';
    END IF;
END
$$;
