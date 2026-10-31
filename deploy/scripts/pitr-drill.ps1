# EDP staging PITR 整库恢复演练（W5-T15b / EDP-027）
#
# 用法（仓库根目录；bash/终端超时给足 ≥5min）：
#   powershell -File deploy/scripts/pitr-drill.ps1
#
# 流程：
#   [1/7] 前置：patroni1 可用 + S3 repo 存在早于当前时刻的备份集
#   [2/7] 标记行写入：event.events 插 pitr-marker-<ts>（edp_migrator BYPASSRLS，DB 时钟记 occurred_at）
#   [3/7] WAL 推进①：pg_switch_wal + 轮询 pg_stat_archiver（marker 段落 S3）
#   [4/7] 目标时点 = occurred_at + 60s；睡过目标点后插 end-marker（commit ts > target，
#         保证 recovery 有可停的提交点；该行按时间点语义【不应】被重放 -> 负向断言）+ WAL 推进②
#   [5/7] 恢复（RTO 计时从冷启动起）：一次性容器（patroni 同镜像，宿主 15433，不走 patroni——
#         原生 postgres 单实例）：pgbackrest --type=time restore + recovery-target-action=promote
#   [6/7] 断言：15432 可连 + marker 存在 + end-marker 不存在 + platform.tenants 与主库一致
#   [7/7] 读数（RTO/RPO）输出 + 清理恢复容器 + 删主库两根 marker 行
#
# 不影响主栈：恢复走独立容器/端口，不动 patroni 数据卷；失败如实退出（读数由人工归档）。
# PowerShell 5.1 兼容：无三元/??/管道链语法。

# 恢复实例宿主端口：任务口径 15432，实测被常驻 edp-dev-db-1（dev 栈 db，Up 5 days）占用——
# 不动 dev 栈，演练实例改 15433（语义不变：独立端口 + 宿主 TCP 可连断言）。
param([int]$RestoreHostPort = 15433)

$ErrorActionPreference = "Stop"

# ---- 路径与常量 ----
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # deploy/scripts -> 仓库根
$ComposeFile = "deploy/docker-compose.staging.yml"
$ConfPath = Join-Path $RepoRoot "deploy/pgbackrest/pgbackrest.conf"
$RestoreContainer = "edp-pitr-restore"
$RestoreNetwork = "edp-staging_default"
$PatroniImage = "edp-staging/patroni:pg16"
$TargetDelaySec = 60          # 目标时点 = marker 后 60s

function Invoke-Native {
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"
    $out = & $CmdArgs[0] $CmdArgs[1..($CmdArgs.Length - 1)] 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return @{ Out = $out; Exit = $code }
}

function Invoke-PrimarySql {
    # 主库（patroni1）以 edp_migrator over TCP 执行 SQL（BYPASSRLS；exec 默认 root 不走 peer）
    param([string]$Sql)
    $r = Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T",
        "-e", "PGPASSWORD=edp_dev", "patroni1",
        "psql", "-h", "patroni1", "-U", "edp_migrator", "-d", "edp", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", $Sql)
    if ($r.Exit -ne 0) { throw "主库 SQL 失败：$Sql`n$($r.Out)" }
    return $r.Out.Trim()
}

function Invoke-RestoreSql {
    # 恢复实例（容器内 127.0.0.1:5432）以 edp_migrator over TCP 执行 SQL
    param([string]$Sql)
    $r = Invoke-Native @("docker", "exec",
        "-e", "PGPASSWORD=edp_dev", $RestoreContainer,
        "psql", "-h", "127.0.0.1", "-p", "5432", "-U", "edp_migrator", "-d", "edp", "-t", "-A", "-c", $Sql)
    return @{ Out = $r.Out.Trim(); Exit = $r.Exit }
}

function ConvertFrom-PgTimestamp {
    # PG 输出偏移 +00 无冒号，.NET 不识别——规范成 +00:00 再解析
    param([string]$Ts)
    $norm = $Ts.Trim() -replace "([+-]\d{2})$", "`$1:00"
    return [DateTimeOffset]::Parse($norm, [Globalization.CultureInfo]::InvariantCulture)
}

function Wait-ArchiveAdvance {
    # 等 pg_stat_archiver.last_archived_wal 变化（switch 关闭的段已完成 archive-push 到 S3）
    param([string]$BeforeWal, [int]$Attempts = 30, [int]$IntervalSec = 2)
    for ($i = 1; $i -le $Attempts; $i++) {
        $cur = Invoke-PrimarySql "SELECT last_archived_wal FROM pg_stat_archiver"
        if ($cur -and $cur -ne $BeforeWal) { return $cur }
        Start-Sleep -Seconds $IntervalSec
    }
    throw "WAL 归档在 $($Attempts * $IntervalSec)s 内未推进（before=$BeforeWal）"
}

Push-Location $RepoRoot
$rtoSeconds = -1; $markerId = ""; $markerLabel = ""; $endMarkerLabel = ""
try {
    Write-Host "== [1/7] 前置检查 =="
    $tenantId = Invoke-PrimarySql "SELECT tenant_id FROM platform.tenants WHERE slug = 'default'"
    if (-not $tenantId) { throw "default 租户不存在" }
    $info = Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T", "-u", "postgres", "pgbackrest",
        "pgbackrest", "--stanza=edp", "info")
    if ($info.Exit -ne 0 -or $info.Out -notmatch "full backup:") { throw "S3 repo 无全量备份集（pgbackrest info）" }
    Write-Host "  主库可达（default 租户 $tenantId）+ repo 备份集在位"

    Write-Host "== [2/7] 标记行写入（event.events，DB 时钟）=="
    $markerLabel = "pitr-marker-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
    # event.events.object_id 有 FK -> master.business_objects：marker 专用 object（演练后随 marker 一并清理）
    $markerSql = @"
WITH obj AS (
  INSERT INTO master.business_objects (object_id, tenant_id, object_type, owner_domain, source_system, source_id, attributes)
  VALUES (gen_random_uuid(), '$tenantId', 'pitr-marker', 'w5', 'w5-drill', '$markerLabel', jsonb_build_object('purpose','pitr-drill'))
  RETURNING object_id)
INSERT INTO event.events (event_id, tenant_id, event_type, object_id, source_system,
  occurred_at, data, created_at, updated_at)
SELECT gen_random_uuid(), '$tenantId', 'platform.pitr-marker', obj.object_id, 'w5-drill',
  clock_timestamp(), jsonb_build_object('marker','$markerLabel','phase','start'),
  clock_timestamp(), clock_timestamp()
FROM obj
RETURNING event_id, occurred_at
"@
    $row = Invoke-PrimarySql $markerSql
    $firstLine = ($row -split "`n")[0].Trim()
    $parts = $firstLine -split "\|"
    $markerId = $parts[0]
    $tsNorm = $parts[1] -replace "([+-]\d{2})$", "`$1:00"
    $markerTs = [DateTimeOffset]::Parse($tsNorm, [Globalization.CultureInfo]::InvariantCulture)
    Write-Host "  marker=$markerLabel"
    Write-Host "  event_id=$markerId occurred_at=$($markerTs.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))"

    Write-Host "== [3/7] WAL 推进①：pg_switch_wal + 等归档（marker 段落 S3）=="
    $walBefore = Invoke-PrimarySql "SELECT last_archived_wal FROM pg_stat_archiver"
    Invoke-PrimarySql "SELECT pg_switch_wal()" | Out-Null
    $walMid = Wait-ArchiveAdvance $walBefore
    $archMidTime = ConvertFrom-PgTimestamp (Invoke-PrimarySql "SELECT last_archived_time FROM pg_stat_archiver")
    Write-Host "  归档推进：$walBefore -> $walMid（$($archMidTime.ToString('HH:mm:ss')) UTC）"

    Write-Host "== [4/7] 目标时点 = marker + ${TargetDelaySec}s；睡过目标点后插 end-marker + WAL 推进② =="
    $target = $markerTs.AddSeconds($TargetDelaySec)
    $targetStr = $target.ToString("yyyy-MM-dd HH:mm:ss.ffffffzzz")
    $waitSec = [int][math]::Ceiling(($target - [DateTimeOffset]::UtcNow).TotalSeconds) + 2
    if ($waitSec -gt 0) {
        Write-Host "  目标时点 $targetStr —— 等待 ${waitSec}s 跨过目标点（无写入，纯时钟推进）"
        Start-Sleep -Seconds $waitSec
    }
    $endMarkerLabel = $markerLabel -replace "^pitr-marker-", "pitr-marker-end-"
    $endMarkerSql = @"
WITH obj AS (
  INSERT INTO master.business_objects (object_id, tenant_id, object_type, owner_domain, source_system, source_id, attributes)
  VALUES (gen_random_uuid(), '$tenantId', 'pitr-marker', 'w5', 'w5-drill', '$endMarkerLabel', jsonb_build_object('purpose','pitr-drill'))
  RETURNING object_id)
INSERT INTO event.events (event_id, tenant_id, event_type, object_id, source_system,
  occurred_at, data, created_at, updated_at)
SELECT gen_random_uuid(), '$tenantId', 'platform.pitr-marker', obj.object_id, 'w5-drill',
  clock_timestamp(), jsonb_build_object('marker','$endMarkerLabel','phase','end'),
  clock_timestamp(), clock_timestamp()
FROM obj
"@
    Invoke-PrimarySql $endMarkerSql | Out-Null
    $walBefore2 = Invoke-PrimarySql "SELECT last_archived_wal FROM pg_stat_archiver"
    Invoke-PrimarySql "SELECT pg_switch_wal()" | Out-Null
    $walEnd = Wait-ArchiveAdvance $walBefore2
    $archEndTime = ConvertFrom-PgTimestamp (Invoke-PrimarySql "SELECT last_archived_time FROM pg_stat_archiver")
    Write-Host "  end-marker 已提交（commit ts > target）+ 归档推进：$walBefore2 -> $walEnd"

    Write-Host "== [5/7] 恢复（RTO 计时从冷启动起）：一次性容器 + --type=time restore + promote =="
    # --target-timeline=current（=备份所在 timeline，主库现线）：显式指定，防历次演练实例 promote
    # 的新 timeline 干扰目标 timeline 判定（演练实例已统一 archive_mode=off 不再回推 repo）
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-Native @("docker", "rm", "-f", $RestoreContainer) | Out-Null
    $r = Invoke-Native @("docker", "run", "-d", "--name", $RestoreContainer,
        "--network", $RestoreNetwork, "-p", "${RestoreHostPort}:5432",
        "-v", "${ConfPath}:/etc/pgbackrest/pgbackrest.conf:ro",
        $PatroniImage, "sleep", "infinity")
    if ($r.Exit -ne 0) { throw "恢复容器启动失败：$($r.Out)" }
    Start-Sleep -Seconds 1
    Invoke-Native @("docker", "exec", $RestoreContainer, "mkdir", "-p", "/var/lib/postgresql/data/pgdata") | Out-Null
    Invoke-Native @("docker", "exec", $RestoreContainer, "chown", "postgres:postgres", "/var/lib/postgresql/data/pgdata") | Out-Null
    $r = Invoke-Native @("docker", "exec", "-u", "postgres", $RestoreContainer,
        "pgbackrest", "--stanza=edp", "--pg1-path=/var/lib/postgresql/data/pgdata",
        "--type=time", "--target=$targetStr", "--target-timeline=current",
        "--target-action=promote", "restore")
    if ($r.Exit -ne 0) { throw "pgbackrest restore 失败：$($r.Out)" }
    $setLine = ""
    if ($r.Out -match "restore backup set (\S+?),") { $setLine = $Matches[1] }
    Write-Host "  restore OK 备份集=$setLine（耗时 $([math]::Round($sw.Elapsed.TotalSeconds,1))s）"
    # 原生 postgres 单实例起（不走 patroni，避免加入集群）；archive_mode=off 防 promote 后新 timeline WAL 回推共享 repo
    $r = Invoke-Native @("docker", "exec", "-u", "postgres", $RestoreContainer,
        "pg_ctl", "-D", "/var/lib/postgresql/data/pgdata", "-l", "/tmp/pitr-postgres.log",
        "-o", "-p 5432 -c archive_mode=off", "-w", "-t", "60", "start")
    if ($r.Exit -ne 0) {
        $log = Invoke-Native @("docker", "exec", $RestoreContainer, "tail", "-n", "20", "/tmp/pitr-postgres.log")
        throw "pg_ctl start 失败：$($r.Out)`n$($log.Out)"
    }
    # 轮询 promote 完成（recovery 到达 target -> pg_is_in_recovery()=false）
    $promoted = $false
    for ($i = 1; $i -le 45; $i++) {
        $q = Invoke-RestoreSql "SELECT pg_is_in_recovery()"
        if ($q.Exit -eq 0 -and $q.Out -match "f") { $promoted = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $promoted) {
        $log = Invoke-Native @("docker", "exec", $RestoreContainer, "tail", "-n", "20", "/tmp/pitr-postgres.log")
        throw "恢复实例 90s 内未完成 promote（未到达目标时点）：$($log.Out)"
    }
    $sw.Stop()
    $rtoSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host "  promote 完成（到达目标时点 $targetStr），RTO=${rtoSeconds}s" -ForegroundColor Green

    Write-Host "== [6/7] 断言：15432 可连 + marker 存在 + end-marker 不存在 + tenants 一致 =="
    $tcp = New-Object Net.Sockets.TcpClient
    $tcpConnected = $tcp.ConnectAsync("127.0.0.1", [int]$RestoreHostPort).Wait(3000)
    $tcp.Close()
    if (-not $tcpConnected) { throw "宿主 127.0.0.1:$RestoreHostPort TCP 不可连" }
    Write-Host "  $RestoreHostPort TCP 可连"
    $primaryTenants = [int](Invoke-PrimarySql "SELECT count(*) FROM platform.tenants")
    $a1 = Invoke-RestoreSql ("SELECT count(*) FROM event.events WHERE data->>'marker' = '{0}'" -f $markerLabel)
    if ($a1.Exit -ne 0 -or [int]$a1.Out -ne 1) { throw "marker 行不存在（count=$($a1.Out)）——PITR 重放缺失目标前事务" }
    Write-Host "  marker 行存在（count=1）"
    $a2 = Invoke-RestoreSql ("SELECT count(*) FROM event.events WHERE data->>'marker' = '{0}'" -f $endMarkerLabel)
    if ($a2.Exit -ne 0 -or [int]$a2.Out -ne 0) { throw "end-marker 行被重放（count=$($a2.Out)）——时间点未停在目标" }
    Write-Host "  end-marker 未被重放（count=0，时间点精度负向断言通过）"
    $restoreTenants = [int]((Invoke-RestoreSql "SELECT count(*) FROM platform.tenants").Out)
    if ($restoreTenants -ne $primaryTenants) { throw "tenants 不一致：主库=$primaryTenants 恢复库=$restoreTenants" }
    Write-Host "  platform.tenants 主库=$primaryTenants 恢复库=$restoreTenants 一致"

    # RPO：目标时点前的提交全部可重放（零丢失）；覆盖余量 = 最后归档时刻 - 目标时点
    $rpoMargin = [math]::Round(($archEndTime - $target).TotalSeconds, 1)
    Write-Host ""
    Write-Host "== [7/7] 读数汇总 ==" -ForegroundColor Green
    Write-Host "  RTO = ${rtoSeconds}s（冷启动容器 -> restore -> WAL 重放 -> promote -> 可查可断言）"
    Write-Host "  RPO = 0s（目标时点前提交零丢失；WAL 归档覆盖余量 ${rpoMargin}s：最后归档 $walEnd @ $($archEndTime.ToString('HH:mm:ss')) vs 目标 $targetStr）"
    Write-Host "  marker: $markerLabel（event_id=$markerId）"
    Write-Host "  目标时点: $targetStr | 备份集: $($setLine.Trim())"
}
catch {
    Write-Host "PITR 演练失败：$_" -ForegroundColor Red
    Write-Host "（诊断：docker logs $RestoreContainer / 容器内 /tmp/pitr-postgres.log / pgbackrest info）"
    $fail = $true
}
finally {
    # 清理恢复容器 + 主库 marker 行（幂等；不动主栈）
    $ErrorActionPreference = "Continue"
    & docker rm -f $RestoreContainer *> $null
    $ErrorActionPreference = "Stop"
    if ($markerLabel) {
        # 注意：@() 数组字面量内跨行 `+` 不续行（实测拆成两参数被 psql 忽略）——SQL 先构变量再传
        $cleanupSql = @"
DELETE FROM event.events WHERE data->>'marker' IN ('$markerLabel', '$endMarkerLabel');
DELETE FROM master.business_objects WHERE source_system='w5-drill' AND source_id IN ('$markerLabel', '$endMarkerLabel');
"@
        Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T", "-e", "PGPASSWORD=edp_dev",
            "patroni1", "psql", "-h", "patroni1", "-U", "edp_migrator", "-d", "edp", "-q", "-c", $cleanupSql) | Out-Null
        Write-Host "清理：恢复容器已删 + 主库 marker 行已清（events + business_objects，label=$markerLabel / $endMarkerLabel）"
    }
    Pop-Location
}

if ($fail) { exit 1 }
exit 0
