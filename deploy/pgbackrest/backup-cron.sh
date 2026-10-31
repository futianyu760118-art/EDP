#!/bin/sh
# EDP staging pgbackrest 每日全量备份调度（W5-T15a / EDP-031）
#
# 形态：pgbackrest repo keeper 容器内后台循环脚本（容器内无 cron 服务，
#   用 while + sleep 到每日 02:00 UTC 触发；compose 见 docker-compose.staging.yml
#   pgbackrest 服务 entrypoint）。
# 执行路径（本地拷贝模式约束）：keeper 容器无 patroni 数据目录，备份必须
#   在 patroni1 本地执行——经 psql 连 patroni1，用 COPY TO PROGRAM
#   （superuser 权限，edp_migrator）在数据库宿主上拉起
#   `pgbackrest --stanza=edp --type=full backup`（COPY 同步等待退出码）。
#   该链路 2026-09-21 实测可用（见 docs/demo/w5-drills.md T15a 段）。
#
# 用法：
#   sh /usr/local/bin/backup-cron.sh           # 循环模式（entrypoint）：睡到 02:00 UTC 全量备份，每日重复
#   sh /usr/local/bin/backup-cron.sh --once    # 单次模式：立即执行一次全量备份后退出（演练/手工补备）
#
# 环境变量（compose 注入，演示值——生产经 secret manager）：
#   BACKUP_PGHOST  备份执行库宿主（默认 patroni1）
#   BACKUP_PGUSER  触发账号（默认 edp_migrator，SUPERUSER+BYPASSRLS）
#   BACKUP_DB      库名（默认 edp）
#   PGPASSWORD     触发账号密码（默认 edp_dev，演示值）
#   BACKUP_TYPE    备份类型（默认 full；retention 由 pgbackrest.conf retention-full=2 兜底）
#
# 日志：本容器 stdout（docker logs 可查）+ patroni1 容器 /tmp/backup-cron.log。

set -u

BACKUP_PGHOST="${BACKUP_PGHOST:-patroni1}"
BACKUP_PGUSER="${BACKUP_PGUSER:-edp_migrator}"
BACKUP_DB="${BACKUP_DB:-edp}"
BACKUP_TYPE="${BACKUP_TYPE:-full}"
PGPASSWORD="${PGPASSWORD:-edp_dev}"
CRON_HOUR_UTC="${CRON_HOUR_UTC:-2}"          # 每日 02:00 UTC（容器时区 UTC；本地 UTC+8 即 10:00）
REMOTE_LOG="${REMOTE_LOG:-/tmp/backup-cron.log}"

log() { echo "[backup-cron] [$(date -u '+%Y-%m-%d %H:%M:%SZ')] $*"; }

run_backup() {
    log "backup begin: type=${BACKUP_TYPE} exec=${BACKUP_PGHOST}:local(pg1-path) via COPY TO PROGRAM"
    # COPY TO PROGRAM：psql 在 patroni1 上以服务进程用户执行命令并同步回传退出码
    if psql -h "$BACKUP_PGHOST" -U "$BACKUP_PGUSER" -d "$BACKUP_DB" -v ON_ERROR_STOP=1 \
        -c "COPY (SELECT 'backup-cron') TO PROGRAM 'pgbackrest --stanza=edp --type=${BACKUP_TYPE} backup >> ${REMOTE_LOG} 2>&1'"; then
        # keeper 循环以 root 运行，info 需显式 allow-root（只读 repo，不落文件）
        label=$(pgbackrest --stanza=edp --allow-root info 2>/dev/null | grep -E "[a-z]+ backup:" | tail -1 | sed 's/^ *//')
        log "backup OK: repo 最新备份集 -> ${label}"
        return 0
    else
        log "backup FAILED（psql/COPY 退出码非零；详见 patroni1 ${REMOTE_LOG}）"
        return 1
    fi
}

seconds_until_cron() {
    # 纯算术算距下一个 02:00 UTC 的秒数（不依赖 date -d 解析）
    now=$(date -u +%s)
    sod=$((now % 86400))
    target_sod=$((CRON_HOUR_UTC * 3600))
    if [ "$sod" -lt "$target_sod" ]; then
        echo $((target_sod - sod))
    else
        echo $((86400 - sod + target_sod))
    fi
}

if [ "${1:-}" = "--once" ]; then
    run_backup
    exit $?
fi

log "loop mode: 每日 $(printf '%02d' "$CRON_HOUR_UTC"):00 UTC 全量备份（ keeper=$(hostname) ）"
while :; do
    wait_secs=$(seconds_until_cron)
    log "next run in $((wait_secs / 3600))h$(((wait_secs % 3600) / 60))m"
    sleep "$wait_secs"
    run_backup || log "本次备份失败，等待下一调度窗口（retention 内既有备份集不受影响）"
done
