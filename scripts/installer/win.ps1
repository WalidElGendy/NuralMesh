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

function Get-PythonExe {
  if (Test-CommandExists 'python')  { return 'python' }
  if (Test-CommandExists 'python3') { return 'python3' }
  if (Test-CommandExists 'py')      { return 'py -3' }
  Fail 'Python 3 is required. Install from https://www.python.org/downloads/windows/ and re-run.'
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
  Write-Log "Creating virtual environment in $($script:VenvDir)..."
  if ($py -eq 'py -3') { & py -3 -m venv $script:VenvDir } else { & $py -m venv $script:VenvDir }
  $venvPy = Join-Path $script:VenvDir 'Scripts\python.exe'
  if (-not (Test-Path $venvPy)) { Fail "Failed to create virtualenv at $($script:VenvDir)" }
  & $venvPy -m pip install --upgrade pip
  & $venvPy -m pip install -r (Join-Path $script:NodeDir 'requirements.txt')
}

function Install-MeshnetService {
  param([switch]$SkipService)
  if ($SkipService -or $env:MESHNET_SKIP_SERVICE -eq '1') {
    Write-Log 'Skipping service install (MESHNET_SKIP_SERVICE).'
    return
  }
  $venvPy = Join-Path $script:VenvDir 'Scripts\python.exe'
  $nodePy = Join-Path $script:NodeDir 'node.py'
  $taskName = 'MeshnetNode'
  $envBlock = "`$env:MESHNET_API_BASE_URL='$($script:BackendUrl)'; `$env:MESHNET_CREDENTIALS_FILE='$($script:CredentialsFile)';"
  $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `"$envBlock & '$venvPy' '$nodePy' *>> '$($script:LogFile)'`""
  Write-Log "Registering scheduled task '$taskName' (runs at logon)..."
  schtasks.exe /Delete /TN $taskName /F 2>$null | Out-Null
  schtasks.exe /Create /TN $taskName /SC ONLOGON /RL LIMITED /F /TR $cmd | Out-Null
  schtasks.exe /Run    /TN $taskName | Out-Null
  Write-Log "Scheduled task started. Logs: $($script:LogFile)"
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
  Write-Log 'Dashboard: https://beta.meshnet.co/host/dashboard'
}

# When piped through iex, the function is defined but not invoked.
# Run: Install-Meshnet -ClaimToken <token>
