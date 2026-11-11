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

# Installs the Ollama runtime WITHOUT blocking. It used to download Ollama and
# then pull the ~40 GB model before the node was even registered, so a new
# provider waited hours (or failed on disk space) and never showed up. Now the
# install runs in a hidden background process and the node agent (node.py)
# pulls the model itself once Ollama is there, while already online.
# The one-click Windows app calls this function first, so it must return fast.
function Install-OllamaWindows {
  $ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
  if ((Test-CommandExists 'ollama') -or (Test-Path -LiteralPath $ollamaExe)) {
    Write-Log 'Ollama already installed. Your node will download the AI model in the background once it is online.'
    return
  }
  Write-Log 'Installing Ollama in the background. Your node will come online first and download the AI model afterwards.'
  $installer = (Join-Path $env:TEMP 'OllamaSetup.exe').Replace("'", "''")
  $bg = "`$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '$installer' -UseBasicParsing; Start-Process -FilePath '$installer' -ArgumentList '/VERYSILENT','/NORESTART','/SUPPRESSMSGBOXES' -Wait } catch { }"
  try {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-Command',$bg) | Out-Null
  } catch {
    Write-Log "Could not start the Ollama install ($($_.Exception.Message)). Install it from https://ollama.com/download; your node will pick it up."
  }
}

function Get-GpuInfo {
  # nvidia-smi first: Win32_VideoController.AdapterRAM is a 32-bit value and
  # reports any card over 4 GB (an RTX 4090 included) as 4095 MB, which made
  # every Windows GPU look too small for jobs.
  try {
    $smi = $null
    $cmd = Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue
    if ($cmd) { $smi = $cmd.Source }
    else {
      $p = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'
      if (Test-Path -LiteralPath $p) { $smi = $p }
    }
    if ($smi) {
      $line = (& $smi --query-gpu=memory.total,name,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
      if ($line) {
        $parts = $line -split ',\s*', 3
        return @{ gpu_model = $parts[1].Trim(); vram_mib = [int]$parts[0].Trim(); driver = $parts[2].Trim(); platform = 'windows'; os = (Get-CimInstance Win32_OperatingSystem).Caption }
      }
    }
  } catch { }
  try {
    $gpus = Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 }
    $primary = $gpus | Sort-Object AdapterRAM -Descending | Select-Object -First 1
    $name = if ($primary) { $primary.Name } else { 'unknown' }
    $vramMib = if ($primary -and $primary.AdapterRAM) { [int]($primary.AdapterRAM / 1MB) } else { 0 }
    return @{ gpu_model = $name; vram_mib = $vramMib; driver = $(if ($primary) { $primary.DriverVersion } else { '' }); platform = 'windows'; os = (Get-CimInstance Win32_OperatingSystem).Caption }
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
  Invoke-WebRequest -Uri "$($script:BackendUrl)/node.py" -OutFile (Join-Path $script:NodeDir 'node.py') -UseBasicParsing
  # The node agent needs only these two packages. The server's requirements.txt
  # (FastAPI, Stripe, Redis, ...) made setup slow and could fail to build.
  @('ollama','requests') | Set-Content -Path (Join-Path $script:NodeDir 'requirements.txt') -Encoding ASCII
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
  $hidden   = Join-Path $script:MeshnetDir 'start-node-hidden.vbs'

  if (-not (Test-Path -LiteralPath $venvPy)) { Fail "Python not found at $venvPy" }
  if (-not (Test-Path -LiteralPath $nodePy)) { Fail "node.py not found at $nodePy" }

  # Write a self-contained .cmd wrapper. No quoting fragility: just plain batch.
  $launcherBody = @"
@echo off
setlocal
set "MESHNET_API_BASE_URL=$($script:BackendUrl)"
set "MESHNET_CREDENTIALS_FILE=$($script:CredentialsFile)"
set "MESHNET_DIR=$($script:MeshnetDir)"
set "PYTHONUNBUFFERED=1"
"$venvPy" "$nodePy" >> "$($script:LogFile)" 2>&1
"@
  Set-Content -LiteralPath $launcher -Value $launcherBody -Encoding ASCII
  # Runs the .cmd with no window at all.
  $vbsPath = $launcher.Replace('"', '""')
  Set-Content -LiteralPath $hidden -Value "CreateObject(""WScript.Shell"").Run """"""$vbsPath"""""", 0, False" -Encoding ASCII
  Write-Log "Wrote node launcher: $launcher"

  # Start at logon from the user's Startup folder. The scheduled task this
  # used to create was reported as started but was missing afterwards on
  # real machines (schtasks: "cannot find the file specified"), so the node
  # never ran in the background. The Startup folder needs no admin rights.
  Invoke-NativeQuiet -Exe 'schtasks.exe' -Args @('/Delete','/TN','MeshnetNode','/F') | Out-Null
  try {
    $startup = [Environment]::GetFolderPath('Startup')
    Ensure-Directory $startup
    Copy-Item -LiteralPath $hidden -Destination (Join-Path $startup 'MeshNet Node.vbs') -Force
    Write-Log 'The node will start automatically when you sign in to Windows.'
  } catch {
    Write-Log "Could not add the node to Startup ($($_.Exception.Message)); start it after a restart with: wscript `"$hidden`""
  }

  # Stop a node agent that is already running (an older install), then start
  # the fresh one in the background now.
  try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and $_.CommandLine -like '*\.meshnet\node\node.py*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  } catch { }
  try {
    Start-Process -FilePath 'wscript.exe' -ArgumentList @("`"$hidden`"") | Out-Null
    Write-Log "Node agent started in the background. Logs: $($script:LogFile)"
  } catch {
    Fail "Could not start the node agent: $($_.Exception.Message)"
  }
}

function Confirm-Heartbeat {
  Write-Log 'Confirming backend heartbeat...'
  Start-Sleep -Seconds 5
  try {
    # The heartbeat needs the node's own credentials; without them it was
    # always refused, so this step never confirmed anything.
    $creds = @{}
    Get-Content -LiteralPath $script:CredentialsFile | ForEach-Object {
      $pair = $_ -split '=', 2
      if ($pair.Count -eq 2) { $creds[$pair[0].Trim()] = $pair[1].Trim() }
    }
    $headers = @{ 'X-Node-Id' = $creds['NODE_ID']; 'X-Node-Secret' = $creds['NODE_SECRET'] }
    $body = @{ hostname = [System.Net.Dns]::GetHostName(); gpu_info = (Get-GpuInfo) } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri "$($script:BackendUrl)/api/node/heartbeat" -Method Post -Headers $headers -TimeoutSec 15 -Body $body -ContentType 'application/json' | Out-Null
    Write-Log 'Heartbeat OK. Your node is online.'
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
  # Register first so the node shows up within minutes; the model download
  # (tens of GB) happens afterwards in the background.
  Claim-Node -ClaimToken $ClaimToken -Force:$Force
  Update-NodeClient
  Install-PythonDeps
  Install-MeshnetService -SkipService:$SkipService
  Confirm-Heartbeat
  Install-OllamaWindows
  Write-Log 'Done. Your MeshNet node is registered and running.'
  Write-Log 'It downloads the AI model in the background and starts taking jobs when that finishes.'
  Write-Log 'Dashboard: https://beta.meshnet.co/host-dashboard.html'
}

# When piped through iex, the function is defined but not invoked.
# Run: Install-Meshnet -ClaimToken <token>
