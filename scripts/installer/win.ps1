#Requires -Version 5.1
<#
  MeshNet Windows installer
  Usage:
    iwr https://install.beta.meshnet.co/win.ps1 -UseBasicParsing | iex
    Install-Meshnet -ClaimToken YOUR_TOKEN [-Force] [-SkipService]
#>

$ErrorActionPreference = 'Stop'

$script:MeshnetDir      = if ($env:MESHNET_DIR) { $env:MESHNET_DIR } else { Join-Path $env:USERPROFILE '.meshnet' }
$script:NodeDir         = Join-Path $script:MeshnetDir 'node'
$script:VenvDir         = Join-Path $script:MeshnetDir 'venv'
$script:CredentialsFile = Join-Path $script:MeshnetDir 'credentials'
$script:LogFile         = Join-Path $script:MeshnetDir 'meshnet-node.log'
$script:BackendUrl      = if ($env:MESHNET_BACKEND_URL)      { $env:MESHNET_BACKEND_URL }      else { 'https://api.beta.meshnet.co' }
$script:InstallBaseUrl  = if ($env:MESHNET_INSTALL_BASE_URL) { $env:MESHNET_INSTALL_BASE_URL } else { 'https://install.beta.meshnet.co' }
$script:ModelName       = 'llama3.3:70b-instruct-q4_K_M'

function Write-Log { param([string]$Message) Write-Host "[meshnet] $Message" }
function Fail      { param([string]$Message) Write-Host "[meshnet] ERROR: $Message" -ForegroundColor Red; throw $Message }
function Test-CommandExists { param([string]$Name) [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Ensure-Directory { param([string]$Path) if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

function Test-PythonExe {
  param([string]$Exe, [string[]]$PreArgs = @())
  try {
    $argsList = @()
    if ($PreArgs) { $argsList += $PreArgs }
    $argsList += '--version'
    $out = & $Exe @argsList 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { return $false }
    if ($out -match 'Python\s+3\.') { return $true }
    return $false
  } catch { return $false }
}

function Resolve-PythonCommand {
  $py = Get-Command 'py' -ErrorAction SilentlyContinue
  if ($py -and (Test-PythonExe -Exe $py.Source -PreArgs @('-3'))) {
    return @{ Exe = $py.Source; PreArgs = @('-3') }
  }
  foreach ($name in @('python3','python')) {
    $cands = @(Get-Command $name -All -ErrorAction SilentlyContinue)
    foreach ($c in $cands) {
      $src = $c.Source
      if (-not $src) { continue }
      if ($src -like '*\WindowsApps\*') { continue }
      if (Test-PythonExe -Exe $src) {
        return @{ Exe = $src; PreArgs = @() }
      }
    }
  }
  return $null
}

function Install-PythonViaWinget {
  if (-not (Test-CommandExists 'winget')) { return $false }
  Write-Log 'Installing Python 3.12 via winget (this can take a minute)...'
  try {
    & winget install --silent --accept-source-agreements --accept-package-agreements --exact --id Python.Python.3.12 | Out-Null
  } catch { return $false }
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
  return $true
}

function Get-PythonExe {
  $resolved = Resolve-PythonCommand
  if ($resolved) { return $resolved }
  Write-Log 'No working Python 3 found on PATH. Attempting auto-install via winget...'
  if (Install-PythonViaWinget) {
    $resolved = Resolve-PythonCommand
    if ($resolved) { return $resolved }
  }
  Fail 'Python 3 is required. Install from https://www.python.org/downloads/windows/ (tick "Add Python to PATH") and re-run. If only the Microsoft Store Python alias is present, install the real package from python.org.'
}

function Install-OllamaWindows {
  if (Test-CommandExists 'ollama') {
    Write-Log 'Ollama already installed.'
  } else {
    Write-Log 'Installing Ollama for Windows...'
    $installer = Join-Path $env:TEMP 'OllamaSetup.exe'
    Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $installer -UseBasicParsing
    Start-Process -FilePath $installer -ArgumentList '/SILENT' -Wait
    $ollamaBin = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
    if (Test-Path $ollamaBin) { $env:Path = "$ollamaBin;$env:Path" }
    if (-not (Test-CommandExists 'ollama')) {
      Fail 'Ollama installation failed. Install manually from https://ollama.com/download and re-run.'
    }
  }
  Write-Log "Pulling model $($script:ModelName) (this can take a while)..."
  & ollama pull $script:ModelName
  if ($LASTEXITCODE -ne 0) { Fail "Failed to pull model $($script:ModelName)" }
}

function Get-GpuInfo {
  try {
    $gpus = Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 }
    $primary = $gpus | Sort-Object AdapterRAM -Descending | Select-Object -First 1
    $name = if ($primary) { $primary.Name } else { 'unknown' }
    $vramMib = if ($primary -and $primary.AdapterRAM) { [int]($primary.AdapterRAM / 1MB) } else { 0 }
    return @{ gpu_model = $name; vram_mib = $vramMib; driver = (if ($primary) { $primary.DriverVersion } else { '' }); platform = 'windows'; os = (Get-CimInstance Win32_OperatingSystem).Caption }
  } catch {
    return @{ gpu_model = 'unknown'; vram_mib = 0; platform = 'windows' }
  }
}

function Claim-Node {
  param([string]$ClaimToken, [switch]$Force)
  if ((Test-Path $script:CredentialsFile) -and -not $Force) {
    Write-Log 'Existing credentials found; skipping claim. Pass -Force to re-claim.'
    return
  }
  if ([string]::IsNullOrWhiteSpace($ClaimToken)) {
    Fail 'Missing claim token. Use: Install-Meshnet -ClaimToken YOUR_TOKEN'
  }
  $hostname = [System.Net.Dns]::GetHostName()
  $gpu = Get-GpuInfo
  Write-Log 'Registering node with MeshNet backend...'
  $body = @{ claim_token = $ClaimToken; hostname = $hostname; gpu_info = $gpu } | ConvertTo-Json -Depth 6
  try {
    $resp = Invoke-RestMethod -Uri "$($script:BackendUrl)/api/provider/claim" -Method Post -Body $body -ContentType 'application/json'
  } catch {
    Fail "Claim failed: $($_.Exception.Message)"
  }
  foreach ($key in @('provider_id','node_id','node_secret')) {
    if (-not $resp.PSObject.Properties.Name.Contains($key)) { Fail "Claim response missing field: $key" }
  }
  Ensure-Directory $script:MeshnetDir
  @(
    "PROVIDER_ID=$($resp.provider_id)",
    "NODE_ID=$($resp.node_id)",
    "NODE_SECRET=$($resp.node_secret)"
  ) | Set-Content -Path $script:CredentialsFile -Encoding ASCII
  Write-Log "Credentials saved to $($script:CredentialsFile)."
}

function Update-NodeClient {
  Ensure-Directory $script:NodeDir
  Invoke-WebRequest -Uri "$($script:BackendUrl)/node.py"          -OutFile (Join-Path $script:NodeDir 'node.py')          -UseBasicParsing
  Invoke-WebRequest -Uri "$($script:BackendUrl)/requirements.txt" -OutFile (Join-Path $script:NodeDir 'requirements.txt') -UseBasicParsing
  Write-Log "Node client updated in $($script:NodeDir)."
}

function Install-PythonDeps {
  $py = Get-PythonExe
  $pyExe  = $py.Exe
  $pyArgs = @()
  if ($py.PreArgs) { $pyArgs += $py.PreArgs }
  Write-Log "Creating virtual environment in $($script:VenvDir) (using $pyExe $($pyArgs -join ' '))..."
  $venvArgs = @()
  if ($pyArgs) { $venvArgs += $pyArgs }
  $venvArgs += @('-m','venv',$script:VenvDir)
  & $pyExe @venvArgs
  if ($LASTEXITCODE -ne 0) { Fail "Failed to create virtualenv at $($script:VenvDir)" }
  $venvPy = Join-Path $script:VenvDir 'Scripts\python.exe'
  if (-not (Test-Path $venvPy)) { Fail "Failed to create virtualenv at $($script:VenvDir)" }
  & $venvPy -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) { Fail 'pip upgrade failed' }
  & $venvPy -m pip install -r (Join-Path $script:NodeDir 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { Fail 'pip install -r requirements.txt failed' }
}

function Invoke-NativeQuiet {
  # Run a native command suppressing stderr noise; return @{ ExitCode = N; Output = '...' }
  param([string]$Exe, [string[]]$Args)
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & $Exe @Args 2>&1 | Out-String
    return @{ ExitCode = $LASTEXITCODE; Output = $out }
  } catch {
    return @{ ExitCode = 1; Output = $_.Exception.Message }
  } finally {
    $ErrorActionPreference = $prevEAP
  }
}

function Install-MeshnetService {
  param([switch]$SkipService)
  if ($SkipService -or $env:MESHNET_SKIP_SERVICE -eq '1') { Write-Log 'Skipping service install (MESHNET_SKIP_SERVICE).'; return }
  $venvPy   = Join-Path $script:VenvDir 'Scripts\python.exe'
  $nodePy   = Join-Path $script:NodeDir 'node.py'
  $launcher = Join-Path $script:MeshnetDir 'start-node.cmd'
  $taskName = 'MeshnetNode'

  if (-not (Test-Path -LiteralPath $venvPy)) { Fail "Python not found at $venvPy" }
  if (-not (Test-Path -LiteralPath $nodePy)) { Fail "node.py not found at $nodePy" }

  # Write a self-contained .cmd wrapper. No quoting fragility: just plain batch.
  $launcherBody = @"
@echo off
setlocal
set "MESHNET_API_BASE_URL=$($script:BackendUrl)"
set "MESHNET_CREDENTIALS_FILE=$($script:CredentialsFile)"
set "MESHNET_DIR=$($script:MeshnetDir)"
"$venvPy" "$nodePy" >> "$($script:LogFile)" 2>&1
"@
  Set-Content -LiteralPath $launcher -Value $launcherBody -Encoding ASCII
  Write-Log "Wrote node launcher: $launcher"

  Write-Log "Registering scheduled task '$taskName' (runs at logon)..."
  # Best-effort delete any previous task
  Invoke-NativeQuiet -Exe 'schtasks.exe' -Args @('/Delete','/TN',$taskName,'/F') | Out-Null

  # Create — point /TR at the wrapper script. /TR must be a single token, so we pass it as one quoted arg.
  $trArg = '"' + $launcher + '"'
  $createRes = Invoke-NativeQuiet -Exe 'schtasks.exe' -Args @('/Create','/TN',$taskName,'/SC','ONLOGON','/RL','LIMITED','/F','/TR',$trArg)
  if ($createRes.ExitCode -ne 0) {
    Write-Log "schtasks /Create output: $($createRes.Output.Trim())"
    Fail "Failed to register scheduled task '$taskName' (exit $($createRes.ExitCode)). Try running PowerShell as Administrator."
  }

  # Verify the task actually exists post-create (catches the silent-discard case).
  $verify = Invoke-NativeQuiet -Exe 'schtasks.exe' -Args @('/Query','/TN',$taskName)
  if ($verify.ExitCode -ne 0) {
    Write-Log "schtasks /Query output: $($verify.Output.Trim())"
    Write-Log "Falling back to direct launch (no scheduled task)..."
    # Fallback: start the launcher in the background so the user still gets a running node.
    try {
      Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $launcher) -WindowStyle Hidden | Out-Null
      Write-Log "Node launched directly. Logs: $($script:LogFile)"
      Write-Log "NOTE: scheduled task could not be registered; node will NOT auto-restart at next logon. Re-run installer as Administrator to fix."
      return
    } catch {
      Fail "Scheduled task did not persist after /Create and direct launch also failed: $($_.Exception.Message)"
    }
  }

  # Start now — non-fatal if it can't start immediately
  $runRes = Invoke-NativeQuiet -Exe 'schtasks.exe' -Args @('/Run','/TN',$taskName)
  if ($runRes.ExitCode -ne 0) {
    Write-Log "Scheduled task registered but did not start now (exit $($runRes.ExitCode)). It will run at next logon. Falling back to direct launch for this session..."
    try {
      Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $launcher) -WindowStyle Hidden | Out-Null
      Write-Log "Node launched directly. Logs: $($script:LogFile)"
    } catch {
      Write-Log "Direct launch failed: $($_.Exception.Message). Log out and back in to start the task."
    }
  } else {
    Write-Log "Scheduled task started. Logs: $($script:LogFile)"
  }
}

function Confirm-Heartbeat {
  Write-Log 'Confirming backend heartbeat...'
  Start-Sleep -Seconds 5
  try {
    Invoke-RestMethod -Uri "$($script:BackendUrl)/api/node/heartbeat" -Method Post -TimeoutSec 15 -Body '{}' -ContentType 'application/json' | Out-Null
    Write-Log 'Heartbeat OK.'
  } catch {
    Write-Log "Heartbeat not confirmed yet; the service may still be starting. Check $($script:LogFile)."
  }
}

function Install-Meshnet {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$false)] [string]$ClaimToken = '',
    [switch]$Force,
    [switch]$SkipService
  )
  if ([string]::IsNullOrWhiteSpace($ClaimToken) -and $env:MESHNET_CLAIM_TOKEN) { $ClaimToken = $env:MESHNET_CLAIM_TOKEN }
  Ensure-Directory $script:MeshnetDir
  Ensure-Directory $script:NodeDir
  Write-Log "MeshNet directory: $($script:MeshnetDir)"
  Write-Log "Backend URL:       $($script:BackendUrl)"
  Install-OllamaWindows
  Claim-Node -ClaimToken $ClaimToken -Force:$Force
  Update-NodeClient
  Install-PythonDeps
  Install-MeshnetService -SkipService:$SkipService
  Confirm-Heartbeat
  Write-Log 'Done. Your MeshNet node is registered and running.'
  Write-Log 'Dashboard: https://beta.meshnet.co/host-dashboard.html'
}

# When piped through iex, the function is defined but not invoked.
# Run: Install-Meshnet -ClaimToken <token>
