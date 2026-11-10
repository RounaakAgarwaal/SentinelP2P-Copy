param([switch]$Streamlit)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$State = Join-Path $Root '.sentinelp2p'
$Run = Join-Path $State 'run'
$Logs = Join-Path $State 'logs'

function Fail([string]$Message) { throw "start: $Message" }
function Test-PortBusy([int]$Port) {
    $Client = [System.Net.Sockets.TcpClient]::new()
    try { $Task = $Client.ConnectAsync('127.0.0.1', $Port); return $Task.Wait(250) -and $Client.Connected }
    catch { return $false }
    finally { $Client.Dispose() }
}
function Get-SavedProcess([string]$Name, [string]$Needle) {
    $File = Join-Path $Run "$Name.json"
    if (-not (Test-Path $File)) { return $null }
    try { $Record = Get-Content $File -Raw | ConvertFrom-Json } catch { return $null }
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.pid)" -ErrorAction SilentlyContinue
    if (-not $Process -or $Process.CommandLine -notlike "*$Needle*" -or $Process.ExecutablePath -ne $Record.executable) { return $null }
    $ActualStart = [Management.ManagementDateTimeConverter]::ToDateTime($Process.CreationDate).ToUniversalTime()
    $ExpectedStart = [datetime]::Parse($Record.started).ToUniversalTime()
    if ([math]::Abs(($ActualStart - $ExpectedStart).TotalSeconds) -gt 2) { return $null }
    return $Process
}

if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) { Fail 'Production frontend is missing. Run setup.bat first.' }
$PythonFile = Join-Path $State 'python-path'
if (-not (Test-Path $PythonFile)) { Fail 'Python environment is not configured. Run setup.bat first.' }
$Python = (Get-Content $PythonFile -Raw).Trim()
if (-not (Test-Path $Python)) { Fail "Configured Python is unavailable: $Python. Rerun setup.bat in the intended environment." }
New-Item -ItemType Directory -Path $Run,$Logs -Force | Out-Null
$ApiHost = if ($env:SENTINEL_API_HOST) { $env:SENTINEL_API_HOST } else { '127.0.0.1' }
$ApiPort = if ($env:SENTINEL_API_PORT) { [int]$env:SENTINEL_API_PORT } else { 8000 }
$StreamlitPort = if ($env:SENTINEL_STREAMLIT_PORT) { [int]$env:SENTINEL_STREAMLIT_PORT } else { 8501 }
if ($ApiPort -lt 1 -or $ApiPort -gt 65535) { Fail 'SENTINEL_API_PORT must be an integer from 1 to 65535.' }
if ($Streamlit -and ($StreamlitPort -lt 1 -or $StreamlitPort -gt 65535)) { Fail 'SENTINEL_STREAMLIT_PORT must be an integer from 1 to 65535.' }
$ApiExisting = Get-SavedProcess 'api' 'uvicorn app.main:app'
$ApiAlreadyRunning = [bool]$ApiExisting
if ($ApiExisting -and ($ApiExisting.CommandLine -notlike "*--host $ApiHost*" -or $ApiExisting.CommandLine -notlike "*--port $ApiPort*")) {
    Fail 'FastAPI was started by these scripts with different host/port settings. Run stop.bat before changing them.'
}
if (-not $ApiAlreadyRunning -and (Test-PortBusy $ApiPort)) { Fail "Port $ApiPort is already in use. Stop that service or set SENTINEL_API_PORT to another free port." }
$StreamlitAlreadyRunning = [bool](Get-SavedProcess 'streamlit' 'dashboard.py')
if ($Streamlit) {
    & $Python -c 'import streamlit' 2>$null
    if ($LASTEXITCODE -ne 0) { Fail 'Streamlit is not installed. Run setup.bat -WithStreamlit first.' }
    if (-not $StreamlitAlreadyRunning -and (Test-PortBusy $StreamlitPort)) { Fail "Port $StreamlitPort is in use. Set SENTINEL_STREAMLIT_PORT to a free port." }
}

$LogStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ApiOut = Join-Path $Logs "api-$LogStamp.out.log"
$ApiErr = Join-Path $Logs "api-$LogStamp.err.log"
if (-not $ApiAlreadyRunning) {
    $OldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $Root 'backend'
    $ApiArguments = "-m uvicorn app.main:app --host $ApiHost --port $ApiPort"
    $ApiProcess = Start-Process -FilePath $Python -ArgumentList $ApiArguments -WorkingDirectory $Root -PassThru -RedirectStandardOutput $ApiOut -RedirectStandardError $ApiErr
    $env:PYTHONPATH = $OldPythonPath
    $ApiRecord = @{ pid = $ApiProcess.Id; executable = $Python; started = $ApiProcess.StartTime.ToUniversalTime().ToString('o'); stdout = $ApiOut; stderr = $ApiErr }
    $ApiRecord | ConvertTo-Json | Set-Content (Join-Path $Run 'api.json') -Encoding UTF8
} else {
    $ApiRecord = Get-Content (Join-Path $Run 'api.json') -Raw | ConvertFrom-Json
    $ApiProcess = Get-Process -Id ([int]$ApiRecord.pid)
    if ($ApiRecord.stdout) { $ApiOut = $ApiRecord.stdout }
    if ($ApiRecord.stderr) { $ApiErr = $ApiRecord.stderr }
}

$Ready = $false
for ($i=0; $i -lt 40; $i++) {
    if ($ApiProcess.HasExited) { break }
    try { $Response = Invoke-WebRequest "http://${ApiHost}:$ApiPort/api/health" -TimeoutSec 1; if ($Response.StatusCode -eq 200) { $Ready = $true; break } } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $Ready) {
    if (-not $ApiAlreadyRunning) {
        $OwnedApi = Get-SavedProcess 'api' 'uvicorn app.main:app'
        if ($OwnedApi) { Stop-Process -Id $OwnedApi.ProcessId -Force -ErrorAction SilentlyContinue }
        Remove-Item (Join-Path $Run 'api.json') -Force -ErrorAction SilentlyContinue
    }
    Get-Content $ApiErr -Tail 30 -ErrorAction SilentlyContinue | Write-Host
    Fail "FastAPI failed to become healthy. Inspect $ApiErr"
}

if ($Streamlit -and -not $StreamlitAlreadyRunning) {
    $StreamOut = Join-Path $Logs "streamlit-$LogStamp.out.log"
    $StreamErr = Join-Path $Logs "streamlit-$LogStamp.err.log"
    $Dashboard = Join-Path $Root 'dashboard.py'
    $StreamArguments = "-m streamlit run `"$Dashboard`" --server.address 127.0.0.1 --server.port $StreamlitPort --server.headless true"
    $StreamProcess = Start-Process -FilePath $Python -ArgumentList $StreamArguments -WorkingDirectory $Root -PassThru -RedirectStandardOutput $StreamOut -RedirectStandardError $StreamErr
    @{ pid = $StreamProcess.Id; executable = $Python; started = $StreamProcess.StartTime.ToUniversalTime().ToString('o'); stdout = $StreamOut; stderr = $StreamErr } | ConvertTo-Json | Set-Content (Join-Path $Run 'streamlit.json') -Encoding UTF8
    $StreamReady = $false
    for ($i=0; $i -lt 30; $i++) {
        if ($StreamProcess.HasExited) { break }
        if (Test-PortBusy $StreamlitPort) { $StreamReady = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $StreamReady) {
        $OwnedStreamlit = Get-SavedProcess 'streamlit' 'dashboard.py'
        if ($OwnedStreamlit) { Stop-Process -Id $OwnedStreamlit.ProcessId -Force -ErrorAction SilentlyContinue }
        Remove-Item (Join-Path $Run 'streamlit.json') -Force -ErrorAction SilentlyContinue
        Get-Content $StreamErr -Tail 30 -ErrorAction SilentlyContinue | Write-Host
        Fail "Streamlit failed to open port $StreamlitPort. Inspect $StreamErr"
    }
    Write-Host "Optional Streamlit dashboard: http://127.0.0.1:$StreamlitPort"
}
Write-Host "SentinelP2P is ready: http://${ApiHost}:$ApiPort"
Write-Host "API logs: $ApiOut and $ApiErr"
Write-Host 'Stop with: stop.bat'
