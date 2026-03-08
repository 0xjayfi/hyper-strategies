# Automated X Content Pipeline — Design

> Repurpose the existing Nansen data pipeline, scoring engine, and writing guidelines into an automated content generation system that produces daily wallet spotlight posts for X, pushed to Typefully as drafts for manual review and publishing.

---

## Problem Statement

Running a free public dashboard burns Nansen API credits with no return. The same data and scoring infrastructure can generate high-quality X content — wallet spotlights backed by real on-chain analysis — driving engagement and audience growth instead.

---

## Decisions

| Decision | Choice |
|----------|--------|
| Content type | Wallet spotlight — automated wallet picking based on score movers |
| Trigger | Rank change (enter/exit top 5, move 2+ ranks) OR score delta ≥ configurable threshold |
| Cadence | Daily, skip if nothing interesting |
| Writer | Claude Code itself (`cldy` alias, full permissions) — no Claude API dependency |
| Review flow | Push draft to Typefully, user reviews and publishes manually |
| Content style | Pure data analysis, no product mentions. Lead with interesting change, explain with 2-3 key dimensions |
| Style variation | Random pick from the 8 styles in `x_writer/writing_style.md` |
| No post if nothing moved | No filler content |
| Writing references | `writing_style.md` (rules) + `studied_x_writiing_styles.md` (voice examples) + `review_notes.md` (known pitfalls) |
| Charts | Python-generated PNGs with visual type variation, consistent dark theme |

---

## Architecture

```
Daily 08:00 UTC (cron)
│
├── 1. python -m src.content_pipeline
│      ├── Query score_snapshots table (today vs yesterday)
│      ├── Detect movers (rank change OR score delta)
│      ├── Pick most interesting wallet
│      └── Write data/content_payload.json
│
├── 2. Shell: check post_worthy == true?
│      ├── false → stop, no cost
│      └── true ↓
│
├── 3. python -m src.chart_generator
│      ├── Read payload
│      ├── Randomly pick 1-2 chart types
│      └── Render PNGs to data/charts/
│
├── 4. cldy -p "scripts/content-prompt.md"
│      │
│      ├── Read payload + 3 writing reference files
│      │
│      ├── Agent 1 (Drafter)
│      │   └── Raw draft from data + random style
│      │
│      ├── Agent 2 (CT Editor)
│      │   └── Fix voice, kill jargon, check lengths
│      │
│      ├── Agent 3 (Final Polish)
│      │   └── Vibe check against Cryptor examples
│      │
│      └── Upload charts via Typefully media API
│      └── Push to Typefully as draft with media attached
│
└── 5. User reviews in Typefully, publishes when ready
```

---

## Module 1: Detection (`src/content_pipeline.py`)

**Purpose:** Determine if any wallet had an interesting enough score/rank change to warrant a post.

**New SQLite table: `score_snapshots`**

| Column | Type | Description |
|--------|------|-------------|
| snapshot_date | DATE | Date of the snapshot |
| trader_id | TEXT | Wallet address |
| rank | INTEGER | Rank position on that date |
| composite_score | REAL | Overall composite score |
| growth_score | REAL | Growth dimension |
| drawdown_score | REAL | Drawdown dimension |
| leverage_score | REAL | Leverage risk dimension |
| liq_distance_score | REAL | Liquidation distance dimension |
| diversity_score | REAL | Diversity dimension |
| consistency_score | REAL | Consistency dimension |
| smart_money | BOOLEAN | Whether wallet has Smart Money label |

**Detection logic:**
1. After existing metrics recompute, store daily snapshot of all scored traders
2. Compare latest snapshot vs previous day
3. Trigger conditions (configurable in `src/config.py`):
   - Rank change: wallet enters/exits top 5, or moves ≥ 2 ranks
   - Score delta: composite score changed by ≥ 0.10 (default)
4. If multiple wallets trigger, pick the one with the largest combined rank + score change
5. If nothing triggers, set `post_worthy: false`

**Output:** `data/content_payload.json`

```json
{
  "post_worthy": true,
  "snapshot_date": "2026-03-08",
  "wallet": {
    "address": "0xabc...",
    "label": "Token Millionaire",
    "smart_money": true
  },
  "change": {
    "old_rank": 5,
    "new_rank": 2,
    "rank_delta": 3,
    "old_score": 0.65,
    "new_score": 0.78,
    "score_delta": 0.13
  },
  "current_dimensions": {
    "growth": 0.72,
    "drawdown": 0.99,
    "leverage": 0.85,
    "liq_distance": 1.00,
    "diversity": 0.88,
    "consistency": 0.60
  },
  "previous_dimensions": {
    "growth": 0.55,
    "drawdown": 0.92,
    "leverage": 0.80,
    "liq_distance": 0.95,
    "diversity": 0.88,
    "consistency": 0.60
  },
  "top_movers": [
    {"dimension": "growth", "delta": 0.17},
    {"dimension": "drawdown", "delta": 0.07},
    {"dimension": "leverage", "delta": 0.05}
  ],
  "context": {
    "top_5_wallets": [
      {"address": "0x...", "label": "...", "score": 0.80, "rank": 1},
      {"address": "0x...", "label": "...", "score": 0.78, "rank": 2}
    ]
  }
}
```

---

## Module 2: Chart Generator (`src/chart_generator.py`)

**Purpose:** Generate visually varied chart images to accompany the post.

**Chart types (randomly pick 1-2 per post):**

1. **Radar/spider chart** — 6 dimensions for the spotlight wallet, shows the profile shape
2. **Before/after bar chart** — yesterday vs today scores for top 5, mover highlighted
3. **Score heatmap** — top 5-10 wallets × 6 dimensions, color-coded cells
4. **Rank trajectory line chart** — wallet's rank over past 7-14 days
5. **Dimension delta chart** — horizontal bars showing which dimensions changed most

**Visual consistency:**
- Consistent dark theme / color palette across all chart types
- Brand-consistent styling so charts look cohesive despite type variation
- Output to `data/charts/` as PNGs

**Input:** `data/content_payload.json` (plus additional historical data from `score_snapshots` table for trajectory charts)

**Output:** 1-2 PNG files in `data/charts/`

---

## Module 3: Typefully Client (`src/typefully_client.py`)

**Purpose:** Wrapper around Typefully API v2 for creating drafts with media.

**Config (in `.env`):**
- `TYPEFULLY_API_KEY` — Bearer token
- `TYPEFULLY_SOCIAL_SET_ID` — fetched once via `GET /v2/social-sets`, stored in config

**Functions:**
- `upload_media(file_path: str) -> str` — upload PNG, return `media_id`
- `create_draft(posts: list[dict], draft_title: str) -> dict` — create draft with text + media attachments, return draft URL
- `get_media_status(media_id: str) -> str` — poll until media is `ready`

**Draft creation payload structure:**
```json
{
  "platforms": {
    "x": {
      "enabled": true,
      "posts": [
        {"text": "tweet 1 text", "media": ["media_id_1"]},
        {"text": "tweet 2 text"}
      ]
    }
  },
  "draft_title": "Wallet Spotlight — 2026-03-08"
}
```

**CLI interface for Claude Code to call:**
```bash
python -m src.typefully_client \
  --posts '["tweet1", "tweet2"]' \
  --media data/charts/radar_chart.png data/charts/rank_trajectory.png \
  --title "Wallet Spotlight — 2026-03-08"
```

---

## Module 4: Writer Agent Team

**Invoked by:** Claude Code (`cldy`) via `scripts/content-prompt.md`

**Inputs available to all agents:**
- `data/content_payload.json` — the signal data
- `x_writer/writing_style.md` — do's and don'ts
- `x_writer/studied_x_writiing_styles.md` — Cryptor reference posts
- `x_writer/review_notes.md` — editorial pitfalls from previous review
- `data/charts/*.png` — generated chart images

### Agent 1: Drafter

- Reads payload + all 3 writing reference files
- Randomly picks 1 of the 8 style variations
- Writes first draft (1-3 tweets, wallet spotlight)
- Decides which chart(s) pair with which tweet
- Outputs: draft text + chart placement

### Agent 2: CT Editor

- Reads draft + same 3 reference files
- Reviews against writing style rules and review_notes.md pitfalls
- Checklist:
  - Does it sound like a real trader or a product pitch?
  - Any em dashes? Banned phrases?
  - Are numbers interpreted, not just listed?
  - Each tweet under 280 characters?
  - Is there a take, not just data?
- Rewrites problem areas, outputs improved version

### Agent 3: Final Polish

- Reads improved draft + `studied_x_writiing_styles.md` only
- Pure vibe check: does this read like something Cryptor would post?
- Checks sentence rhythm, tone, CT lingo
- Makes final tweaks, outputs publish-ready version

### After Agent 3:

- Upload chart PNGs via `src/typefully_client.py`
- Create Typefully draft with final text + attached media
- Log the draft URL

---

## Cron Setup

```bash
# Crontab entry — daily at 08:00 UTC
0 8 * * *  cd /home/jsong407/hyper-strategies-pnl-weighted && python -m src.content_pipeline && [ -f data/content_payload.json ] && grep -q '"post_worthy": true' data/content_payload.json && python -m src.chart_generator && cldy -p "scripts/content-prompt.md"
```

**Chain logic:**
1. `python -m src.content_pipeline` — detect movers, write payload
2. Shell checks `post_worthy` — if false, chain stops, zero Claude Code cost
3. `python -m src.chart_generator` — render charts from payload
4. `cldy -p "scripts/content-prompt.md"` — Claude Code wakes up, runs writer agent team, pushes to Typefully

---

## New Files

| File | Purpose |
|------|---------|
| `src/content_pipeline.py` | Detection module — score mover detection, payload generation |
| `src/chart_generator.py` | Chart rendering — 5 chart types, random selection, dark theme |
| `src/typefully_client.py` | Typefully API wrapper — media upload, draft creation |
| `scripts/content-prompt.md` | Standing instructions for Claude Code writer agent team |

## Modified Files

| File | Change |
|------|--------|
| `src/datastore.py` | Add `score_snapshots` table + snapshot CRUD methods |
| `src/scheduler.py` | Add daily snapshot job after metrics recompute |
| `.env.example` | Add `TYPEFULLY_API_KEY`, `TYPEFULLY_SOCIAL_SET_ID` |
| `src/config.py` | Add content pipeline config (thresholds, chart settings) |

## No Changes To

- Frontend (can be shut down or kept private)
- Existing backend API routers
- Existing scoring/metrics/allocation logic
