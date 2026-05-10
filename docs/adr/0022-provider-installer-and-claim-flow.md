# ADR 0022: Provider installer and claim flow

## Status

Accepted

## Context

GPU providers need a low-friction way to join the beta without receiving backend credentials or editing configuration files. The installer must work from a one-line command, detect unsuitable machines early, and be safe to rerun for updates.

## Decision

MeshNet hosts a static shell installer at `GET /install` with `text/x-shellscript`. The provider onboarding page creates a single-use claim token that expires after 24 hours. The setup page shows the token and a prefilled installer command:

`curl -sSL https://install.beta.meshnet.co | bash -s -- --claim-token <token>`

The installer:

1. Detects Linux, macOS, or WSL and rejects native Windows with a WSL2 link.
2. Requires `nvidia-smi` with at least 22GB usable VRAM, except `--dev` for local installer testing.
3. Downloads the vendored Ollama installer from MeshNet, pulls `llama3.3:70b-instruct-q4_K_M`, creates `~/.meshnet`, and exchanges the claim token with `POST /api/provider/claim`.
4. Writes permanent `NODE_ID` and `NODE_SECRET` to `~/.meshnet/credentials`.
5. Downloads `node.py` and `requirements.txt`, installs them into a venv, installs a `meshnet-node` service via launchd or systemd user services, starts it, confirms heartbeat, and prints the dashboard URL.

`node.py` reads `~/.meshnet/credentials` at startup. Its backend calls include `X-Node-Id` and `X-Node-Secret`; the backend validates the hashed secret against the `providers` table.

## Consequences

- Providers do not need Supabase keys on their machines.
- Re-running the installer updates node code and dependencies while preserving existing credentials.
- The claim endpoint must reject expired or reused tokens.
- The beta installer depends on a large first model download, so the page and installer warn providers about the 15-60 minute first install.
