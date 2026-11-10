$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Run = Join-Path $Root '.sentinelp2p\run'

function Stop-OwnedProcess([string]$Name, [string]$Needle) {
    $File = Join-Path $Run "$Name.json"
    if (-not (Test-Path $File)) { Write-Host "$Name is not running (no script-owned PID record)."; return }
    try { $Record = Get-Content $File -Raw | ConvertFrom-Json } catch { Write-Host "Invalid $Name PID record; leaving processes untouched."; return }
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.pid)" -ErrorAction SilentlyContinue
    if (-not $Process) { Remove-Item $File -Force; Write-Host "Removed stale $Name PID record."; return }
    $ActualStart = [Management.ManagementDateTimeConverter]::ToDateTime($Process.CreationDate).ToUniversalTime()
    $ExpectedStart = [datetime]::Parse($Record.started).ToUniversalTime()
    if ($Process.CommandLine -notlike "*$Needle*" -or $Process.ExecutablePath -ne $Record.executable -or [math]::Abs(($ActualStart - $ExpectedStart).TotalSeconds) -gt 2) {
        throw "Refusing to stop PID $($Record.pid): it no longer matches this script's $Name process."
    }
    Stop-Process -Id ([int]$Record.pid) -ErrorAction Stop
    try { Wait-Process -Id ([int]$Record.pid) -Timeout 10 -ErrorAction Stop } catch {
        $StillThere = Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.pid)" -ErrorAction SilentlyContinue
        $StillStart = if ($StillThere) { [Management.ManagementDateTimeConverter]::ToDateTime($StillThere.CreationDate).ToUniversalTime() } else { [datetime]::MinValue }
        if ($StillThere -and $StillThere.CommandLine -like "*$Needle*" -and $StillThere.ExecutablePath -eq $Record.executable -and [math]::Abs(($StillStart - $ExpectedStart).TotalSeconds) -le 2) {
            Stop-Process -Id ([int]$Record.pid) -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $File -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $Name (PID $($Record.pid))."
}

Stop-OwnedProcess 'api' 'uvicorn app.main:app'
Stop-OwnedProcess 'streamlit' 'dashboard.py'
