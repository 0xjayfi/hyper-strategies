#!/usr/bin/env bash
# Multi-Angle Content Pipeline — Daily cron runner
# 0 8 * * *  /home/jsong407/hyper-strategies/scripts/run-content-pipeline.sh >> logs/content-pipeline.log 2>&1

set -euo pipefail
cd /home/jsong407/hyper-strategies

# Load pyenv and environment
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
eval "$(pyenv init -)"
set -a; source .env; set +a

# Step 1: Take daily snapshots
echo "[$(date -u)] Taking daily snapshots..."
python -m src.content.dispatcher --snapshot

# Step 2: Detect and select angles
echo "[$(date -u)] Running angle detection..."
python -m src.content.dispatcher --detect
if [ ! -f data/content_selections.json ]; then
    echo "[$(date -u)] No angles selected. Done."
    exit 0
fi

# Step 3: Start Vite dev server (shared across all angles)
VITE_PID=""
cleanup_vite() {
    if [ -n "$VITE_PID" ]; then
        kill "$VITE_PID" 2>/dev/null || true
    fi
}
trap cleanup_vite EXIT

cd frontend
npx vite --host 0.0.0.0 &>/dev/null &
VITE_PID=$!
cd ..

VITE_READY=false
for i in $(seq 1 15); do
    # First check: is our Vite process still alive?
    if ! kill -0 "$VITE_PID" 2>/dev/null; then
        echo "[$(date -u)] ERROR: Vite process (PID $VITE_PID) died."
        exit 1
    fi
    if curl -s -o /dev/null http://localhost:5173/; then
        VITE_READY=true
        break
    fi
    sleep 1
done
if [ "$VITE_READY" = false ]; then
    echo "[$(date -u)] ERROR: Vite dev server failed to start within 15s. Aborting."
    exit 1
fi

# Step 4: Process each selected angle (isolated — one failure doesn't block the next)
python -c "
import json
with open('data/content_selections.json') as f:
    selections = json.load(f)
for s in selections:
    print(s['angle_type'])
" | while read -r angle; do
    echo "[$(date -u)] Processing angle: $angle"
    (
        # Capture screenshots
        python -m src.content.screenshot "$angle"

        # Run writer team
        cat "src/content/prompts/${angle}.md" | /home/jsong407/.local/bin/claude --dangerously-skip-permissions -p -

        echo "[$(date -u)] Angle $angle complete."
    ) || echo "[$(date -u)] Angle $angle FAILED — continuing to next angle."
done

echo "[$(date -u)] Content pipeline complete."
