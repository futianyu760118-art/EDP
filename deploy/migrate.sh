#!/bin/sh
# 对 compose dev 库执行 alembic 迁移（0001~0007：15 Schema 基线 + RLS + 种子数据）。
# 以 edp_migrator 角色（BYPASSRLS、属主）运行；compose 内 api/worker 均用 edp_app（受 RLS 约束）。
#
# 用法（仓库根，Git Bash / WSL / sh）：
#   ./deploy/migrate.sh
# 端口 override 场景（宿主 5432/8000 被占用）：
#   EDP_COMPOSE_OVERRIDE_FILE=deploy/docker-compose.dev.override.yml ./deploy/migrate.sh
#
# PowerShell 等效（README「常用命令」表有同款）：
#   docker compose -f deploy/docker-compose.dev.yml run --rm `
#     -e EDP_DATABASE_URL="postgresql+asyncpg://edp_migrator:edp_dev@db:5432/edp" `
#     api alembic upgrade head
set -e
cd "$(dirname "$0")/.."

COMPOSE_FILES="-f deploy/docker-compose.dev.yml"
if [ -n "$EDP_COMPOSE_OVERRIDE_FILE" ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f $EDP_COMPOSE_OVERRIDE_FILE"
fi

# --no-deps：复用已运行的 db（migrate 前先 up -d；避免 compose run 重建依赖容器触发宿主端口冲突）
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES run --rm --no-deps \
    -e EDP_DATABASE_URL="postgresql+asyncpg://edp_migrator:edp_dev@db:5432/edp" \
    api alembic upgrade head
