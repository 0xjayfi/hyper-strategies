# UI Tooltips, Intro Section & Position Explorer Fixes

**Date:** 2026-02-27
**Status:** Approved

## Overview

Four UI improvements: hover tooltips on leaderboard and deep dive score components, an educational intro section for the Allocation Over Time chart, and layout/copy fixes on the Position Explorer detail row.

## 1. Reusable Tooltip Component

**File:** `frontend/src/components/ui/Tooltip.tsx`

A lightweight ~30-line component using Tailwind `group`/`group-hover`:
- Dark background (`bg-[#1c2128]`), border, rounded, small text
- Positioned above the wrapped element
- Mobile: appears on tap via `focus-within`
- Props: `text: string`, `children: ReactNode`

No external dependencies.

## 2. Leaderboard Score Tooltips

**Files:** `LeaderboardTable.tsx`, `LeaderboardCard.tsx`

Wrap each score column header and mobile card label with `<Tooltip>`.

| Component | Tooltip Text |
|-----------|-------------|
| Growth | Measures PnL growth relative to account size. Higher = more profitable trading. |
| Drawdown | Penalizes large peak-to-trough equity drops. Higher = more controlled losses. |
| Leverage | Scores conservative leverage usage. Higher = less risky position sizing. |
| Liq Dist | Liquidation distance — how far positions are from forced liquidation. Higher = safer margins. |
| Diversity | Rewards trading across multiple assets. Higher = less concentrated risk. |
| Consistency | Measures steadiness of returns over time. Higher = less volatile performance. |

## 3. Deep Dive Score Breakdown Tooltips

**File:** `ScoreBreakdown.tsx`

Wrap each score label with `<Tooltip>`.

| Component | Tooltip Text |
|-----------|-------------|
| ROI | Return on investment across all closed trades. |
| Sharpe | Risk-adjusted returns — higher means better return per unit of risk. |
| Win Rate | Percentage of trades that closed with positive PnL. |
| Consistency | Steadiness of returns across time periods. |
| Smart Money | Bonus for addresses tagged as smart money by Nansen. |
| Risk Mgmt | Composite of leverage, drawdown, and liquidation distance behavior. |

## 4. Allocation Over Time Intro

**File:** `AllocationTimeline.tsx`

Add a `<p>` below the "Allocation Over Time" heading:

> This chart tracks how your portfolio's capital allocation shifts across tracked traders over time. Weights are recalculated every 6 hours based on updated performance scores. Rising allocations indicate improving trader performance, while declining weights suggest deteriorating metrics. Use this to understand how the system dynamically rebalances exposure.

## 5. Position Explorer Fixes

**File:** `PositionRowDetail.tsx`

### Address Overlap
- Add `truncate max-w-[180px]` to the `<code>` element
- Change `grid-cols-4` to `grid-cols-2 sm:grid-cols-4` for mobile responsiveness

### Copy Icon
- Wrap `navigator.clipboard.writeText()` in try/catch
- Add fallback using `document.execCommand('copy')` for non-HTTPS contexts
- Add `title="Copy address"` to the button for discoverability
