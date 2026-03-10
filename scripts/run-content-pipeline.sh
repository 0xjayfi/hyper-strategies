#!/usr/bin/env bash
# Automated X Content Pipeline — Daily cron runner
# Crontab entry:
#   0 8 * * *  /home/jsong407/hyper-strategies-pnl-weighted/scripts/run-content-pipeline.sh >> /home/jsong407/hyper-strategies-pnl-weighted/logs/content-pipeline.log 2>&1

set -euo pipefail

cd /home/jsong407/hyper-strategies-pnl-weighted

# Load pyenv so the correct Python + virtualenv are on PATH
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
eval "$(pyenv init -)"

# Load environment
set -a
source .env
set +a

# Sync database from the running backend (if it exists and is newer)
BACKEND_DB="${BACKEND_DB:-/home/jsong407/hyper-strategies/data/pnl_weighted.db}"
LOCAL_DB="data/pnl_weighted.db"

if [ -f "$BACKEND_DB" ] && [ "$BACKEND_DB" != "$(realpath "$LOCAL_DB" 2>/dev/null)" ]; then
    echo "[$(date -u)] Syncing database from running backend: $BACKEND_DB"
    cp "$BACKEND_DB" "$LOCAL_DB"
fi

# Take a fresh daily score snapshot so the comparison has up-to-date data
echo "[$(date -u)] Taking daily score snapshot..."
python -c "
from src.scheduler import save_daily_score_snapshot
from src.datastore import DataStore
ds = DataStore('data/pnl_weighted.db')
save_daily_score_snapshot(ds)
ds.close()
"

echo "[$(date -u)] Starting content pipeline"

# Step 1: Detect score movers
python -m src.content_pipeline
if [ $? -ne 0 ]; then
    echo "[$(date -u)] No post-worthy content found. Done."
    exit 0
fi

# Step 2: Verify payload is post-worthy
if ! grep -q '"post_worthy": true' data/content_payload.json; then
    echo "[$(date -u)] Payload not post-worthy. Done."
    exit 0
fi

echo "[$(date -u)] Post-worthy content detected. Capturing dashboard screenshots..."

# Step 3: Start Vite dev server (needed for screenshot proxy to backend)
VITE_PID=""
cleanup_vite() {
    if [ -n "$VITE_PID" ]; then
        kill "$VITE_PID" 2>/dev/null || true
        echo "[$(date -u)] Vite dev server stopped."
    fi
}
trap cleanup_vite EXIT

cd frontend
npx vite --host 0.0.0.0 &>/dev/null &
VITE_PID=$!
cd ..

# Wait for Vite to be ready
for i in $(seq 1 15); do
    if curl -s -o /dev/null http://localhost:5173/; then
        break
    fi
    sleep 1
done
echo "[$(date -u)] Vite dev server ready (PID=$VITE_PID)."

# Step 4: Capture dashboard screenshots
python -m src.screenshot_capture

echo "[$(date -u)] Screenshots captured. Launching Claude Code writer team..."

# Step 5: Launch Claude Code to write and push to Typefully
/home/jsong407/.local/bin/claude --dangerously-skip-permissions -p scripts/content-prompt.md

echo "[$(date -u)] Content pipeline complete."
