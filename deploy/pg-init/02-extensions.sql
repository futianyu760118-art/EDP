-- pg_stat_statements 扩展（W6 T3 / EDP-033 压测线供给）：压测 top SQL
-- 读数（mean_exec_time DESC）与慢查询治理的数据源。超级用户侧建立，
-- edp_migrator/edp_app 不涉及权限变更。
-- 注意：docker-entrypoint-initdb.d 仅在数据卷**首次初始化**时执行——
-- 已有 pgdata 卷需手动执行一次（或 down -v 重建卷）：
--   docker compose -f deploy/docker-compose.dev.yml exec db \
--     psql -U edp_migrator -d edp -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements;'
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
