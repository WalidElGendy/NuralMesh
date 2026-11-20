#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

MOCK_BIN="$TMP_DIR/bin"
mkdir -p "$MOCK_BIN"

cat > "$MOCK_BIN/nvidia-smi" <<'SH'
#!/usr/bin/env bash
# MOCK_VRAM: one MiB figure per card, e.g. "24564 24564" for two 4090s.
if [[ "$*" == *"--query-gpu=memory.total"* ]]; then
  for v in ${MOCK_VRAM:-24564}; do echo "$v"; done
elif [[ "$*" == *"--query-gpu=name,memory.total"* ]]; then
  for v in ${MOCK_VRAM:-24564}; do echo "NVIDIA RTX 4090, $v MiB"; done
else
  echo "NVIDIA-SMI mock"
fi
SH

cat > "$MOCK_BIN/ollama" <<'SH'
#!/usr/bin/env bash
echo "ollama $*"
SH

cat > "$MOCK_BIN/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
dest=""
url=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "-o" ]]; then
    dest="${args[$((i+1))]}"
  fi
  if [[ "${args[$i]}" == http* ]]; then
    url="${args[$i]}"
  fi
done
write_dest() {
  if [[ -n "$dest" ]]; then
    printf '%s' "$1" > "$dest"
  else
    printf '%s' "$1"
  fi
}
case "$url" in
  */install/vendor/install_ollama.sh)
    write_dest $'#!/usr/bin/env bash\necho vendor ollama installed\n'
    ;;
  */node.py)
    write_dest $'print("meshnet node mock")\n'
    ;;
  */requirements.txt)
    write_dest $'requests\n'
    ;;
  */api/provider/claim)
    write_dest '{"provider_id":"prov_test","node_id":"node_test","node_secret":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
    ;;
  */api/node/heartbeat)
    write_dest '{"status":"ok"}'
    ;;
  *)
    echo "unexpected curl url: $url" >&2
    exit 2
    ;;
esac
SH

chmod +x "$MOCK_BIN/nvidia-smi" "$MOCK_BIN/ollama" "$MOCK_BIN/curl"
run_install() {   # $1 = MOCK_VRAM, rest = extra installer flags
  local vram="$1"; shift
  rm -rf "$TMP_DIR/home"; mkdir -p "$TMP_DIR/home"
  HOME="$TMP_DIR/home" \
  PATH="$MOCK_BIN:$PATH" \
  MOCK_VRAM="$vram" \
  MESHNET_BACKEND_URL="https://backend.test" \
  MESHNET_INSTALL_BASE_URL="https://install.test" \
  MESHNET_SKIP_SERVICE=1 \
  MESHNET_SKIP_PIP_INSTALL=1 \
  bash "$ROOT_DIR/scripts/installer/install.sh" --claim-token clm_test_token --dev "$@"
}

# One 24 GB card: registers, and is sized to a 32B model.
run_install "24564"
test -f "$TMP_DIR/home/.meshnet/credentials"
test -f "$TMP_DIR/home/.meshnet/node/node.py"
grep -q "NODE_ID=node_test" "$TMP_DIR/home/.meshnet/credentials"
grep -q "NM_NODE_MODEL=qwen2.5:32b-instruct-q4_K_M" "$TMP_DIR/home/.meshnet/node.env"

# Two 24 GB cards in one machine work as one: the 70B.
run_install "24564 24564"
grep -q "NM_NODE_MODEL=llama3.3:70b-instruct-q4_K_M" "$TMP_DIR/home/.meshnet/node.env"

# An 8 GB card can join too, with an 8B model.
run_install "8192"
grep -q "NM_NODE_MODEL=llama3.1:8b-instruct-q4_K_M" "$TMP_DIR/home/.meshnet/node.env"

# Below 6 GB: a clear refusal.
if run_install "4096" >/dev/null 2>&1; then echo "a 4 GB card should be refused"; exit 1; fi

# RAM-only: the node runs its own Ollama with models in memory.
run_install "8192" --ram-only
grep -q "MESHNET_OWN_OLLAMA=1" "$TMP_DIR/home/.meshnet/node.env"
grep -q "OLLAMA_MODELS=/dev/shm/meshnet-models" "$TMP_DIR/home/.meshnet/node.env"

# A pool worker refuses a public address.
if run_install "8192" --pool-worker --pool-bind 8.8.8.8 >/dev/null 2>&1; then echo "a public pool address should be refused"; exit 1; fi
echo "installer mock test passed"
