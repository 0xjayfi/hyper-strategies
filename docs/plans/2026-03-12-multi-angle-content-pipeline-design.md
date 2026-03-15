# Multi-Angle Content Pipeline — Design

> Evolve the daily X content pipeline from a single "Wallet Spotlight" narrative into a system that automatically selects the most interesting story angle each day from 6 possible angles, with cooldowns to ensure variety.

---

## Problem Statement

The current content pipeline posts the same narrative shape every day: wallet spotlight (single wallet score mover). This gets repetitive for followers and misses interesting stories happening elsewhere in the data — leaderboard shake-ups, smart money consensus flips, allocation shifts, etc. The web dashboard is live and surfaces multiple views (market, leaderboard, allocations, positions) that each contain post-worthy signals.

---

## Decisions

| Decision | Choice |
|----------|--------|
| Angle selection | Automatic — system scores all angles, picks top 1-2 |
| Max posts per day | 2 (second post only if score ≥ 0.5) |
| Angle variety | Cooldown per angle type prevents same angle posting consecutive days |
| Auto-publish vs draft | Safe/factual angles auto-publish; analytical/opinionated angles → Typefully draft for manual review |
| Tone | Analytical angles keep Cryptor voice; factual/recap angles use cleaner neutral tone |
| Screenshots | Per-angle — each angle captures its own relevant dashboard pages |
| Writer team | Same 5-agent structure (Drafter → Editor → Polish → 2x Reviewer), angle-specific prompt templates |

---

## Angle Definitions

### The 6 Angles

| Angle | Trigger Threshold | Tone | Auto-publish | Cooldown | Dashboard Page |
|-------|------------------|------|-------------|----------|----------------|
| **Wallet Spotlight** | Score delta ≥ 0.10 OR rank change ≥ 2 OR top-5 entry/exit | Cryptor (analytical, opinionated) | No (draft) | 2 days | `/traders/{addr}` |
| **Leaderboard Shake-up** | ≥ 3 wallets changed position in top 10 OR new entrant in top 3 | Neutral recap | Yes (auto) | 2 days | `/leaderboard` |
| **Smart Money Consensus** | Direction flipped on any token OR confidence swing ≥ 20pp | Cryptor (directional take) | No (draft) | 3 days | `/market` |
| **Allocation Shift** | Trader entered/exited allocation set OR weight changed ≥ 10pp | Neutral, factual | Yes (auto) | 3 days | `/allocations` |
| **Token Spotlight** | Smart money wallet opened position ≥ $500K on single token | Cryptor (thesis analysis) | No (draft) | 3 days | `/positions` |
| **Index Portfolio Update** | Aggregate portfolio direction flipped on ≥ 2 tokens OR new token entered top 5 | Neutral with light interpretation | Yes (auto) | 4 days | `/allocations` strategies tab |

### Detection Scoring

Each angle's `detect()` returns a raw score (0-1) based on how far above threshold the signal is:

- **Wallet Spotlight:** `score = max(top5_floor, min(1.0, (score_delta / 0.30) * 0.5 + (rank_change / 10) * 0.5))` where `top5_floor = 0.5` if the wallet entered or exited the top 5 (guarantees selection consideration even with small numeric changes), otherwise 0. A 0.30 score swing with a 10-rank jump = perfect 1.0
- **Leaderboard Shake-up:** `score = min(1.0, shuffled_wallets / 8)` — 8+ shuffles = 1.0
- **Smart Money Consensus:** If a direction flip occurred, `score = min(1.0, 0.7 + confidence_swing / 40)` (the 0.7 is additive on top of the confidence component). If no flip, `score = min(1.0, confidence_swing / 40)`. A 40pp swing without a flip = 1.0; a direction flip with zero additional swing = 0.7
- **Allocation Shift:** `score = min(1.0, max_weight_delta / 0.25)` — 25pp weight change = 1.0; entry/exit gets flat 0.6
- **Token Spotlight:** `score = min(1.0, position_value / 2_000_000)` — $2M+ position = 1.0
- **Index Portfolio Update:** `score = min(1.0, tokens_flipped / 3)` — 3+ tokens flipped direction = 1.0

### Cooldown & Freshness Boost

Angles within their cooldown window are blocked (effective_score = 0). After cooldown expires, angles that haven't posted recently get a freshness multiplier:

```
days_since_last = days since this angle last posted
if days_since_last < cooldown:
    effective_score = 0  (blocked)
else:
    effective_score = raw_score * min(1.3, 1.0 + (days_since_last - cooldown) * 0.05)
```

An angle 7 days past its cooldown gets a 1.3x boost (capped).

---

## Architecture

### New Module Structure

```
src/
  content/                          # NEW package (replaces content_pipeline.py)
    __init__.py
    dispatcher.py                   # Runs all detectors, ranks, picks top 1-2
    base.py                         # Base angle class
    angles/
      __init__.py
      wallet_spotlight.py           # Existing logic from content_pipeline.py
      leaderboard_shakeup.py
      smart_money_consensus.py
      allocation_shift.py
      token_spotlight.py
      index_portfolio.py
    prompts/                        # Per-angle prompt templates
      wallet_spotlight.md
      leaderboard_shakeup.md
      smart_money_consensus.md
      allocation_shift.md
      token_spotlight.md
      index_portfolio.md
    screenshot.py                   # Generalized screenshot capture
```

### Base Angle Class

```python
@dataclass
class AngleResult:
    angle_type: str
    raw_score: float
    effective_score: float
    payload: dict
    screenshot_config: ScreenshotConfig
    prompt_path: str
    auto_publish: bool
    tone: str  # "analytical" or "neutral"

class ContentAngle(ABC):
    angle_type: str
    auto_publish: bool
    cooldown_days: int
    tone: str

    @abstractmethod
    def detect(self, datastore, nansen_client=None) -> float:
        """Return raw post-worthiness score 0-1, or 0 if below threshold."""

    @abstractmethod
    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload JSON for the writer team."""

    @abstractmethod
    def screenshot_config(self) -> ScreenshotConfig:
        """Return screenshot capture configuration for this angle."""

    @property
    def prompt_path(self) -> str:
        return f"src/content/prompts/{self.angle_type}.md"
```

### Dispatcher Flow

```
Daily 08:00 UTC (cron)
│
├── 1. Take daily snapshots
│      ├── Score snapshots (existing)
│      ├── Consensus snapshots (new)
│      ├── Allocation snapshots (new)
│      └── Index portfolio snapshots (new)
│
├── 2. Run detection
│      ├── For each registered angle:
│      │     ├── angle.detect(datastore, nansen_client) → raw_score
│      │     ├── Check cooldown gate against content_posts table
│      │     └── Apply freshness boost → effective_score
│      ├── Sort by effective_score descending
│      ├── Pick #1 (if effective_score > 0)
│      ├── Pick #2 only if effective_score ≥ 0.5
│      └── For each picked angle:
│            ├── angle.build_payload() → data/content_payload_{angle_type}.json
│            └── Record selection in content_posts table
│
├── 3. For each selected angle (max 2):
│      ├── Start Vite dev server (once, shared)
│      ├── Capture angle-specific screenshots → data/charts/
│      ├── Pipe angle-specific prompt to Claude Code
│      │     └── cat src/content/prompts/{angle_type}.md | claude --dangerously-skip-permissions -p -
│      ├── Claude Code: 5-agent writer team → Typefully
│      │     ├── auto_publish=true → schedule publish_at = now + 5min
│      │     └── auto_publish=false → create draft for review
│      └── Log result to content_posts table
│
└── 4. Kill Vite, done
```

### Screenshot Generalization

```python
@dataclass
class PageCapture:
    route: str                    # e.g. "/market", "/allocations"
    wait_selector: str            # data-testid to wait for
    capture_selector: str         # element to screenshot
    filename: str                 # output filename
    pre_capture_js: str | None    # optional JS before screenshot

@dataclass
class ScreenshotConfig:
    pages: list[PageCapture]
```

Each angle defines its own config. The screenshot module navigates to each page, waits for the selector, optionally runs JS (hide extra rows, etc.), and captures.

---

## Data Dependencies

### New SQLite Tables

**`content_posts`** — Tracks posted content and cooldowns.

```sql
content_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_date       TEXT NOT NULL,
    angle_type      TEXT NOT NULL,
    raw_score       REAL NOT NULL,
    effective_score REAL NOT NULL,
    auto_published  INTEGER DEFAULT 0,
    typefully_url   TEXT,
    payload_path    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_content_posts_angle_date ON content_posts(angle_type, post_date DESC);
```

**`consensus_snapshots`** — Day-over-day smart money consensus per token.

```sql
consensus_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,
    token           TEXT NOT NULL,
    direction       TEXT NOT NULL,
    confidence_pct  REAL NOT NULL,
    sm_long_usd     REAL,
    sm_short_usd    REAL,
    UNIQUE(snapshot_date, token)
)
```

**`allocation_snapshots`** — Day-over-day allocation weights.

```sql
allocation_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,
    trader_id       TEXT NOT NULL,
    weight          REAL NOT NULL,
    UNIQUE(snapshot_date, trader_id)
)
```

**`index_portfolio_snapshots`** — Day-over-day aggregate portfolio composition.

```sql
index_portfolio_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,
    token           TEXT NOT NULL,
    side            TEXT NOT NULL,
    target_weight   REAL NOT NULL,
    target_usd      REAL NOT NULL,
    UNIQUE(snapshot_date, token, side)
)
```

### Data Source Per Angle

| Angle | Detection Data | New Table Needed |
|-------|---------------|-----------------|
| Wallet Spotlight | `score_snapshots` (existing) | No |
| Leaderboard Shake-up | `score_snapshots` (existing) | No |
| Smart Money Consensus | `consensus_snapshots` (new) + live Nansen API | Yes |
| Allocation Shift | `allocation_snapshots` (new) | Yes |
| Token Spotlight | `position_snapshots` (existing) + live Nansen API for payload | No |
| Index Portfolio Update | `index_portfolio_snapshots` (new) | Yes |

### Snapshot Population

All snapshots are taken at the start of the dispatcher run, before detection. The consensus snapshot requires live Nansen API calls (same endpoints as `/market-overview`). All others use existing DB data.

**Allocation snapshot population:** Reads the latest allocations via `get_latest_allocations()` (which selects the batch with `MAX(computed_at)` from the `allocations` table) and stores `(today, trader_id, final_weight)` into `allocation_snapshots`. The `allocations` table accumulates rows with different `computed_at` timestamps, but only the latest batch is relevant. The new snapshot table flattens this to one row per trader per day for simple day-over-day comparison. Column naming: `trader_id` follows the convention used in `score_snapshots` (the source column in `allocations` is `address`).

**Token Spotlight detection logic:**

Identifying smart money wallets: The `score_snapshots` table has a `smart_money` boolean column. The detector queries `SELECT DISTINCT trader_id FROM score_snapshots WHERE smart_money = 1 AND snapshot_date = :today` to get the set of smart money addresses. A new DataStore method `get_smart_money_addresses(date)` is added for this.

Comparing positions: For each smart money address, the detector calls `get_position_snapshot_series(address, days=2)` (existing method) to get snapshots from the last 48 hours. It buckets these into "recent" (captured_at within last 24h) and "prior" (captured_at 24-48h ago), using the most recent snapshot per address in each bucket. A "new large position" is detected when: (a) a token appears in the recent bucket but not in the prior bucket with position_value_usd ≥ $500K, OR (b) the position size on an existing token grew by ≥ $500K between buckets.

The live Nansen API call is used only in `build_payload()` to fetch the freshest position details for the content, not for detection. This means detection uses slightly stale data (up to 12 hours old from the last sweep), which is acceptable since the threshold ($500K) is high enough that a position this large will still be present when the payload is built.

**First run behavior:** When `content_posts` is empty (first run), all angles have `days_since_last = infinity`, meaning every angle gets the maximum 1.3x freshness boost. The highest raw_score wins. This is intentional — the first day simply picks the most interesting story.

### Content Selections File

The `--detect` step writes `data/content_selections.json` with this schema:

```json
[
  {
    "angle_type": "leaderboard_shakeup",
    "raw_score": 0.75,
    "effective_score": 0.91,
    "auto_publish": true,
    "payload_path": "data/content_payload_leaderboard_shakeup.json"
  },
  {
    "angle_type": "wallet_spotlight",
    "raw_score": 0.62,
    "effective_score": 0.62,
    "auto_publish": false,
    "payload_path": "data/content_payload_wallet_spotlight.json"
  }
]
```

If no angles pass detection, the file is not written (the shell script checks for its existence before proceeding).

### Retention Policy

All 4 new tables are included in `enforce_retention()` with 90-day retention (same as existing tables). Since these store daily snapshots (not hourly), this means ~90 rows per token/trader, which is negligible in size.

---

## Prompt Templates & Tone

### Tone Spectrum

**Analytical/Opinionated (Cryptor voice)** — Wallet Spotlight, Smart Money Consensus, Token Spotlight:
- Full style variation rotation (8 styles from `writing_style.md`)
- Interpret data, take positions, use CT lingo
- 2-3 tweets
- References `writing_style.md` + `studied_x_writiing_styles.md`

**Neutral/Factual (recap voice)** — Leaderboard Shake-up, Allocation Shift, Index Portfolio Update:
- Clean recap tone: lead with the change, provide context, close with what to watch
- No directional takes, no style dice roll
- 1-2 tweets
- References `writing_style.md` only (for formatting rules like no em dashes)
- Neutral tone rules: state facts without opinion ("Wallet X moved from rank 7 to rank 2" not "Wallet X is crushing it"). Use "notable" / "significant" instead of "bullish" / "bearish". End with a forward-looking observation ("worth watching whether this holds") not a call to action. Still use CT-natural language (not corporate), but no hot takes.

### Prompt Structure (shared skeleton)

Each angle prompt follows this shape:

```
Step 1: Load context
  - Read data/content_payload_{angle_type}.json
  - Read x_writer/writing_style.md
  - [ANALYTICAL only]: Read x_writer/studied_x_writiing_styles.md
  - List PNGs in data/charts/

Step 2: Tone instruction
  - [ANALYTICAL]: Pick random style variation, full Cryptor voice
  - [NEUTRAL]: Clean recap tone, no style dice roll

Step 3: Angle-specific writing instructions
  - What to lead with
  - What data points to include
  - What to interpret vs. just report
  - Screenshot pairing rules

Step 4: 5-agent pipeline (Drafter → Editor → Polish → 2x Reviewer)

Step 5: Push to Typefully
  - [AUTO-PUBLISH]: schedule publish_at = now + 5min
  - [DRAFT]: create draft, print URL
```

---

## Shell Script & Orchestration

### Revised `scripts/run-content-pipeline.sh`

```bash
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
    if curl -s -o /dev/null http://localhost:5173/; then
        VITE_READY=true
        break
    fi
    sleep 1
done
if [ "$VITE_READY" = false ]; then
    echo "[$(date -u)] ERROR: Vite dev server failed to start. Aborting."
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
```

### Error Handling

- Each angle runs in a subshell (`( ... ) || ...`), so one angle's failure does not abort the loop
- Each angle's result is logged to `content_posts` table by the prompt's Typefully step
- The `set -euo pipefail` at the top catches failures in the snapshot and detection steps (which are fatal), but the per-angle loop is isolated

---

## Testing Strategy

### Unit Tests (`tests/test_content/`)

**Per-angle detection** (`test_angles/`):
- Each angle gets its own test file
- Test `detect()` returns correct score for above/below threshold scenarios
- Test `build_payload()` produces valid JSON
- Test cooldown blocking (score = 0 within cooldown)
- Test freshness boost math

**Dispatcher** (`test_dispatcher.py`):
- Given known scores, picks correct top 1-2
- Respects cooldowns
- Second angle only picked if score ≥ 0.5
- All angles below threshold → no post

**Snapshots** (`test_snapshots.py`):
- Consensus snapshot stores/retrieves correctly
- Allocation snapshot comparison detects entries/exits
- Index portfolio snapshot comparison detects direction flips

**Screenshot config** (`test_screenshot.py`):
- Each angle's ScreenshotConfig has valid routes and selectors
- Filenames don't collide across angles

### Integration Smoke Test

`scripts/test_content_angles.py`:
1. Seeds DB with synthetic snapshot data for 2 consecutive days
2. Runs `dispatcher.detect()` and verifies at least one angle fires
3. Verifies payload JSON is well-formed
4. Does NOT call Typefully or Claude Code

---

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `src/content/__init__.py` | Package init |
| `src/content/dispatcher.py` | Detection orchestrator, angle ranking, selection |
| `src/content/base.py` | Base `ContentAngle` class and `ScreenshotConfig` dataclasses |
| `src/content/screenshot.py` | Generalized Playwright screenshot capture |
| `src/content/angles/__init__.py` | Registers all 6 angles |
| `src/content/angles/wallet_spotlight.py` | Wallet spotlight detection + payload (extracted from `content_pipeline.py`) |
| `src/content/angles/leaderboard_shakeup.py` | Leaderboard shake-up detection + payload |
| `src/content/angles/smart_money_consensus.py` | Smart money consensus detection + payload |
| `src/content/angles/allocation_shift.py` | Allocation shift detection + payload |
| `src/content/angles/token_spotlight.py` | Token spotlight detection + payload |
| `src/content/angles/index_portfolio.py` | Index portfolio update detection + payload |
| `src/content/prompts/wallet_spotlight.md` | Writer prompt (extracted from `scripts/content-prompt.md`) |
| `src/content/prompts/leaderboard_shakeup.md` | Writer prompt |
| `src/content/prompts/smart_money_consensus.md` | Writer prompt |
| `src/content/prompts/allocation_shift.md` | Writer prompt |
| `src/content/prompts/token_spotlight.md` | Writer prompt |
| `src/content/prompts/index_portfolio.md` | Writer prompt |
| `tests/test_content/__init__.py` | Test package |
| `tests/test_content/test_dispatcher.py` | Dispatcher tests |
| `tests/test_content/test_snapshots.py` | Snapshot table tests |
| `tests/test_content/test_screenshot.py` | Screenshot config tests |
| `tests/test_content/test_angles/` | Per-angle detection tests (6 files) |
| `scripts/test_content_angles.py` | Integration smoke test |

### Modified Files

| File | Change |
|------|--------|
| `src/datastore.py` | Add 4 new tables (`content_posts`, `consensus_snapshots`, `allocation_snapshots`, `index_portfolio_snapshots`) + CRUD methods + retention cleanup for new tables |
| `src/typefully_client.py` | Add `publish_at` parameter to `create_draft()` and `_build_draft_payload()`. The Typefully API v2 supports a `publish_at` field (ISO 8601 datetime) on the draft creation endpoint to schedule immediate publishing. Auto-publish angles pass `publish_at = now + 5min`; draft angles omit it. |
| `scripts/run-content-pipeline.sh` | Rewrite to use dispatcher + per-angle loop |
| `src/config.py` | Add per-angle thresholds and cooldown config |
| `frontend/src/pages/MarketOverview.tsx` | Add `data-testid="market-overview"` to the main content wrapper |
| `frontend/src/pages/AllocationDashboard.tsx` | Add `data-testid="allocation-dashboard"` to the main content wrapper, `data-testid="allocation-strategies"` to the strategies tab panel |
| `frontend/src/pages/PositionExplorer.tsx` | Add `data-testid="position-explorer"` to the main content wrapper |

**Note on frontend `data-testid` attributes:** The `/leaderboard` and `/traders/{addr}` pages already have the necessary `data-testid` selectors. The `/market`, `/allocations`, and `/positions` pages need them added as a prerequisite for screenshot capture. These are trivial one-line additions to each page component's outer wrapper div.

**Note on allocation strategies tab:** The strategies tab on `/allocations` uses React `useState` for tab switching, which is not URL-driven. The Index Portfolio Update angle's screenshot config must include `pre_capture_js` that clicks the "Index Portfolio" tab button before capture.

### Deprecated (kept but no longer called by cron)

| File | Status |
|------|--------|
| `src/content_pipeline.py` | Logic moves to `src/content/angles/wallet_spotlight.py`; file kept for reference |
| `src/screenshot_capture.py` | Logic moves to `src/content/screenshot.py`; file kept for reference |
| `scripts/content-prompt.md` | Split into per-angle prompts in `src/content/prompts/`; file kept for reference |

---

## What Stays the Same

- Writer agent team structure (5-agent: Drafter → Editor → Polish → 2x Reviewer)
- `x_writer/writing_style.md` and `x_writer/studied_x_writiing_styles.md` — voice references
- `score_snapshots` table — still populated by scheduler
- Scheduler (`src/scheduler.py`) — still runs independently; content pipeline is cron-triggered, not scheduler-triggered
- Cron schedule: daily 08:00 UTC
- All existing backend API routers and frontend pages
