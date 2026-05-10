#!/usr/bin/env bash
set -Eeuo pipefail

if command -v ollama >/dev/null 2>&1; then
  echo "[meshnet] Ollama already installed: $(command -v ollama)"
  exit 0
fi

if [[ "${MESHNET_MOCK_OLLAMA_INSTALL:-0}" == "1" ]]; then
  echo "[meshnet] Mock Ollama install enabled."
  exit 0
fi

case "$(uname -s)" in
  Darwin)
    if command -v brew >/dev/null 2>&1; then
      brew install ollama
      exit 0
    fi
    echo "[meshnet] Install Ollama for macOS from https://ollama.com/download, then rerun this installer." >&2
    exit 1
    ;;
  Linux)
    if command -v apt-get >/dev/null 2>&1; then
      echo "[meshnet] Installing Ollama using the vendored installer path."
      curl -fsSL https://ollama.com/install.sh | sh
      exit 0
    fi
    echo "[meshnet] Could not find a supported Linux package manager for Ollama." >&2
    exit 1
    ;;
  *)
    echo "[meshnet] Unsupported OS for Ollama install." >&2
    exit 1
    ;;
esac
