# EDP 试运行巡检（W6 T13，EDP-035）
#
# 用法（仓库根目录）：
#   powershell -File deploy/scripts/trial-patrol.ps1
#   powershell -File deploy/scripts/trial-patrol.ps1 -Cycles 3 -IntervalMin 30
#
# 巡检项（每周期一轮，TSV 追加 deploy/logs/trial-run.log）：
#   1. GET /healthz                —— 无认证探活；非 200 = P0（服务不可用）
#   2. GET /health?deep=true       —— 深层健康；status != ok = P0；HTTP != 200 = P1
#   3. GET /admin/outbox/status    —— 积压计数；HTTP != 200 = P1；
#                                      pending 跨周期单调增长 = P1（worker 停摆嫌疑）
#   4. GET /admin/quality/coverage —— 覆盖简报；HTTP != 200 = P2
#   5. outbox last_published_at 推进 —— 有积压且不推进 = P1
#
# 缺陷分级（写进 docs/demo/w6-trial-run.md 协议）：
#   P0=服务不可用/数据丢失/安全越权；P1=核心接口 5xx/功能不可用/积压失控；
#   P2=体验缺陷/次要端点异常；P3=建议。
# 收口口径：连续 N>=3 个周期 0 P0/0 P1 = 等价证据（W5「连续 3 天」先例）。
#
# PowerShell 5.1 兼容：无三元/??/管道链语法。

param(
    [string]$BaseUrl = "http://localhost:18010",
    [int]$Cycles = 3,
    [int]$IntervalMin = 30,
    [string]$AdminUser = "admin",
    [string]$AdminPass = "Admin@123!",
    [string]$OutLog = "deploy/logs/trial-run.log"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$OutLogPath = Join-Path $RepoRoot $OutLog

function Invoke-Probe {
    # 返回 @{ Code=<int>; Ms; Body=object }
    param([string]$Method, [string]$Url, [hashtable]$Headers = @{}, [string]$Body = $null, [int]$TimeoutSec = 5)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $params = @{
            Uri = $Url
            Method = $Method
            UseBasicParsing = $true
            TimeoutSec = $TimeoutSec
            Headers = $Headers
        }
        if (-not [string]::IsNullOrEmpty($Body)) {
            $params["Body"] = $Body
            $params["ContentType"] = "application/json"
        }
        $resp = Invoke-WebRequest @params
        $sw.Stop()
        $parsed = $null
        try { $parsed = $resp.Content | ConvertFrom-Json } catch { }
        return @{ Code = [int]$resp.StatusCode; Ms = [int]$sw.ElapsedMilliseconds; Body = $parsed }
    } catch {
        $sw.Stop()
        $code = -1
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return @{ Code = $code; Ms = [int]$sw.ElapsedMilliseconds; Body = $null }
    }
}

function Add-Line {
    param([string]$Line)
    $dir = Split-Path -Parent $OutLogPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Add-Content -LiteralPath $OutLogPath -Value $Line -Encoding UTF8
    Write-Output $Line
}

# ---- 登录（取 token）----
$loginBody = '{"username":"' + $AdminUser + '","password":"' + $AdminPass + '"}'
$login = Invoke-Probe -Method "POST" -Url "$BaseUrl/api/v1/auth/login" -Body $loginBody
if ($login.Code -ne 200 -or $login.Body -eq $null) {
    Add-Line ("{0}`tcycle=0`tlogin`thttp={1}`tverdict=P0" -f (Get-Date -Format "s"), $login.Code)
    throw "登录失败（http=$($login.Code)）——栈是否就绪？"
}
$token = $login.Body.access_token
$headers = @{ Authorization = "Bearer $token" }

Add-Line ("{0}`tcycle=0`tpatrol-start`tbase={1}`tcycles={2}`tinterval_min={3}" -f (Get-Date -Format "s"), $BaseUrl, $Cycles, $IntervalMin)

$prevPending = $null
$prevPublished = $null
$cleanCycles = 0
$cycleResults = @()

for ($i = 1; $i -le $Cycles; $i++) {
    $cycleVerdict = "OK"
    $ts = Get-Date -Format "s"

    # 1. /healthz
    $h = Invoke-Probe -Method "GET" -Url "$BaseUrl/healthz"
    $v = "OK"; if ($h.Code -ne 200) { $v = "P0" }
    Add-Line ("{0}`tcycle={1}`thealthz`thttp={2}`tms={3}`tverdict={4}" -f $ts, $i, $h.Code, $h.Ms, $v)
    if ($v -eq "P0") { $cycleVerdict = "P0" }

    # 2. /health?deep=true
    $d = Invoke-Probe -Method "GET" -Url "$BaseUrl/api/v1/health?deep=true" -Headers $headers
    $v = "OK"
    if ($d.Code -ne 200) { $v = "P1" }
    elseif ($d.Body -ne $null -and $d.Body.status -ne "ok") { $v = "P0" }
    Add-Line ("{0}`tcycle={1}`thealth_deep`thttp={2}`tms={3}`tstatus={4}`tverdict={5}" -f $ts, $i, $d.Code, $d.Ms, $d.Body.status, $v)
    if ($v -eq "P0") { $cycleVerdict = "P0" } elseif ($v -eq "P1" -and $cycleVerdict -eq "OK") { $cycleVerdict = "P1" }

    # 3. outbox status
    $o = Invoke-Probe -Method "GET" -Url "$BaseUrl/api/v1/admin/outbox/status" -Headers $headers
    $pending = -1
    if ($o.Body -ne $null) { $pending = [int]$o.Body.pending_count }
    $v = "OK"
    if ($o.Code -ne 200) { $v = "P1" }
    elseif ($prevPending -ne $null -and $pending -gt $prevPending) { $v = "P1" }
    $published = ""
    if ($o.Body -ne $null -and $o.Body.last_published_at -ne $null) { $published = $o.Body.last_published_at }
    Add-Line ("{0}`tcycle={1}`toutbox_status`thttp={2}`tpending={3}`tlast_published={4}`tverdict={5}" -f $ts, $i, $o.Code, $pending, $published, $v)
    if ($v -eq "P1" -and $cycleVerdict -eq "OK") { $cycleVerdict = "P1" }

    # 4. quality coverage
    $c = Invoke-Probe -Method "GET" -Url "$BaseUrl/api/v1/admin/quality/coverage" -Headers $headers
    $v = "OK"; if ($c.Code -ne 200) { $v = "P2" }
    Add-Line ("{0}`tcycle={1}`tquality_coverage`thttp={2}`tms={3}`tverdict={4}" -f $ts, $i, $c.Code, $c.Ms, $v)
    if ($v -eq "P2" -and $cycleVerdict -eq "OK") { $cycleVerdict = "P2" }

    # 5. worker 推进（有积压且 last_published 不推进 = P1）
    if ($pending -gt 0 -and $prevPublished -ne $null -and $published -eq $prevPublished) {
        Add-Line ("{0}`tcycle={1}`tworker_progress`tpending={2}`tstalled=true`tverdict=P1" -f $ts, $i, $pending)
        if ($cycleVerdict -eq "OK") { $cycleVerdict = "P1" }
    }

    $cycleResults += $cycleVerdict
    if ($cycleVerdict -eq "OK") { $cleanCycles = $cleanCycles + 1 }
    $prevPending = $pending
    $prevPublished = $published

    if ($i -lt $Cycles) { Start-Sleep -Seconds ($IntervalMin * 60) }
}

$summary = "clean=$cleanCycles/$Cycles; verdicts=" + ($cycleResults -join ",")
Add-Line ("{0}`tcycle=end`t{1}`tverdict={2}" -f (Get-Date -Format "s"), $summary, $(if ($cleanCycles -eq $Cycles) { "PASS" } else { "FAIL" }))
if ($cleanCycles -eq $Cycles) { exit 0 } else { exit 1 }
