#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

MOCK_BIN="$TMP_DIR/bin"
mkdir -p "$MOCK_BIN"

cat > "$MOCK_BIN/nvidia-smi" <<'SH'
#!/usr/bin/env bash
if [[ "$*" == *"--query-gpu=memory.total"* ]]; then
  echo "24564"
elif [[ "$*" == *"--query-gpu=name,memory.total"* ]]; then
  echo "NVIDIA RTX 4090, 24564 MiB"
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
mkdir -p "$TMP_DIR/home"

HOME="$TMP_DIR/home" \
PATH="$MOCK_BIN:$PATH" \
MESHNET_BACKEND_URL="https://backend.test" \
MESHNET_INSTALL_BASE_URL="https://install.test" \
MESHNET_SKIP_SERVICE=1 \
MESHNET_SKIP_PIP_INSTALL=1 \
bash "$ROOT_DIR/scripts/installer/install.sh" --claim-token clm_test_token --dev

test -f "$TMP_DIR/home/.meshnet/credentials"
test -f "$TMP_DIR/home/.meshnet/node/node.py"
grep -q "NODE_ID=node_test" "$TMP_DIR/home/.meshnet/credentials"
echo "installer mock test passed"
