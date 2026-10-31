# EDP staging 备份验证脚本（W5-T15a / EDP-031）
#
# 用法（仓库根目录，单次完整验证；连续 N 次全绿 = 「连续 N 天」等价证据，口径见 w5-drills.md T15a）：
#   powershell -File deploy/scripts/backup-verify.ps1
#
# 单次流程：
#   [1/3] pgbackrest check（patroni1 exec；含 WAL 归档真实往返）
#   [2/3] 抽样恢复验证：一次性恢复容器（同 patroni 镜像，S3 repo）restore 最新备份集
#         到 /tmp/verify -> 单用户模式（postgres --single）查 platform.tenants 行数断言非零
#   [3/3] 拆容器 + 结果追加 deploy/logs/backup-verify.log（gitignore）
#
# 退出码：0 = 全绿（check 通过 + 恢复成功 + 断言通过）；1 = 任一环节失败（如实记 RED）。
# 不影响主栈：恢复走独立临时容器（docker run + 专用名，用后即删），不触碰 patroni 数据卷。
#
# PowerShell 5.1 兼容：无三元/??/管道链语法。

$ErrorActionPreference = "Stop"

# ---- 路径与常量 ----
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # deploy/scripts -> 仓库根
$ComposeFile = "deploy/docker-compose.staging.yml"
$ConfPath = Join-Path $RepoRoot "deploy/pgbackrest/pgbackrest.conf"
$LogDir = Join-Path $RepoRoot "deploy/logs"
$LogFile = Join-Path $LogDir "backup-verify.log"
$VerifyContainer = "edp-backup-verify"                 # 一次性恢复容器（用后即删）
$VerifyNetwork = "edp-staging_default"                 # compose project name=edp-staging -> 默认网络
$PatroniImage = "edp-staging/patroni:pg16"

Push-Location $RepoRoot
$swTotal = [System.Diagnostics.Stopwatch]::StartNew()
$checkExit = -1; $checkMs = -1; $restoreSec = -1.0; $tenants = -1; $events = -1
$result = "RED"; $failReason = ""
try {
    # ---- 工具函数：跑原生命令捕获输出+退出码（stderr 不致 EAP 抛错）----
    function Invoke-Native {
        param([string[]]$CmdArgs)
        $ErrorActionPreference = "Continue"
        $out = & $CmdArgs[0] $CmdArgs[1..($CmdArgs.Length - 1)] 2>&1 | Out-String
        $code = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        return @{ Out = $out; Exit = $code }
    }

    # ---- [1/3] pgbackrest check（真实 WAL 归档往返）----
    Write-Host "== [1/3] pgbackrest check（patroni1，含 WAL 往返）=="
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-Native @("docker", "compose", "-f", $ComposeFile, "exec", "-T", "patroni1", "pgbackrest", "--stanza=edp", "check")
    $sw.Stop()
    $checkExit = $r.Exit; $checkMs = [int]$sw.ElapsedMilliseconds
    $checkLast = ($r.Out -split "`n" | Where-Object { $_ -match "command end" } | Select-Object -Last 1)
    Write-Host "  check exit=$checkExit 耗时=${checkMs}ms"
    Write-Host "  $($checkLast.Trim())"
    if ($checkExit -ne 0) { $failReason = "check exit=$checkExit"; throw "pgbackrest check 失败" }

    # ---- [2/3] 一次性恢复容器：S3 restore 最新备份集 -> /tmp/verify ----
    Write-Host "== [2/3] 抽样恢复验证：起一次性容器（$VerifyContainer，网络 $VerifyNetwork）=="
    Invoke-Native @("docker", "rm", "-f", $VerifyContainer) | Out-Null
    $r = Invoke-Native @("docker", "run", "-d", "--name", $VerifyContainer,
        "--network", $VerifyNetwork,
        "-v", "${ConfPath}:/etc/pgbackrest/pgbackrest.conf:ro",
        $PatroniImage, "sleep", "infinity")
    if ($r.Exit -ne 0) { $failReason = "docker run 失败"; throw "恢复容器启动失败：$($r.Out)" }
    Start-Sleep -Seconds 1
    Invoke-Native @("docker", "exec", $VerifyContainer, "mkdir", "-p", "/tmp/verify") | Out-Null
    Invoke-Native @("docker", "exec", $VerifyContainer, "chown", "postgres:postgres", "/tmp/verify") | Out-Null

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-Native @("docker", "exec", "-u", "postgres", $VerifyContainer,
        "pgbackrest", "--stanza=edp", "--pg1-path=/tmp/verify", "restore")
    $sw.Stop()
    $restoreSec = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    $setLine = ($r.Out -split "`n" | Where-Object { $_ -match "restore backup set" } | Select-Object -Last 1)
    Write-Host "  restore exit=$($r.Exit) 耗时=${restoreSec}s"
    Write-Host "  $($setLine.Trim())"
    if ($r.Exit -ne 0) { $failReason = "restore exit=$($r.Exit)"; throw "restore 失败（详见上方输出）" }

    # ---- [3/3] 单用户模式断言：platform.tenants 计数非零 ----
    Write-Host "== [3/3] 单用户模式（postgres --single）断言 platform.tenants 非零 =="
    # 注意：PS 5.1 传参不含内嵌双引号（会被剥掉截断 SQL）——SQL 用单引号包（$sql 内无单引号）
    $sql = "select count(*) as tenants from platform.tenants; select count(*) as events from event.events;"
    $shCmd = "printf '%s\n' '$sql' | postgres --single -D /tmp/verify edp"
    $r = Invoke-Native @("docker", "exec", "-i", "-u", "postgres", $VerifyContainer, "sh", "-c", $shCmd)
    if ($r.Out -match 'tenants = "(\d+)"') { $tenants = [int]$Matches[1] }
    if ($r.Out -match 'events = "(\d+)"') { $events = [int]$Matches[1] }
    Write-Host "  恢复库读数：platform.tenants=$tenants / event.events=$events"
    if ($tenants -lt 1) { $failReason = "断言失败 tenants=$tenants"; throw "platform.tenants 计数为 $tenants（应非零）" }

    $result = "GREEN"
    Write-Host "备份验证 GREEN（check ${checkMs}ms + restore ${restoreSec}s + 断言通过）" -ForegroundColor Green
}
catch {
    $result = "RED"
    Write-Host "备份验证 RED：$failReason（$_）" -ForegroundColor Red
}
finally {
    # 拆恢复容器（幂等）；不动主栈任何容器
    $ErrorActionPreference = "Continue"
    & docker rm -f $VerifyContainer *> $null
    $ErrorActionPreference = "Stop"
    $swTotal.Stop()
    # 追加式日志（目录/文件不存在则建）
    if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
    $line = "{0} | {1} | check=exit:{2}({3}ms) | restore={4}s | tenants={5} | events={6} | {7}" -f `
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $result, $checkExit, $checkMs, $restoreSec, $tenants, $events, $result
    if ($result -eq "RED") { $line += " | reason=$failReason" }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host "日志已追加：$LogFile"
    Pop-Location
}

if ($result -eq "GREEN") { exit 0 } else { exit 1 }
