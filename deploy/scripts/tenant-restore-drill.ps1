# EDP staging 租户级恢复演练（W5-T15c / EDP-027）
#
# 用法（仓库根目录；超时给足 ≥5min）：
#   powershell -File deploy/scripts/tenant-restore-drill.ps1
#
# 流程（模拟「误删某租户业务数据 -> 从最近备份隔离恢复 -> 逻辑回放找回」）：
#   [1/8] 前置 + 幂等清场 + 建 demo 租户 b（platform.tenants，固定 UUID；重跑安全）
#   [2/8] 造业务数据：master.business_objects×12 + event.events×120 + evidence.records×40（edp_migrator BYPASSRLS）
#   [3/8] 增量备份（pgbackrest --type=incr，保证备份集含本批数据）
#   [4/8] 误删（RTO 计时起）：计数留证 -> DELETE evidence.records/event.events WHERE tenant_id=b
#         —— 只删业务数据，不动 platform.tenants 行
#   [5/8] 隔离恢复：一次性容器（同 patroni 镜像原生 postgres，宿主 15434）restore 最新备份集（full+incr 链）
#   [6/8] 校验+回放：隔离库该租户行数 == 误删前计数 -> 容器内 COPY 管道按表回插主库
#         （CSV 经 psql|psql，全程容器内不落宿主盘；edp_migrator 写入）
#   [7/8] 断言：主库计数恢复 == 留证计数；evidence checksum 抽样 5 条与隔离库一致（RTO 计时止）
#   [8/8] 读数汇总 + 清恢复容器（租户 b 数据保留 = 演练成果）+ 追加日志 deploy/logs/tenant-restore-drill.log
#
# 口径说明：api 层断言（HTTP 查询该租户 events）需 tenant-b 成员账号/JWT（未配置）——
#   以 DB 层等价断言（migrator 直查 + checksum 抽样）留痕；api /healthz 全程 200 不受影响。
# PowerShell 5.1 兼容：无三元/??/管道链语法；SQL 内联值用 dollar-quoting（$$uuid$$）避开双层引号。

$ErrorActionPreference = "Stop"

# ---- 路径与常量 ----
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # deploy/scripts -> 仓库根
$ComposeFile = "deploy/docker-compose.staging.yml"
$ConfPath = Join-Path $RepoRoot "deploy/pgbackrest/pgbackrest.conf"
$LogDir = Join-Path $RepoRoot "deploy/logs"
$LogFile = Join-Path $LogDir "tenant-restore-drill.log"
$RestoreContainer = "edp-tenant-restore"
$RestoreNetwork = "edp-staging_default"
$RestoreHostPort = "15434"     # 15432=dev-db 常驻、15433=PITR 演练占用，本演练 15434
$PatroniImage = "edp-staging/patroni:pg16"
$TenantB = "b0000000-0000-4000-8000-00000000000b"   # demo 租户 b 固定 UUID（幂等重跑）
$SeedEvents = 120
$SeedEvidence = 40
# PS 双引号串里 $$ 是自动变量——用反引号转义出字面 $$（SQL dollar-quoting）
$Dq = "`$`$"

function Invoke-Native {
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"
    $out = & $CmdArgs[0] $CmdArgs[1..($CmdArgs.Length - 1)] 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return @{ Out = $out; Exit = $code }
}

function Invoke-PrimarySql {
    param([string]$Sql)
    $r = Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T",
        "-e", "PGPASSWORD=edp_dev", "patroni1",
        "psql", "-h", "patroni1", "-U", "edp_migrator", "-d", "edp", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", $Sql)
    if ($r.Exit -ne 0) { throw "主库 SQL 失败：$Sql`n$($r.Out)" }
    return $r.Out.Trim()
}

function Invoke-IsolatedSql {
    param([string]$Sql)
    $r = Invoke-Native @("docker", "exec",
        "-e", "PGPASSWORD=edp_dev", $RestoreContainer,
        "psql", "-h", "127.0.0.1", "-p", "5432", "-U", "edp_migrator", "-d", "edp", "-t", "-A", "-c", $Sql)
    return @{ Out = $r.Out.Trim(); Exit = $r.Exit }
}

Push-Location $RepoRoot
$swRto = $null; $evBefore = -1; $evBeforeEvid = -1; $isoEv = -1; $isoEvid = -1
$afterEv = -1; $afterEvid = -1; $sampleOk = 0; $backupLabel = ""
try {
    Write-Host "== [1/8] 前置 + 幂等清场 + 建 demo 租户 b =="
    $cleanSql = @"
DELETE FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq;
DELETE FROM event.events WHERE tenant_id=$Dq$TenantB$Dq;
DELETE FROM master.business_objects WHERE tenant_id=$Dq$TenantB$Dq AND source_system='t15c-drill';
INSERT INTO platform.tenants (tenant_id, slug, name, plan, status, attributes, created_by)
VALUES ($Dq$TenantB$Dq, 'demo-b', 'T15c 恢复演练租户B', 'STANDARD', 'ACTIVE',
  jsonb_build_object('purpose','tenant-restore-drill'), 'w5-drill')
ON CONFLICT (tenant_id) DO NOTHING
"@
    Invoke-PrimarySql $cleanSql | Out-Null
    Write-Host "  租户 b 就绪（tenant_id=$TenantB）"

    Write-Host "== [2/8] 造业务数据：objects×12 + events×$SeedEvents + evidence×$SeedEvidence =="
    $seedSql = @"
INSERT INTO master.business_objects (object_id, tenant_id, object_type, owner_domain, source_system, source_id)
SELECT ('b0000000-0000-4000-8000-' || lpad(g::text, 12, '0'))::uuid, $Dq$TenantB$Dq, 'demo-order', 'sales', 't15c-drill', 'obj-' || g
FROM generate_series(1, 12) g;

INSERT INTO event.events (event_id, tenant_id, event_type, object_id, source_system, occurred_at, actor_type, actor_id, data)
SELECT gen_random_uuid(), $Dq$TenantB$Dq, 'sales.order.created',
  ('b0000000-0000-4000-8000-' || lpad(((g % 12) + 1)::text, 12, '0'))::uuid,
  't15c-erp', now() - (g || ' minutes')::interval, 'SERVICE', 't15c-drill',
  jsonb_build_object('seq', g, 'drill', 't15c')
FROM generate_series(1, $SeedEvents) g;

INSERT INTO evidence.records (evidence_id, tenant_id, source_system, source_record_id, object_id, event_id,
  content_type, checksum, checksum_algo, snapshot, captured_at)
SELECT gen_random_uuid(), $Dq$TenantB$Dq, 't15c-erp', 't15c-ev-' || g,
  ('b0000000-0000-4000-8000-' || lpad(((g % 12) + 1)::text, 12, '0'))::uuid,
  (SELECT event_id FROM event.events WHERE tenant_id = $Dq$TenantB$Dq AND (data->>'seq')::int = ((g - 1) % $SeedEvents) + 1),
  'application/json', md5('t15c-evidence-' || g), 'md5', jsonb_build_object('seq', g, 'kind', 'demo'),
  now() - (g || ' minutes')::interval
FROM generate_series(1, $SeedEvidence) g;
"@
    Invoke-PrimarySql $seedSql | Out-Null
    $evBefore = [int](Invoke-PrimarySql "SELECT count(*) FROM event.events WHERE tenant_id=$Dq$TenantB$Dq")
    $evBeforeEvid = [int](Invoke-PrimarySql "SELECT count(*) FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq")
    if ($evBefore -ne $SeedEvents -or $evBeforeEvid -ne $SeedEvidence) {
        throw "造数计数不符：events=$evBefore/$SeedEvents evidence=$evBeforeEvid/$SeedEvidence"
    }
    Write-Host "  造数完成（留证计数）：event.events=$evBefore / evidence.records=$evBeforeEvid"

    Write-Host "== [3/8] 增量备份（含本批数据）=="
    $r = Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T", "patroni1",
        "pgbackrest", "--stanza=edp", "--type=incr", "backup")
    if ($r.Exit -ne 0) { throw "增量备份失败：$($r.Out)" }
    if ($r.Out -match "new backup label = (\S+)") { $backupLabel = $Matches[1] }
    Write-Host "  incr 备份集：$backupLabel"

    Write-Host "== [4/8] 误删（RTO 计时起）：DELETE 租户 b 业务数据（不动 platform.tenants）=="
    $swRto = [System.Diagnostics.Stopwatch]::StartNew()
    $deleteSql = @"
DELETE FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq;
DELETE FROM event.events WHERE tenant_id=$Dq$TenantB$Dq
"@
    Invoke-PrimarySql $deleteSql | Out-Null
    $delEv = [int](Invoke-PrimarySql "SELECT count(*) FROM event.events WHERE tenant_id=$Dq$TenantB$Dq")
    $delEvid = [int](Invoke-PrimarySql "SELECT count(*) FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq")
    if ($delEv -ne 0 -or $delEvid -ne 0) { throw "误删未生效：events=$delEv evidence=$delEvid（应均为 0）" }
    $tenantRow = [int](Invoke-PrimarySql "SELECT count(*) FROM platform.tenants WHERE tenant_id=$Dq$TenantB$Dq")
    Write-Host "  误删后 events=0 / evidence=0；platform.tenants 行保留（count=$tenantRow，口径要求）"

    Write-Host "== [5/8] 隔离恢复：一次性容器（$RestoreContainer :$RestoreHostPort）restore 最新备份集 =="
    # --target-timeline=current（=备份所在 timeline，主库现线）：显式指定，避免被历次演练实例
    # promote 产生的新 timeline 干扰（实测默认 latest 会因演练线 fork 点早于备份 LSN 报 [058]，
    # 指定数字又要求 repo 有该线 .history——current 两者皆免，见 w5-drills T15c 踩坑记）
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
        "--target-timeline=current", "restore")
    if ($r.Exit -ne 0) { throw "隔离 restore 失败：$($r.Out)" }
    $setLine = ""
    if ($r.Out -match "restore backup set (\S+?),") { $setLine = $Matches[1] }
    # archive_mode=off：演练实例 end-of-recovery 的新 timeline WAL 不回推共享 repo（防污染）
    $r = Invoke-Native @("docker", "exec", "-u", "postgres", $RestoreContainer,
        "pg_ctl", "-D", "/var/lib/postgresql/data/pgdata", "-l", "/tmp/tenant-restore-postgres.log",
        "-o", "-p 5432 -c archive_mode=off", "-w", "-t", "60", "start")
    if ($r.Exit -ne 0) {
        $log = Invoke-Native @("docker", "exec", $RestoreContainer, "tail", "-n", "20", "/tmp/tenant-restore-postgres.log")
        throw "隔离实例启动失败：$($r.Out)`n$($log.Out)"
    }
    # 等可连（restore 后 end-of-recovery 完成）
    $ready = $false
    for ($i = 1; $i -le 30; $i++) {
        $q = Invoke-IsolatedSql "SELECT pg_is_in_recovery()"
        if ($q.Exit -eq 0 -and $q.Out -match "f") { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "隔离实例 60s 内未就绪" }
    Write-Host "  隔离实例就绪（restore 自 $setLine）"

    Write-Host "== [6/8] 校验隔离库 + 容器内 COPY 管道回放主库 =="
    $isoEv = [int]((Invoke-IsolatedSql "SELECT count(*) FROM event.events WHERE tenant_id=$Dq$TenantB$Dq").Out)
    $isoEvid = [int]((Invoke-IsolatedSql "SELECT count(*) FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq").Out)
    if ($isoEv -ne $evBefore -or $isoEvid -ne $evBeforeEvid) {
        throw "隔离库计数不符（应 == 误删前）：events=$isoEv/$evBefore evidence=$isoEvid/$evBeforeEvid"
    }
    Write-Host "  隔离库计数 == 误删前（events=$isoEv / evidence=$isoEvid）"
    # 回放：edp_migrator 全程；容器内 psql|psql 管道（CSV 不落宿主盘）；主库行已删，UUID 直插无冲突
    foreach ($table in @("event.events", "evidence.records")) {
        $pipe = ("psql -h 127.0.0.1 -U edp_migrator -d edp -v ON_ERROR_STOP=1 " +
            "-c 'COPY (SELECT * FROM $table WHERE tenant_id=${Dq}$TenantB${Dq}) TO STDOUT WITH (FORMAT csv)' " +
            "| psql -h patroni1 -U edp_migrator -d edp -v ON_ERROR_STOP=1 " +
            "-c 'COPY $table FROM STDIN WITH (FORMAT csv)'")
        $r = Invoke-Native @("docker", "exec", "-e", "PGPASSWORD=edp_dev", $RestoreContainer, "sh", "-c", $pipe)
        if ($r.Exit -ne 0) { throw "回放 $table 失败：$($r.Out)" }
        $copied = ($r.Out -split "`n" | Where-Object { $_ -match "^COPY \d+" }) -join ""
        Write-Host "  回放 $table -> $copied"
    }

    Write-Host "== [7/8] 断言：主库计数恢复 + checksum 抽样一致（RTO 计时止）=="
    $afterEv = [int](Invoke-PrimarySql "SELECT count(*) FROM event.events WHERE tenant_id=$Dq$TenantB$Dq")
    $afterEvid = [int](Invoke-PrimarySql "SELECT count(*) FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq")
    if ($afterEv -ne $evBefore -or $afterEvid -ne $evBeforeEvid) {
        throw "回放后主库计数不符：events=$afterEv/$evBefore evidence=$afterEvid/$evBeforeEvid"
    }
    Write-Host "  主库恢复计数 == 误删前（events=$afterEv / evidence=$afterEvid）"
    # checksum 抽样：隔离库 vs 主库各取前 5 条（source_record_id 序），比对一致
    $sampleIso = (Invoke-IsolatedSql ("SELECT checksum FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq " +
        "ORDER BY source_record_id LIMIT 5")).Out -split "`n"
    $samplePri = (Invoke-PrimarySql ("SELECT checksum FROM evidence.records WHERE tenant_id=$Dq$TenantB$Dq " +
        "ORDER BY source_record_id LIMIT 5")) -split "`n"
    for ($i = 0; $i -lt 5; $i++) {
        if ($sampleIso[$i].Trim() -eq $samplePri[$i].Trim()) { $sampleOk++ }
    }
    if ($sampleOk -ne 5) { throw "checksum 抽样不一致（$sampleOk/5）" }
    $swRto.Stop()
    $rtoSeconds = [math]::Round($swRto.Elapsed.TotalSeconds, 1)
    Write-Host "  checksum 抽样 5/5 一致"
    Write-Host "  RTO = ${rtoSeconds}s（误删 -> 隔离恢复 -> 回放 -> 断言全过；目标 ≤4h）" -ForegroundColor Green

    Write-Host ""
    Write-Host "== [8/8] 读数汇总 ==" -ForegroundColor Green
    Write-Host "  误删前/隔离库/回放后：events $evBefore/$isoEv/$afterEv，evidence $evBeforeEvid/$isoEvid/$afterEvid"
    Write-Host "  RTO = ${rtoSeconds}s | RPO = 0s（整批找回，行数+checksum 抽样 5/5 一致）"
    Write-Host "  备份链：incr $backupLabel（隔离 restore 自 $setLine）"
}
catch {
    Write-Host "租户级恢复演练失败：$_" -ForegroundColor Red
    Write-Host "（诊断：docker logs $RestoreContainer / 容器内 /tmp/tenant-restore-postgres.log）"
    $fail = $true
}
finally {
    $ErrorActionPreference = "Continue"
    & docker rm -f $RestoreContainer *> $null
    $ErrorActionPreference = "Stop"
    $rtoText = -1
    if ($swRto) { $rtoText = [math]::Round($swRto.Elapsed.TotalSeconds, 1) }
    if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
    $line = "{0} | {1} | events {2}->{3}->{4} | evidence {5}->{6}->{7} | checksum {8}/5 | rto={9}s | {10}" -f `
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $TenantB, $evBefore, $isoEv, $afterEv,
        $evBeforeEvid, $isoEvid, $afterEvid, $sampleOk, $rtoText, $(if ($fail) { "RED" } else { "GREEN" })
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host "日志已追加：$LogFile（租户 b 数据保留 = 演练成果；仅清理恢复容器）"
    Pop-Location
}

if ($fail) { exit 1 }
exit 0
