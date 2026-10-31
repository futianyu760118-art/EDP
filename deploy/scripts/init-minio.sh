#!/bin/sh
# EDP staging MinIO bucket 初始化（W5-T14 / EDP-031 前置）
# 形态：compose 一次性 job（restart: no，depends_on minio healthy）内执行；
#       幂等（mb --ignore-existing），可随栈反复 up。凭据经环境变量注入（与 minio 服务同值）。
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD required}"

MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"

# 兜底等待 minio ready（depends_on healthy 已保证；重试 ~60s 防 race）
i=0
until mc alias set local "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: minio not ready after ${i} retries: $MINIO_ENDPOINT" >&2
    exit 1
  fi
  sleep 2
done

mc mb local/edp-backups --ignore-existing
mc ls local/
