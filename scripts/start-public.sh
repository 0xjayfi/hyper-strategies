#!/usr/bin/env bash
# Start backend + Cloudflare Tunnel for public dashboard access.
# Usage: ./scripts/start-public.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$BACKEND_PID" 2>/dev/null || true
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# --- Check prerequisites ---
if ! command -v cloudflared &>/dev/null; then
    echo "ERROR: cloudflared is not installed."
    echo ""
    echo "Install it:"
    echo "  Debian/Ubuntu: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb && sudo dpkg -i /tmp/cloudflared.deb"
    echo "  macOS:         brew install cloudflared"
    echo ""
    exit 1
fi

# --- Start backend ---
echo "Starting backend on port $BACKEND_PORT..."
python -m backend.run &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$BACKEND_PORT/" >/dev/null 2>&1; then
        echo "Backend is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Backend failed to start within 30s."
        exit 1
    fi
    sleep 1
done

# --- Start Cloudflare Tunnel ---
echo ""
echo "Starting Cloudflare Tunnel..."
echo "============================================"
echo "  Your public backend URL will appear below"
echo "  (look for the https://*.trycloudflare.com line)"
echo "============================================"
echo ""

cloudflared tunnel --url "http://localhost:$BACKEND_PORT" &
TUNNEL_PID=$!

# Wait for both
wait "$BACKEND_PID" "$TUNNEL_PID"
