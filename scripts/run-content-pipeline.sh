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

echo "[$(date -u)] Post-worthy content detected. Generating charts..."

# Step 3: Generate charts
python -m src.chart_generator

echo "[$(date -u)] Charts generated. Launching Claude Code writer team..."

# Step 4: Launch Claude Code to write and push to Typefully
/home/jsong407/.local/bin/claude --dangerously-skip-permissions -p scripts/content-prompt.md

echo "[$(date -u)] Content pipeline complete."
