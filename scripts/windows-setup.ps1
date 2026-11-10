param([switch]$WithStreamlit, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$State = Join-Path $Root '.sentinelp2p'

function Fail([string]$Message) { throw "setup: $Message" }
function Get-CommandPath([string]$Name) {
    $item = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $item) { return $null }
    return $item.Source
}
function Test-PythonVersion([string]$Executable) {
    $v = & $Executable -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "Could not run Python at $Executable" }
    $parts = $v.Split('.') | ForEach-Object { [int]$_ }
    if ($parts[0] -lt 3 -or ($parts[0] -eq 3 -and $parts[1] -lt 10)) {
        Fail "Python 3.10+ is required; found $v. No system version was changed."
    }
    return $v
}

$Uv = Get-CommandPath 'uv'
$Node = Get-CommandPath 'node'
$Npm = Get-CommandPath 'npm'
if (-not $Uv) { Fail 'uv is required. Install it manually, then rerun setup.bat.' }
if (-not $Node -or -not $Npm) { Fail 'Node.js 20.19+ or 22.12+ with npm is required. Install it manually; setup will not upgrade the system.' }

$Python = $null
if ($env:VIRTUAL_ENV) { $Python = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe' }
elseif ($env:CONDA_PREFIX) { $Python = Join-Path $env:CONDA_PREFIX 'python.exe' }
elseif (Test-Path (Join-Path $Root '.venv')) {
    $ExistingPython = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path $ExistingPython)) { Fail 'An existing .venv directory has no usable Python. It was left untouched; repair or move it yourself, then rerun setup.' }
    $Python = $ExistingPython
}
else {
    $PythonCommand = Get-CommandPath 'python'
    if (-not $PythonCommand) { $PythonCommand = Get-CommandPath 'py' }
    if (-not $PythonCommand) { Fail 'Python 3.10+ is required. Install it manually; setup will not upgrade system Python.' }
    if ((Split-Path $PythonCommand -Leaf) -eq 'py.exe') {
        $Python = (& $PythonCommand -3 -c 'import sys; print(sys.executable)').Trim()
    } else { $Python = $PythonCommand }
}
if (-not (Test-Path $Python)) { Fail "The selected Python executable does not exist: $Python" }
$PythonVersion = Test-PythonVersion $Python
$NodeVersion = (& $Node --version).Trim().TrimStart('v')
$NodeParts = $NodeVersion.Split('.') | ForEach-Object { [int]$_ }
$NodeOk = ($NodeParts[0] -ge 23) -or ($NodeParts[0] -eq 22 -and $NodeParts[1] -ge 12) -or ($NodeParts[0] -eq 20 -and $NodeParts[1] -ge 19)
if (-not $NodeOk) { Fail "Node.js 20.19+ or 22.12+ is required; found v$NodeVersion. No system version was changed." }
Write-Host "Python: $PythonVersion ($Python)"
Write-Host "Node.js: v$NodeVersion; npm: $(& $Npm --version)"
Write-Host "uv: $(& $Uv --version)"
if ($CheckOnly) { Write-Host 'Prerequisite check complete; no files or environments were changed.'; exit 0 }

if (-not (Test-Path (Join-Path $Root '.env'))) {
    $Example = Join-Path $Root '.env.example'
    if (-not (Test-Path $Example)) { Fail 'Root .env.example is missing; cannot create a safe default configuration.' }
    $EnvPath = Join-Path $Root '.env'
    try {
        $EnvStream = [System.IO.File]::Open($EnvPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $ExampleBytes = [System.IO.File]::ReadAllBytes($Example)
            $EnvStream.Write($ExampleBytes, 0, $ExampleBytes.Length)
        } finally { $EnvStream.Dispose() }
        Write-Host 'Created .env from .env.example because .env did not exist.'
    } catch [System.IO.IOException] {
        if (Test-Path $EnvPath) { Write-Host 'Preserving .env created by another process.' }
        else { throw }
    }
} else { Write-Host 'Preserving existing .env.' }

if (-not $env:VIRTUAL_ENV -and -not $env:CONDA_PREFIX -and -not (Test-Path (Join-Path $Root '.venv'))) {
    $Venv = Join-Path $Root '.venv'
    & $Uv venv --python $Python $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'uv could not create .venv. Existing environments were not removed.' }
    $Python = Join-Path $Venv 'Scripts\python.exe'
}

& $Uv pip install --python $Python -r (Join-Path $Root 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Backend dependency installation failed.' }
if ($WithStreamlit) {
    & $Uv pip install --python $Python -r (Join-Path $Root 'requirements-streamlit.txt')
    if ($LASTEXITCODE -ne 0) { Fail 'Optional Streamlit dependency installation failed.' }
}
& $Npm ci --prefix (Join-Path $Root 'frontend')
if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed.' }
$env:VITE_API_BASE_URL = '/api'
& $Npm run build --prefix (Join-Path $Root 'frontend')
if ($LASTEXITCODE -ne 0) { Fail 'Frontend production build failed.' }

New-Item -ItemType Directory -Path $State -Force | Out-Null
Set-Content -Path (Join-Path $State 'python-path') -Value $Python -Encoding UTF8
Write-Host 'Setup complete. Ollama was not installed, started, or used to download a model.'
if ($WithStreamlit) { Write-Host 'Optional Streamlit dependencies are installed. Start separately with: start.bat -Streamlit' }
Write-Host 'Run the main application with: start.bat'
