#!/usr/bin/env bash
set -Eeuo pipefail

# Anyone with a GPU can join. The model is sized to the machine (see
# pick_model); MESHNET_MODEL overrides it.
MODEL_NAME="${MESHNET_MODEL:-}"
MODEL_GB=0
MIN_ACCEL_MIB=6144
ACCEL_KIND=""
ACCEL_MIB=0
GPU_COUNT=0
RAM_ONLY=0
POOL_ROLE=""
POOL_WORKERS=""
POOL_BIND=""
POOL_PORT=50052
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
  cat <<'USAGE'
Usage: install.sh [--claim-token TOKEN] [options]

  --ram-only              Keep the model in memory only: nothing is written to
                          disk but the public model files, and those live on a
                          RAM disk that disappears on reboot. Needs RAM for the model.
  --pool-worker           (preview) Lend this machine's GPU to your own pool head
                          on the same private network. No claim token needed.
  --pool-head HOST:PORT,… (preview) Run one large model across this machine and
                          your pool workers, and serve it to MeshNet as one node.
  --pool-bind IP          Private address a pool worker listens on (default: auto).
  --dev                   Installer testing on any machine.
  --force-reclaim         Register this machine again.
USAGE
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
    --ram-only)
      RAM_ONLY=1
      shift
      ;;
    --pool-worker)
      POOL_ROLE="worker"
      shift
      ;;
    --pool-head)
      POOL_ROLE="head"
      POOL_WORKERS="${2:-}"
      [[ -n "$POOL_WORKERS" ]] || fail "--pool-head needs a list of workers, e.g. 192.168.1.20:50052,192.168.1.21:50052"
      shift 2
      ;;
    --pool-bind)
      POOL_BIND="${2:-}"
      shift 2
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

# What the model can use: every NVIDIA card summed (Ollama spreads one model
# over the GPUs in a machine), AMD cards through ROCm, or ~70% of an Apple
# Silicon Mac's unified memory.
detect_accelerator() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    ACCEL_KIND="nvidia"
    ACCEL_MIB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk '{s+=$1} END{print s+0}')"
    GPU_COUNT="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | grep -c . || true)"
  elif command -v rocm-smi >/dev/null 2>&1; then
    ACCEL_KIND="amd"
    ACCEL_MIB="$(rocm-smi --showmeminfo vram --csv 2>/dev/null | awk -F, 'NR>1 && $2+0>0 {s+=$2} END{print int(s/1048576)}')"
    GPU_COUNT="$(rocm-smi --showmeminfo vram --csv 2>/dev/null | awk -F, 'NR>1 && $2+0>0' | grep -c . || true)"
  elif [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    ACCEL_KIND="apple"
    ACCEL_MIB="$(( $(sysctl -n hw.memsize) / 1048576 * 70 / 100 ))"
    GPU_COUNT=1
  elif [[ "$DEV_MODE" -eq 1 ]]; then
    ACCEL_KIND="dev"; ACCEL_MIB=16384; GPU_COUNT=1
  else
    fail "No supported GPU found. MeshNet runs on NVIDIA (drivers installed), AMD (ROCm) or Apple Silicon Macs."
  fi
  if [[ "${ACCEL_MIB:-0}" -lt "$MIN_ACCEL_MIB" ]]; then
    fail "This machine has ${ACCEL_MIB} MiB of GPU memory; MeshNet needs at least ${MIN_ACCEL_MIB} MiB (6 GB)."
  fi
  log "Found ${ACCEL_KIND} with $((ACCEL_MIB / 1024)) GB for models across ${GPU_COUNT} GPU(s)."
}

# The largest model that fits, so every card can earn: an 8 GB card serves an
# 8B model, two 24 GB cards or a 64 GB Mac serve the 70B.
pick_model() {
  local gb=$((ACCEL_MIB / 1024))
  if [[ -n "$MODEL_NAME" ]]; then
    MODEL_GB=45
  elif [[ "$gb" -ge 42 ]]; then MODEL_NAME="llama3.3:70b-instruct-q4_K_M"; MODEL_GB=43
  elif [[ "$gb" -ge 21 ]]; then MODEL_NAME="qwen2.5:32b-instruct-q4_K_M"; MODEL_GB=20
  elif [[ "$gb" -ge 11 ]]; then MODEL_NAME="qwen2.5:14b-instruct-q4_K_M"; MODEL_GB=9
  else MODEL_NAME="llama3.1:8b-instruct-q4_K_M"; MODEL_GB=5
  fi
  log "This machine will serve ${MODEL_NAME} (about ${MODEL_GB} GB)."
}

check_disk() {
  local need_gb available_kib
  if [[ "$RAM_ONLY" -eq 1 ]]; then
    local ram_mib
    if [[ "$OS_KIND" == "macos" ]]; then ram_mib="$(( $(sysctl -n hw.memsize) / 1048576 ))"
    else ram_mib="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)"; fi
    if [[ "$ram_mib" -lt $(( (MODEL_GB + 6) * 1024 )) && "$DEV_MODE" -ne 1 ]]; then
      fail "RAM-only mode needs about $((MODEL_GB + 6)) GB of free memory for ${MODEL_NAME}; this machine has $((ram_mib / 1024)) GB."
    fi
    log "RAM-only mode: the model will live in memory and nothing is kept on disk."
    return
  fi
  need_gb=$((MODEL_GB + 5))
  available_kib="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
  if [[ "${available_kib:-0}" -lt $((need_gb * 1048576)) && "$DEV_MODE" -ne 1 ]]; then
    fail "About ${need_gb} GB of free disk is needed for ${MODEL_NAME}. Free some space, or use --ram-only."
  fi
  log "Disk check passed (${need_gb} GB needed)."
}

# RAM-only: a memory-backed folder for the model files. Linux uses /dev/shm;
# macOS gets a RAM disk sized to the model.
RAM_DIR=""
setup_ram_dir() {
  [[ "$RAM_ONLY" -eq 1 ]] || return 0
  if [[ "$OS_KIND" == "macos" ]]; then
    RAM_DIR="/Volumes/MeshNetModels"
    if [[ ! -d "$RAM_DIR" ]]; then
      local sectors=$(( (MODEL_GB + 4) * 1024 * 1024 * 2 ))
      local dev; dev="$(hdiutil attach -nomount "ram://$sectors" | awk '{print $1}')"
      diskutil erasevolume APFS MeshNetModels "$dev" >/dev/null
    fi
  else
    RAM_DIR="/dev/shm/meshnet-models"
    install -d -m 700 "$RAM_DIR"
  fi
  log "Model folder in memory: $RAM_DIR"
}

# The node's settings, read by the service: which model, where it lives,
# which backend serves it.
write_node_env() {
  install -d -m 700 "$MESHNET_DIR"
  {
    echo "MESHNET_API_BASE_URL=$BACKEND_URL"
    echo "NM_NODE_MODEL=$MODEL_NAME"
    if [[ "$RAM_ONLY" -eq 1 ]]; then
      echo "MESHNET_OWN_OLLAMA=1"
      echo "OLLAMA_HOST=127.0.0.1:11435"
      echo "OLLAMA_MODELS=$RAM_DIR"
    fi
    if [[ "$POOL_ROLE" == "head" ]]; then
      echo "MESHNET_BACKEND=openai"
      echo "MESHNET_OPENAI_URL=http://127.0.0.1:8080/v1"
      echo "MESHNET_POOL_WORKERS=$POOL_WORKERS"
    fi
  } > "$MESHNET_DIR/node.env"
  chmod 600 "$MESHNET_DIR/node.env"
}

# --------------------------------------------------------------- pool (preview)
# One big model across several of YOUR machines on one private network, with
# llama.cpp RPC: workers lend their GPU memory to a head, which serves the
# model to MeshNet as a single node. llama.cpp's rpc-server has no
# authentication, so a worker only ever listens on a private address.
LLAMA_DIR="$MESHNET_DIR/llama.cpp"
is_private_ip() {
  [[ "$1" =~ ^10\. || "$1" =~ ^192\.168\. || "$1" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. || "$1" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. ]]
}
install_llama_cpp() {
  [[ -x "$LLAMA_DIR/bin/rpc-server" && -x "$LLAMA_DIR/bin/llama-server" ]] && return 0
  local pattern asset url
  if [[ "$OS_KIND" == "macos" ]]; then pattern="bin-macos-arm64"; else pattern="bin-ubuntu-vulkan-x64"; fi
  url="$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest | python3 -c "import json,sys; a=[x['browser_download_url'] for x in json.load(sys.stdin)['assets'] if '$pattern' in x['name'] and x['name'].endswith(('.zip','.tar.gz'))]; print(a[0] if a else '')")"
  [[ -n "$url" ]] || fail "Could not find a llama.cpp build for this machine ($pattern)."
  TMP_DIR="$(mktemp -d)"
  log "Downloading llama.cpp from $url"
  curl -fsSL "$url" -o "$TMP_DIR/llama.pkg"
  install -d -m 755 "$LLAMA_DIR/bin" "$TMP_DIR/x"
  if [[ "$url" == *.zip ]]; then (cd "$TMP_DIR/x" && unzip -q ../llama.pkg); else tar -xzf "$TMP_DIR/llama.pkg" -C "$TMP_DIR/x"; fi
  local f
  for f in rpc-server llama-server; do
    local found; found="$(find "$TMP_DIR/x" -type f -name "$f" | head -n 1)"
    [[ -n "$found" ]] || fail "This llama.cpp build has no $f; pooling is not available on this machine yet."
    cp "$(dirname "$found")"/* "$LLAMA_DIR/bin/" 2>/dev/null || true
  done
  chmod +x "$LLAMA_DIR/bin/"* 2>/dev/null || true
}
pool_worker() {
  if [[ -z "$POOL_BIND" ]]; then
    if [[ "$OS_KIND" == "macos" ]]; then POOL_BIND="$(ipconfig getifaddr en0 2>/dev/null || true)"
    else POOL_BIND="$(hostname -I 2>/dev/null | awk '{print $1}')"; fi
  fi
  is_private_ip "${POOL_BIND:-}" || fail "Pool workers listen only on a private address (10.x, 172.16-31.x, 192.168.x or a Tailscale 100.x). Pass one with --pool-bind."
  install_llama_cpp
  local cmd="$LLAMA_DIR/bin/rpc-server -H $POOL_BIND -p $POOL_PORT"
  run_as_service meshnet-pool-worker "$cmd"
  log "Pool worker listening on $POOL_BIND:$POOL_PORT. Add it to your head: --pool-head $POOL_BIND:$POOL_PORT"
  log "Keep this port closed to the internet: llama.cpp RPC has no password."
}
pool_head() {
  local w
  for w in ${POOL_WORKERS//,/ }; do is_private_ip "${w%%:*}" || fail "Worker $w is not on a private network address."; done
  install_llama_cpp
  MODEL_NAME="llama3.3:70b-instruct-q4_K_M"; MODEL_GB=43
  local cmd="$LLAMA_DIR/bin/llama-server -hf bartowski/Llama-3.3-70B-Instruct-GGUF:Q4_K_M --rpc $POOL_WORKERS -ngl 99 -c 8192 --host 127.0.0.1 --port 8080"
  run_as_service meshnet-pool-head "$cmd"
  log "Pool head starting: Llama 3.3 70B across this machine and ${POOL_WORKERS}. The first start downloads the model."
}
run_as_service() {
  local name="$1" cmd="$2"
  if [[ "${MESHNET_SKIP_SERVICE:-0}" == "1" ]]; then log "Skipping $name service (MESHNET_SKIP_SERVICE=1): $cmd"; return; fi
  if [[ "$OS_KIND" == "macos" ]]; then
    local plist="$HOME/Library/LaunchAgents/$name.plist" args="" a
    for a in $cmd; do args="$args<string>$a</string>"; done
    install -d -m 755 "$HOME/Library/LaunchAgents"
    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>$name</string>
<key>ProgramArguments</key><array>$args</array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$MESHNET_DIR/$name.log</string><key>StandardErrorPath</key><string>$MESHNET_DIR/$name.log</string></dict></plist>
EOF
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$plist"
  else
    install -d -m 755 "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/$name.service" <<EOF
[Unit]
Description=MeshNet $name
After=network-online.target
[Service]
ExecStart=$cmd
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$name.service"
  fi
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

info = {"dev_mode": os.environ.get("MESHNET_DEV_MODE") == "1",
        "accel": os.environ.get("MESHNET_ACCEL", ""), "vram_mib": int(os.environ.get("MESHNET_ACCEL_MIB", "0") or 0),
        "gpu_count": int(os.environ.get("MESHNET_GPU_COUNT", "0") or 0)}
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
  # The node agent needs only these; the server's requirements.txt is far heavier.
  printf 'ollama\nrequests\n' > "$NODE_DIR/requirements.txt"
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
EnvironmentFile=-$MESHNET_DIR/node.env
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
  <dict>$(awk -F= 'NF>1 {printf "<key>%s</key><string>%s</string>", $1, substr($0, index($0, "=") + 1)}' "$MESHNET_DIR/node.env" 2>/dev/null || printf '<key>MESHNET_API_BASE_URL</key><string>%s</string>' "$BACKEND_URL")</dict>
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
  detect_accelerator
  export MESHNET_ACCEL="$ACCEL_KIND" MESHNET_ACCEL_MIB="$ACCEL_MIB" MESHNET_GPU_COUNT="$GPU_COUNT"
  if [[ "$POOL_ROLE" == "worker" ]]; then
    # A worker only lends its GPU to the provider's own head; it does not
    # register with MeshNet or take jobs itself.
    pool_worker
    return
  fi
  pick_model
  check_disk
  setup_ram_dir
  install -d -m 700 "$MESHNET_DIR"
  # Register first so the node shows up within minutes. The ~40 GB model is
  # downloaded afterwards by the node agent itself, while it is already online.
  claim_node
  [[ "$POOL_ROLE" == "head" ]] && pool_head
  write_node_env
  download_node_client
  install_python_deps
  install_service
  confirm_heartbeat
  install_ollama
  log "Your node is online with ${MODEL_NAME}. It downloads the model in the background and takes jobs once that finishes."
  log "As a community node it serves public jobs only; company data is never sent to it."
  log "Watch it at https://beta.meshnet.co/host-dashboard.html"
}

main
