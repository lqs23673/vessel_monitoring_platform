param(
    [ValidateSet("menu", "start", "stop", "restart", "status")]
    [string]$Action = "menu",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$PlatformRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PowerShellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$PlatformUrl = "http://127.0.0.1:5173"
$ApiUrl = "http://127.0.0.1:8010"

function Test-PlatformApi {
    try {
        $identity = Invoke-RestMethod "$ApiUrl/" -TimeoutSec 3
        return $identity.service -eq "VesselSight Operations API"
    } catch { return $false }
}

function Test-PlatformWeb {
    try {
        $page = Invoke-WebRequest $PlatformUrl -UseBasicParsing -TimeoutSec 3
        return $page.StatusCode -eq 200 -and $page.Content -match "VesselSight"
    } catch { return $false }
}

function Invoke-PlatformScript {
    param([string]$Name, [string[]]$ScriptArguments = @())
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $Name) @ScriptArguments
    if ($LASTEXITCODE -ne 0) { throw "操作未完成，请查看上方信息及 data\logs 中的日志。" }
}

function Find-Conda {
    foreach ($candidate in @($env:CONDA_EXE, "C:\python\Anaconda3-2024.10-1-Windows-x86_64\Scripts\conda.exe")) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    $command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "未找到 Conda，请检查本机 Conda 安装及 Train 环境。"
}

function Stop-Platform {
    if (Test-PlatformApi) {
        Write-Host "正在停止采集，等待当前录像保存……"
        $null = Invoke-RestMethod "$ApiUrl/api/realtime/camera/stop" -Method Post -TimeoutSec 15
        $null = Invoke-RestMethod "$ApiUrl/api/realtime/local-video/stop" -Method Post -TimeoutSec 15
        $deadline = (Get-Date).AddSeconds(120)
        $quietChecks = 0
        do {
            $recording = Invoke-RestMethod "$ApiUrl/api/recording/status" -TimeoutSec 8
            $pending = 0
            $pageNumber = 1
            do {
                $list = Invoke-RestMethod "$ApiUrl/api/recordings?page=$pageNumber&page_size=100" -TimeoutSec 8
                $pending += @($list.items | Where-Object { $_.status -in @("recording", "processing") }).Count
                $pageNumber++
            } while (($pageNumber - 1) * 100 -lt $list.total)
            if (-not $recording.active_id -and $pending -eq 0) { $quietChecks++ } else { $quietChecks = 0 }
            if ($quietChecks -ge 2) { break }
            if ((Get-Date) -ge $deadline) { throw "录像仍在保存，平台暂未关闭。请稍后再次选择关闭平台。" }
            Start-Sleep -Seconds 1
        } while ($true)
    }
    Invoke-PlatformScript "stop-dev.ps1"
    Write-Host "平台已关闭。摄像头和录像设置已保留，下次启动会自动恢复。" -ForegroundColor Green
}

function Start-Platform {
    $apiReady = Test-PlatformApi
    $webReady = Test-PlatformWeb
    if ($apiReady -and $webReady) {
        Write-Host "平台已经运行，无需重复启动。" -ForegroundColor Green
    } else {
        if ($apiReady -or $webReady) {
            Write-Host "检测到部分服务仍在运行，正在关闭后重新启动。"
            Stop-Platform
        }
        Write-Host "正在启动平台、GPU 推理和摄像头采集，请稍候……"
        Invoke-PlatformScript "start-dev.ps1" @("-CondaExe", (Find-Conda), "-Environment", "Train")
        Write-Host "平台已启动：$PlatformUrl" -ForegroundColor Green
    }
    if (-not $NoBrowser) { Start-Process $PlatformUrl }
}

function Show-PlatformStatus {
    Invoke-PlatformScript "status.ps1"
    if (Test-PlatformApi) {
        $camera = Invoke-RestMethod "$ApiUrl/api/realtime/camera" -TimeoutSec 8
        $recording = Invoke-RestMethod "$ApiUrl/api/recording/status" -TimeoutSec 8
        Write-Host "摄像头状态：$($camera.status)；已采集帧数：$($camera.frame_id)"
        Write-Host "录像状态：$($recording.state)（armed 表示已开启，等待船舶触发）"
    }
}

function Invoke-Action {
    param([string]$SelectedAction)
    switch ($SelectedAction) {
        "start" { Start-Platform }
        "stop" { Stop-Platform }
        "restart" { Stop-Platform; Start-Platform }
        "status" { Show-PlatformStatus }
    }
}

if ($Action -ne "menu") {
    try { Invoke-Action $Action; exit 0 }
    catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
}

while ($true) {
    Write-Host ""
    Write-Host "========== VesselSight 船舶监测平台 ==========" -ForegroundColor Cyan
    Write-Host "  1. 启动平台并打开页面"
    Write-Host "  2. 关闭平台"
    Write-Host "  3. 查看运行状态"
    Write-Host "  4. 重新启动平台"
    Write-Host "  0. 退出启动器（平台保持当前状态）"
    $choice = Read-Host "请输入数字"
    if ($choice -eq "0") { exit 0 }
    $selected = switch ($choice) { "1" { "start" }; "2" { "stop" }; "3" { "status" }; "4" { "restart" } }
    if (-not $selected) { Write-Host "请输入 0 到 4。"; continue }
    try { Invoke-Action $selected }
    catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    $null = Read-Host "按回车返回菜单"
}
