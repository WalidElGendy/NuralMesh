#!/usr/bin/env bash
set -Eeuo pipefail

MODEL_NAME="llama3.3:70b-instruct-q4_K_M"
MIN_VRAM_MIB=22528
MESHNET_DIR="${MESHNET_DIR:-$HOME/.meshnet}"
NODE_DIR="$MESHNET_DIR/node"
VENV_DIR="$MESHNET_DIR/venv"
CREDENTIALS_FILE="$MESHNET_DIR/credentials"
LOG_FILE="$MESHNET_DIR/meshnet-node.log"
BACKEND_URL="${MESHNET_BACKEND_URL:-https://api.beta.meshnet.co}"
INSTALL_BASE_URL="${MESHNET_INSTALL_BASE_URL:-https://install.beta.meshnet.co}"
CLAIM_TOKEN=""
DEV_MODE=0
FORCE_RECLAIM=0
TMP_DIR=""

usage() {
  echo "Usage: install.sh [--claim-token TOKEN] [--dev] [--force-reclaim]"
}

log() {
  printf '[meshnet] %s\n' "$*"
}

fail() {
  printf '[meshnet] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local exit_code=$?
  if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
  if [[ $exit_code -ne 0 ]]; then
    log "Install failed. Temporary files cleaned up; existing MeshNet config was left intact."
  fi
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claim-token)
      CLAIM_TOKEN="${2:-}"
      shift 2
      ;;
    --dev)
      DEV_MODE=1
      shift
      ;;
    --force-reclaim)
      FORCE_RECLAIM=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

detect_os() {
  local uname_s
  uname_s="$(uname -s)"
  case "$uname_s" in
    Linux)
      if rg -qi microsoft /proc/version 2>/dev/null || grep -qi microsoft /proc/version 2>/dev/null; then
        OS_KIND="wsl"
      else
        OS_KIND="linux"
      fi
      ;;
    Darwin)
      OS_KIND="macos"
      ;;
    MINGW*|MSYS*|CYGWIN*)
      fail "Native Windows is not supported yet. Install WSL2 first: https://learn.microsoft.com/windows/wsl/install"
      ;;
    *)
      fail "Unsupported OS: $uname_s"
      ;;
  esac
  log "Detected OS: $OS_KIND"
}

check_commands() {
  command -v curl >/dev/null 2>&1 || fail "curl is required."
  command -v python3 >/dev/null 2>&1 || fail "python3 is required."
}

check_disk() {
  local available_kib
  available_kib="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
  if [[ "${available_kib:-0}" -lt 209715200 && "$DEV_MODE" -ne 1 ]]; then
    fail "At least 200GB free disk is required for model + cache. Re-run with --dev only for local installer testing."
  fi
  log "Disk check passed."
}

check_gpu() {
  if [[ "$DEV_MODE" -eq 1 ]]; then
    log "Developer mode enabled; accepting this machine for installer testing."
    return
  fi
  command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi was not found. NVIDIA hosts need drivers installed; Mac M-series installer testing can use --dev."
  local max_vram
  max_vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk 'max<$1{max=$1} END{print max+0}')"
  if [[ "$max_vram" -lt "$MIN_VRAM_MIB" ]]; then
    fail "Detected ${max_vram} MiB VRAM; MeshNet beta requires at least ${MIN_VRAM_MIB} MiB usable VRAM."
  fi
  log "GPU check passed with ${max_vram} MiB VRAM."
}

download_text() {
  local url="$1"
  local dest="$2"
  curl -fsSL "$url" -o "$dest"
}

install_ollama() {
  TMP_DIR="$(mktemp -d)"
  local vendor_script="$TMP_DIR/install_ollama.sh"
  download_text "$INSTALL_BASE_URL/install/vendor/install_ollama.sh" "$vendor_script"
  chmod +x "$vendor_script"
  "$vendor_script"
}

pull_model() {
  command -v ollama >/dev/null 2>&1 || fail "Ollama was not installed successfully."
  log "Pulling $MODEL_NAME. First install downloads about 40GB and can take 15-60 minutes."
  ollama pull "$MODEL_NAME"
}

prompt_for_token() {
  if [[ -n "$CLAIM_TOKEN" ]]; then
    return
  fi
  if [[ -t 0 ]]; then
    read -r -p "Paste your MeshNet claim token: " CLAIM_TOKEN
  else
    fail "Missing claim token. Run: curl -sSL https://install.beta.meshnet.co | bash -s -- --claim-token YOUR_TOKEN"
  fi
}

claim_node() {
  if [[ -f "$CREDENTIALS_FILE" && "$FORCE_RECLAIM" -ne 1 ]]; then
    log "Existing credentials found; skipping claim and updating node client."
    return
  fi

  prompt_for_token
  local hostname gpu_json claim_response
  hostname="$(hostname)"
  gpu_json="$(python3 - <<'PY'
import json
import os
import subprocess

info = {"dev_mode": os.environ.get("MESHNET_DEV_MODE") == "1"}
try:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    info["gpus"] = [line.strip() for line in output.splitlines() if line.strip()]
except Exception:
    info["gpus"] = []
print(json.dumps(info))
PY
)"

  log "Registering node with MeshNet backend..."
  claim_response="$(curl -fsSL \
    -H 'Content-Type: application/json' \
    -d "{\"claim_token\":\"$CLAIM_TOKEN\",\"hostname\":\"$hostname\",\"gpu_info\":$gpu_json}" \
    "$BACKEND_URL/api/provider/claim")"

  install -d -m 700 "$MESHNET_DIR"
  python3 - "$claim_response" "$CREDENTIALS_FILE" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(sys.argv[1])
path = Path(sys.argv[2])
required = ["provider_id", "node_id", "node_secret"]
missing = [key for key in required if key not in data]
if missing:
    raise SystemExit(f"Missing keys in claim response: {missing}")
path.write_text(
    "\n".join(
        [
            f"PROVIDER_ID={data['provider_id']}",
            f"NODE_ID={data['node_id']}",
            f"NODE_SECRET={data['node_secret']}",
            "",
        ]
    ),
    encoding="utf-8",
)
path.chmod(0o600)
PY
}

download_node_client() {
  install -d -m 755 "$NODE_DIR"
  download_text "$BACKEND_URL/node.py" "$NODE_DIR/node.py"
  download_text "$BACKEND_URL/requirements.txt" "$NODE_DIR/requirements.txt"
  log "Node client updated in $NODE_DIR."
}

install_python_deps() {
  python3 -m venv "$VENV_DIR"
  if [[ "${MESHNET_SKIP_PIP_INSTALL:-0}" == "1" ]]; then
    log "Skipping pip install because MESHNET_SKIP_PIP_INSTALL=1."
    return
  fi
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -r "$NODE_DIR/requirements.txt"
}

install_systemd_service() {
  local user_dir="$HOME/.config/systemd/user"
  install -d -m 755 "$user_dir"
  cat > "$user_dir/meshnet-node.service" <<EOF
[Unit]
Description=MeshNet provider node
After=network-online.target

[Service]
Type=simple
Environment=MESHNET_API_BASE_URL=$BACKEND_URL
WorkingDirectory=$NODE_DIR
ExecStart=$VENV_DIR/bin/python $NODE_DIR/node.py
Restart=always
RestartSec=5
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable meshnet-node.service
  systemctl --user restart meshnet-node.service
}

install_launchd_service() {
  local launch_dir="$HOME/Library/LaunchAgents"
  local plist="$launch_dir/meshnet-node.plist"
  install -d -m 755 "$launch_dir"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>meshnet-node</string>
  <key>WorkingDirectory</key><string>$NODE_DIR</string>
  <key>ProgramArguments</key>
  <array><string>$VENV_DIR/bin/python</string><string>$NODE_DIR/node.py</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>MESHNET_API_BASE_URL</key><string>$BACKEND_URL</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_FILE</string>
  <key>StandardErrorPath</key><string>$LOG_FILE</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  launchctl enable "gui/$(id -u)/meshnet-node"
  launchctl kickstart -k "gui/$(id -u)/meshnet-node"
}

install_service() {
  touch "$LOG_FILE"
  if [[ "${MESHNET_SKIP_SERVICE:-0}" == "1" ]]; then
    log "Skipping service install because MESHNET_SKIP_SERVICE=1."
    return
  fi
  if [[ "$OS_KIND" == "macos" ]]; then
    install_launchd_service
  else
    install_systemd_service
  fi
  log "meshnet-node service installed and started."
}

load_credential() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {print $2}' "$CREDENTIALS_FILE" | tail -n 1
}

confirm_heartbeat() {
  local node_id node_secret
  node_id="$(load_credential NODE_ID)"
  node_secret="$(load_credential NODE_SECRET)"
  [[ -n "$node_id" && -n "$node_secret" ]] || fail "Credentials file is missing NODE_ID or NODE_SECRET."
  log "Confirming backend heartbeat..."
  curl -fsSL \
    -H "Content-Type: application/json" \
    -H "X-Node-Id: $node_id" \
    -H "X-Node-Secret: $node_secret" \
    -d "{\"hostname\":\"$(hostname)\",\"gpu_info\":{\"installer_confirm\":true}}" \
    "$BACKEND_URL/api/node/heartbeat" >/dev/null
  log "Tailing $LOG_FILE for 10 seconds..."
  if [[ "${MESHNET_SKIP_SERVICE:-0}" == "1" ]]; then
    log "Service was skipped; heartbeat confirmation succeeded."
  elif command -v timeout >/dev/null 2>&1; then
    timeout 10 tail -f "$LOG_FILE" || true
  else
    tail -f "$LOG_FILE" &
    local tail_pid=$!
    sleep 10
    kill "$tail_pid" >/dev/null 2>&1 || true
    wait "$tail_pid" >/dev/null 2>&1 || true
  fi
}

main() {
  export MESHNET_DEV_MODE="$DEV_MODE"
  detect_os
  check_commands
  check_disk
  check_gpu
  install -d -m 700 "$MESHNET_DIR"
  install_ollama
  pull_model
  claim_node
  download_node_client
  install_python_deps
  install_service
  confirm_heartbeat
  log "Your node is online. Watch it at https://beta.meshnet.co/host/dashboard"
}

main
