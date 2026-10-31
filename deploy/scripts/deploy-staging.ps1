# EDP staging 部署/回滚/演练脚本（T14 / EDP-021）
#
# 用法（仓库根目录）：
#   powershell -File deploy/scripts/deploy-staging.ps1 -Action deploy    # 全新部署：HA 层→账号→迁移→应用层→健康探测（失败自动 rollback）
#   powershell -File deploy/scripts/deploy-staging.ps1 -Action rollback # 回滚应用层到上一版镜像（最小回滚语义，见注释）
#   powershell -File deploy/scripts/deploy-staging.ps1 -Action drill    # 主从切换演练 + 中断/lag 读数 → docs/demo/staging-drill.md
#
# PowerShell 5.1 兼容：无三元/??/管道链语法。

param([string]$Action = "deploy")

$ErrorActionPreference = "Stop"

# ---- 路径与常量 ----
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # deploy/scripts -> 仓库根
$ComposeFile = "deploy/docker-compose.staging.yml"
$ApiHealthUrl = "http://localhost:18010/healthz"     # api 无认证探活端点（main.py /healthz）
$Rest1 = "http://localhost:8008"                     # patroni1 restapi（宿主映射）
$Rest2 = "http://localhost:8009"                     # patroni2 restapi（宿主映射）
$DrillReport = Join-Path $RepoRoot "docs/demo/staging-drill.md"
$AppServices = @("api", "worker", "web")

Push-Location $RepoRoot
try {
    # ---- 工具函数 ----
    function Invoke-Compose {
        param([string[]]$ComposeArgs)
        & docker compose -f $ComposeFile @ComposeArgs
        if ($LASTEXITCODE -ne 0) { throw "docker compose $($ComposeArgs -join ' ') 失败 (exit=$LASTEXITCODE)" }
    }

    function Get-Http {
        # 返回状态码 int；连接失败返回 -1
        param([string]$Url, [int]$TimeoutSec = 3)
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
            return [int]$resp.StatusCode
        } catch {
            if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
            return -1
        }
    }

    function Get-ClusterState {
        param([string]$BaseUrl)
        try {
            $json = Invoke-RestMethod -Uri "$BaseUrl/cluster" -TimeoutSec 5
            return $json
        } catch { return $null }
    }

    function Get-LeaderName {
        # 依次探测两个 restapi，返回当前 leader 节点名（staging-pg1/staging-pg2）或 $null
        foreach ($base in @($Rest1, $Rest2)) {
            $cluster = Get-ClusterState $base
            if ($cluster -and $cluster.members) {
                $leader = @($cluster.members) | Where-Object { $_.role -eq "leader" }
                if ($leader) { return $leader[0].name }
            }
        }
        return $null
    }

    function Wait-Leader {
        param([int]$Attempts = 30, [int]$IntervalSec = 2)
        for ($i = 1; $i -le $Attempts; $i++) {
            $name = Get-LeaderName
            if ($name) { return $name }
            Write-Host "  等待 Patroni 产生 leader（$i/$Attempts）..."
            Start-Sleep -Seconds $IntervalSec
        }
        throw "Patroni 集群在 $($Attempts * $IntervalSec)s 内未产生 leader；请查 docker compose -f $ComposeFile logs etcd patroni1 patroni2"
    }

    function LeaderServiceName {
        param([string]$LeaderName)
        if ($LeaderName -eq "staging-pg2") { return "patroni2" }
        return "patroni1"
    }

    function Test-ImageExists {
        # PS 5.1：EAP=Stop 下原生命令 stderr 重定向会抛 NativeCommandError——局部降级再探测
        param([string]$Image)
        $ErrorActionPreference = "Continue"
        & docker image inspect $Image *> $null
        $code = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        return ($code -eq 0)
    }

    function Probe-Api {
        # 30×2s 轮询 api /healthz；成功返回 $true
        param([int]$Attempts = 30, [int]$IntervalSec = 2)
        for ($i = 1; $i -le $Attempts; $i++) {
            $code = Get-Http $ApiHealthUrl 3
            if ($code -eq 200) {
                Write-Host "  api /healthz 200（第 $i 次探测）"
                return $true
            }
            Write-Host "  api /healthz=$code（$i/$Attempts），${IntervalSec}s 后重试..."
            Start-Sleep -Seconds $IntervalSec
        }
        return $false
    }

    # ==================================================================
    # rollback：最小回滚语义（留痕）
    #   - deploy 在 `up --build` 前把应用层当前镜像打为 *:rollback（本机 tag 链）；
    #     rollback 将 :rollback 重新打回 :latest 并 `up -d --no-build --force-recreate`。
    #   - 迁移不回滚：发布流程为「迁移先行 + 向前兼容」（设计 9.5），旧应用可跑在新 schema 上。
    #   - W5 接入镜像仓库后升级为 registry tag 链 + 独立迁移版本记录。
    # ==================================================================
    function Invoke-Rollback {
        param([string]$Reason = "")
        if ($Reason) { Write-Host "回滚原因：$Reason" -ForegroundColor Yellow }
        Write-Host "== rollback：回退应用层到上一版镜像 =="
        $restored = 0
        foreach ($svc in $AppServices) {
            $img = "edp-staging-$svc"
            if (Test-ImageExists "${img}:rollback") {
                & docker tag "${img}:rollback" "${img}:latest"
                Write-Host "  ${img}:rollback -> :latest"
                $restored++
            } else {
                Write-Host "  ${img} 无 :rollback 记录（首次部署即失败场景）——按当前镜像 recreate"
            }
        }
        Invoke-Compose (@("up", "-d", "--no-build", "--force-recreate") + $AppServices)
        $ok = Probe-Api -Attempts 15 -IntervalSec 2
        if ($ok) { Write-Host "回滚完成，api /healthz 已恢复 200" -ForegroundColor Green }
        else { Write-Host "回滚后 api /healthz 仍未恢复，请人工排查：docker compose -f $ComposeFile logs api" -ForegroundColor Red }
        return $ok
    }

    # ==================================================================
    # deploy：HA 层 -> 账号（pg-init）-> 迁移（edp_migrator）-> 应用层 -> 健康探测
    # ==================================================================
    if ($Action -eq "deploy") {
        Write-Host "== [1/5] 起 etcd + patroni×2（等健康检查通过）=="
        Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "240", "etcd", "patroni1", "patroni2", "pgbackrest")

        $leader = Wait-Leader
        $leaderSvc = LeaderServiceName $leader
        $leaderHost = $leaderSvc   # compose 服务名即容器网络主机名
        Write-Host "  Patroni 集群就绪：leader=$leader（service=$leaderSvc）"

        Write-Host "== [2/5] 账号初始化（幂等）：edp_migrator + pg-init/01-roles.sql（edp_app）+ edp 库 =="
        # dev 由 POSTGRES_USER=edp_migrator 承担；staging patroni 需显式补建（SUPERUSER+BYPASSRLS，同 dev 语义）
        $MigratorSql = @'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'edp_migrator') THEN
        CREATE ROLE edp_migrator LOGIN SUPERUSER BYPASSRLS PASSWORD 'edp_dev';
    END IF;
END
$$;
'@
        $MigratorSql | & docker compose -f $ComposeFile exec -T $leaderSvc psql -U postgres -v ON_ERROR_STOP=1 -q
        if ($LASTEXITCODE -ne 0) { throw "创建 edp_migrator 失败（leader=$leaderSvc）" }
        # pg-init/01-roles.sql（dev/CI 同一文件，幂等 DO 块）——staging 数据库同样初始化后再跑迁移
        Get-Content "deploy/pg-init/01-roles.sql" -Raw | & docker compose -f $ComposeFile exec -T $leaderSvc psql -U postgres -v ON_ERROR_STOP=1 -q
        if ($LASTEXITCODE -ne 0) { throw "执行 pg-init/01-roles.sql 失败" }
        $DbSql = @'
SELECT 'CREATE DATABASE edp OWNER edp_migrator'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'edp')\gexec
ALTER DATABASE edp OWNER TO edp_migrator;
'@
        $DbSql | & docker compose -f $ComposeFile exec -T $leaderSvc psql -U postgres -v ON_ERROR_STOP=1 -q
        if ($LASTEXITCODE -ne 0) { throw "创建/校正 edp 库失败" }
        Write-Host "  账号就绪：edp_migrator（迁移/属主）、edp_app（受 RLS 约束的应用账号）、库 edp"

        Write-Host "== [3/5] 迁移先行：临时容器 alembic upgrade head（对当前 leader=$leaderHost 执行）=="
        $MigUrl = "postgresql+asyncpg://edp_migrator:edp_dev@${leaderHost}:5432/edp"
        Invoke-Compose @("run", "--rm", "--no-deps", "-e", "EDP_DATABASE_URL=$MigUrl", "api", "alembic", "upgrade", "head")

        Write-Host "== [4/5] 应用层滚动：记录回滚点 -> up -d --build =="
        foreach ($svc in $AppServices) {
            $img = "edp-staging-$svc"
            if (Test-ImageExists "${img}:latest") {
                & docker tag "${img}:latest" "${img}:rollback"
                Write-Host "  回滚点已记录：${img}:latest -> :rollback"
            }
        }
        # pgbackrest repo 目录授权（postgres 用户可写；幂等）
        & docker compose -f $ComposeFile exec -T pgbackrest sh -c "mkdir -p /pgbackrest/repo && chmod 777 /pgbackrest/repo"
        Invoke-Compose (@("up", "-d", "--build") + $AppServices)

        Write-Host "== [5/5] api /healthz 探测（30×2s，失败自动回滚）=="
        $healthy = Probe-Api -Attempts 30 -IntervalSec 2
        if (-not $healthy) {
            Write-Host "部署后健康探测失败 —— 触发回滚" -ForegroundColor Red
            Invoke-Rollback -Reason "deploy 后 api /healthz 30×2s 未恢复 200"
            exit 1
        }

        Write-Host ""
        Write-Host "staging 部署就绪：" -ForegroundColor Green
        Write-Host "  api   http://localhost:18010/healthz（/api/v1/*）"
        Write-Host "  web   http://localhost:9090"
        Write-Host "  patroni restapi  :8008(patroni1)/:8009(patroni2)，leader=$leader"
        Write-Host "  演练：powershell -File deploy/scripts/deploy-staging.ps1 -Action drill"
        exit 0
    }

    # ==================================================================
    # rollback 子命令
    # ==================================================================
    if ($Action -eq "rollback") {
        $ok = Invoke-Rollback -Reason "人工触发"
        if (-not $ok) { exit 1 }
        exit 0
    }

    # ==================================================================
    # drill：主从切换演练（switchover 往返）+ 前后 /health 连续探测 + lag 读数
    #   全部读数输出到控制台并写入 docs/demo/staging-drill.md
    # ==================================================================
    if ($Action -eq "drill") {
        Write-Host "== drill 前置检查 =="
        $code = Get-Http $ApiHealthUrl 3
        if ($code -ne 200) { throw "api $ApiHealthUrl 非 200（code=$code）——请先执行 deploy" }

        $leader = Get-LeaderName
        if (-not $leader) { throw "未取到 Patroni leader——请先执行 deploy" }
        if ($leader -ne "staging-pg1") {
            # 上一轮演练未回切：先回切到 pg1，保证演练起点确定（DATABASE_URL 单写入口 = patroni1）
            Write-Host "  当前 leader=$leader，先回切 staging-pg1 以固定演练起点"
            & docker compose -f $ComposeFile exec -T patroni2 patronictl -c /etc/patroni.yml switchover edp_staging --leader $leader --candidate staging-pg1 --force
            if ($LASTEXITCODE -ne 0) { throw "回切 staging-pg1 失败" }
            Start-Sleep -Seconds 10
        }

        function Format-Cluster {
            param($Cluster)
            if (-not $Cluster) { return "(cluster 不可达)" }
            $lines = @()
            foreach ($m in @($Cluster.members)) {
                $lines += ("    - {0}  role={1}  state={2}  timeline={3}  lag={4}" -f $m.name, $m.role, $m.state, $m.timeline, $m.lag)
            }
            return $lines
        }

        function Read-PrimaryCodes {
            $c1 = Get-Http "$Rest1/primary" 3
            $c2 = Get-Http "$Rest2/primary" 3
            return "    GET :8008/primary -> $c1 ; GET :8009/primary -> $c2  （200=主，503=从）"
        }

        function Invoke-SwitchoverWithProbe {
            # 后台 job 执行 switchover，前台 20×1s 连续探测 api /healthz，返回探测记录
            param([string]$FromNode, [string]$ToNode, [string]$ExecSvc)
            $job = Start-Job -ScriptBlock {
                param($repoRoot, $composeFile, $execSvc, $fromNode, $toNode)
                Set-Location $repoRoot
                & docker compose -f $composeFile exec -T $execSvc patronictl -c /etc/patroni.yml switchover edp_staging --leader $fromNode --candidate $toNode --force 2>&1
                exit $LASTEXITCODE
            } -ArgumentList $RepoRoot, $ComposeFile, $ExecSvc, $FromNode, $ToNode
            $records = @()
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            for ($i = 1; $i -le 20; $i++) {
                $c = Get-Http $ApiHealthUrl 2
                $records += ("    [{0:HH:mm:ss.fff}] +{1,5:n1}s  /healthz -> {2}" -f (Get-Date), $sw.Elapsed.TotalSeconds, $c)
                Start-Sleep -Seconds 1
            }
            $sw.Stop()
            $out = Receive-Job -Job $job -Wait
            $jc = $job.ChildJobs[0].JobStateInfo.State
            Remove-Job $job -Force
            return @{ Records = $records; SwitchOutput = ($out -join "`n"); JobState = "$jc" }
        }

        function Wait-Settle {
            # replica 的 state 为 streaming（稳定后），leader 为 running
            param([string]$ExpectLeader, [int]$TimeoutSec = 90)
            $deadline = (Get-Date).AddSeconds($TimeoutSec)
            while ((Get-Date) -lt $deadline) {
                $cluster = Get-ClusterState $Rest1
                if ($cluster) {
                    $l = @($cluster.members) | Where-Object { $_.role -eq "leader" }
                    $r = @($cluster.members) | Where-Object { $_.role -eq "replica" }
                    if ($l -and $r -and $l[0].name -eq $ExpectLeader -and @("streaming", "running") -contains $r[0].state) { return $true }
                }
                Start-Sleep -Seconds 2
            }
            return $false
        }

        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $Nl4 = "`n    "

        # -- 快照：镜像 tag / PG 版本 --
        $pgVersion = ((& docker compose -f $ComposeFile exec -T patroni1 psql -U postgres -t -A -c "show server_version") -join "").Trim()
        $patroniImage = (& docker inspect --format "{{.Config.Image}}" $(docker compose -f $ComposeFile ps -q patroni1)) -join ""
        $apiImageFull = (& docker inspect --format "{{.Image}}" $(docker compose -f $ComposeFile ps -q api)) -join ""
        $apiImageId = $apiImageFull.Substring($apiImageFull.Length - 12)

        # -- 切换前读数 --
        Write-Host "== 切换前快照（leader 应为 staging-pg1）=="
        $clusterBefore = Get-ClusterState $Rest1
        $clusterBeforeText = Format-Cluster $clusterBefore
        $primaryBefore = Read-PrimaryCodes

        # -- 第 1 段：switchover staging-pg1 -> staging-pg2 + 连续探测 --
        Write-Host "== [1/2] switchover staging-pg1 -> staging-pg2（探测 20×1s 并行进行）=="
        $r1 = Invoke-SwitchoverWithProbe -FromNode "staging-pg1" -ToNode "staging-pg2" -ExecSvc "patroni1"
        $fail1 = @($r1.Records | Where-Object { $_ -notmatch "-> 200$" }).Count
        Write-Host "  switchover job 输出：$($r1.SwitchOutput)（job=$($r1.JobState)）"
        $settle1 = Wait-Settle -ExpectLeader "staging-pg2"
        $clusterMid = Get-ClusterState $Rest1
        $clusterMidText = Format-Cluster $clusterMid
        $primaryMid = Read-PrimaryCodes
        $replMid = ((& docker compose -f $ComposeFile exec -T patroni2 psql -U postgres -t -A -c "SELECT application_name || ' state=' || state || ' sync=' || sync_state || ' replay_lag=' || COALESCE(replay_lag::text,'NULL') FROM pg_stat_replication") -join $Nl4).Trim()

        # -- 第 2 段：switchover 回切 staging-pg2 -> staging-pg1 + 连续探测 --
        Write-Host "== [2/2] switchover 回切 staging-pg2 -> staging-pg1（探测 20×1s 并行进行）=="
        $r2 = Invoke-SwitchoverWithProbe -FromNode "staging-pg2" -ToNode "staging-pg1" -ExecSvc "patroni2"
        $fail2 = @($r2.Records | Where-Object { $_ -notmatch "-> 200$" }).Count
        Write-Host "  switchover job 输出：$($r2.SwitchOutput)（job=$($r2.JobState)）"
        $settle2 = Wait-Settle -ExpectLeader "staging-pg1"
        $clusterAfter = Get-ClusterState $Rest1
        $clusterAfterText = Format-Cluster $clusterAfter
        $primaryAfter = Read-PrimaryCodes
        $replAfter = ((& docker compose -f $ComposeFile exec -T patroni1 psql -U postgres -t -A -c "SELECT application_name || ' state=' || state || ' sync=' || sync_state || ' replay_lag=' || COALESCE(replay_lag::text,'NULL') FROM pg_stat_replication") -join $Nl4).Trim()

        # -- pgbackrest 备份演练（幂等：stanza-create 已存在则 no-op）--
        # pgbackrest 日志走 stderr：2>&1 捕获与 EAP=Stop 冲突，局部降为 Continue
        Write-Host "== pgbackrest 备份命令演练（stanza-create + 全量备份）=="
        $ErrorActionPreference = "Continue"
        $stanzaOutput = (& docker compose -f $ComposeFile exec -T patroni1 pgbackrest --stanza=edp stanza-create 2>&1) | Out-String
        $stanzaCreateExit = $LASTEXITCODE
        $backupOutput = (& docker compose -f $ComposeFile exec -T patroni1 pgbackrest --stanza=edp backup --type=full 2>&1) | Out-String
        $backupExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        $backupInfo = ((& docker compose -f $ComposeFile exec -T patroni1 pgbackrest info) -join "`n").Trim()

        # -- 汇总报告 --
        $report = @"
# staging 主从切换演练记录（EDP-021 / T14）

- 演练时间：$timestamp
- 演练命令：powershell -File deploy/scripts/deploy-staging.ps1 -Action drill
- 拓扑形态：双节点（未降级）

## 拓扑（ASCII）

~~~
              +----------------------+
   应用层      |  api :18010          |
   (复用 dev   |  worker              |
    build)     |  web :9090           |
              +----------+-----------+
                         |  DATABASE_URL（单写入口，最小版不自动跟随）
                         v
              +----------------------+         流复制         +----------------------+
   HA 层      |  patroni1/staging-pg1| <--------------------> |  patroni2/staging-pg2|
              |  PG16  restapi :8008 |                       |  PG16  restapi :8009 |
              +----------+-----------+                       +----------+-----------+
                         |  leader 仲裁（etcd v3.5，QUOTA 4GB，单节点）
                         +------------------+----------------------------------+
                                            |
                              +-------------+-------------+
                              | pgbackrest（repo 卷 keeper）|
                              +---------------------------+
~~~

## 镜像与版本（实测）

- patroni 节点镜像：$patroniImage（自建：postgres:16-bookworm + patroni 4.1.5 + pgbackrest 2.59.1 + curl）
- PostgreSQL：$pgVersion
- api 镜像：$apiImageId（edp-staging-api，backend/apps/api/Dockerfile 构建产物）

## 切换前 primary

$primaryBefore
$($clusterBeforeText -join $Nl4)

## 演练 1：switchover staging-pg1 -> staging-pg2

patronictl 输出：
    $($r1.SwitchOutput)

api /healthz 连续探测（20×1s，与 switchover 并行）：
$($r1.Records -join "`n")

- 非探测窗口：$fail1/20
- 集群收敛：$(if ($settle1) { "已收敛（staging-pg2=leader，staging-pg1=running replica）" } else { "90s 内未完全收敛（见 Concerns）" })

切换后角色/延迟读数：
$primaryMid
$($clusterMidText -join $Nl4)
    pg_stat_replication（新主 staging-pg2 上查询）：
    $replMid

## 演练 2：switchover 回切 staging-pg2 -> staging-pg1

patronictl 输出：
    $($r2.SwitchOutput)

api /healthz 连续探测（20×1s，与 switchover 并行）：
$($r2.Records -join "`n")

- 非探测窗口：$fail2/20
- 集群收敛：$(if ($settle2) { "已收敛（staging-pg1=leader，staging-pg2=running replica）" } else { "90s 内未完全收敛（见 Concerns）" })

切换后角色/延迟读数：
$primaryAfter
$($clusterAfterText -join $Nl4)
    pg_stat_replication（回切后主 staging-pg1 上查询）：
    $replAfter

## pgbackrest 备份命令演练

- stanza-create 退出码：$stanzaCreateExit
~~~
$($stanzaOutput.Trim())
~~~
- 全量备份退出码：$backupExit
~~~
$($backupOutput.Trim())
~~~
- pgbackrest info：
~~~
$backupInfo
~~~

## 结论

（人工复核后补充）

## 降级预案与后续项

- 降级预案（本次未触发）：宿主资源不足 -> 去 patroni2 单节点，演练改为「拓扑编排冒烟 + 备份命令演练」，双节点切换演练记「未执行-W5 补」。
- 后续项：单写入口不自动跟随（W5 引入 HAProxy/Pgbouncer）；pgbackrest 备份仍在本机 repo 卷（W5 迁对象存储 + PITR/租户级恢复演练，见设计 9.2）；回滚为本机 tag 链最小语义（W5 接镜像仓库做版本化）。
"@
        Set-Content -Path $DrillReport -Value $report -Encoding UTF8
        Write-Host ""
        Write-Host "演练完成：报告已写入 $DrillReport" -ForegroundColor Green
        if ($fail1 -gt 0 -or $fail2 -gt 0) {
            Write-Host "探测期间出现非 200：演练1=$fail1 次，演练2=$fail2 次（详见报告）" -ForegroundColor Yellow
        }
        exit 0
    }

    throw "未知 Action：$Action（可用：deploy / rollback / drill）"
}
finally {
    Pop-Location
}
