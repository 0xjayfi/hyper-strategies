# UI Tooltips, Intro Section & Position Explorer Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add hover tooltips to score components on leaderboard and deep dive pages, add an educational intro to the Allocation Over Time chart, and fix address overlap + broken copy on Position Explorer.

**Architecture:** Reusable `<Tooltip>` component using Tailwind CSS `group-hover` + `focus-within` (no deps). Applied to column headers in the leaderboard table, score labels in the deep dive breakdown, and a new paragraph in the allocation timeline. Position explorer gets CSS overflow fix + clipboard API fallback.

**Tech Stack:** React 19, Tailwind CSS 4, Lucide React icons, TypeScript

---

### Task 1: Create Reusable Tooltip Component

**Files:**
- Create: `frontend/src/components/shared/Tooltip.tsx`

**Step 1: Create the Tooltip component**

```tsx
import type { ReactNode } from 'react';

interface TooltipProps {
  text: string;
  children: ReactNode;
}

export function Tooltip({ text, children }: TooltipProps) {
  return (
    <span className="group relative inline-flex cursor-help">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 whitespace-normal rounded border border-border bg-[#1c2128] px-2.5 py-1.5 text-xs font-normal text-text-primary opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-w-[220px] text-center leading-snug"
      >
        {text}
      </span>
    </span>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/shared/Tooltip.tsx
git commit -m "feat: add reusable Tooltip component"
```

---

### Task 2: Add Tooltips to Leaderboard Table Headers

**Files:**
- Modify: `frontend/src/components/leaderboard/LeaderboardTable.tsx`

**Step 1: Add tooltip definitions and update column headers**

Add import at top of file:
```tsx
import { Tooltip } from '../shared/Tooltip';
```

Add tooltip map before the `columns` definition (after `MiniScoreBar`):
```tsx
const SCORE_TOOLTIPS: Record<string, string> = {
  Growth: 'Measures PnL growth relative to account size. Higher = more profitable trading.',
  Drawdown: 'Penalizes large peak-to-trough equity drops. Higher = more controlled losses.',
  Leverage: 'Scores conservative leverage usage. Higher = less risky position sizing.',
  'Liq Dist': 'Liquidation distance — how far positions are from forced liquidation. Higher = safer margins.',
  Diversity: 'Rewards trading across multiple assets. Higher = less concentrated risk.',
  Consistency: 'Measures steadiness of returns over time. Higher = less volatile performance.',
};
```

Change each score column's `header` field from a plain string to a function that wraps in `<Tooltip>`. Update these 6 column definitions:

```tsx
  columnHelper.accessor('score_growth', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Growth']}>Growth</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_drawdown', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Drawdown']}>Drawdown</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_leverage', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Leverage']}>Leverage</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_liq_distance', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Liq Dist']}>Liq Dist</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_diversity', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Diversity']}>Diversity</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_consistency', {
    header: () => <Tooltip text={SCORE_TOOLTIPS['Consistency']}>Consistency</Tooltip>,
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/leaderboard/LeaderboardTable.tsx
git commit -m "feat: add hover tooltips to leaderboard score columns"
```

---

### Task 3: Add Tooltips to Leaderboard Mobile Cards

**Files:**
- Modify: `frontend/src/components/leaderboard/LeaderboardCard.tsx`

**Step 1: Add tooltip import and wrap labels**

Add import:
```tsx
import { Tooltip } from '../shared/Tooltip';
```

In the 2x2 metrics grid, wrap the label `<span>` elements with `<Tooltip>`. Use the same `SCORE_TOOLTIPS` map — but since this file only shows Score, Growth, Drawdown, and Weight, we only add tooltips to Growth and Drawdown:

Replace the metrics grid section (the `<div className="grid grid-cols-2 ...">` block):

```tsx
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div>
              <span className="text-[10px] text-text-muted">Score</span>
              <MiniBar value={trader.score} />
            </div>
            <div>
              <Tooltip text="Measures PnL growth relative to account size. Higher = more profitable trading.">
                <span className="text-[10px] text-text-muted">Growth</span>
              </Tooltip>
              <MiniBar value={trader.score_growth} />
            </div>
            <div>
              <Tooltip text="Penalizes large peak-to-trough equity drops. Higher = more controlled losses.">
                <span className="text-[10px] text-text-muted">Drawdown</span>
              </Tooltip>
              <MiniBar value={trader.score_drawdown} />
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Weight</span>
              <div className="font-mono-nums text-sm text-text-primary">
                {trader.allocation_weight != null
                  ? `${(trader.allocation_weight * 100).toFixed(1)}%`
                  : '—'}
              </div>
            </div>
          </div>
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/leaderboard/LeaderboardCard.tsx
git commit -m "feat: add hover tooltips to mobile leaderboard cards"
```

---

### Task 4: Add Tooltips to Deep Dive Score Breakdown

**Files:**
- Modify: `frontend/src/components/trader/ScoreBreakdown.tsx`

**Step 1: Add tooltip definitions and wrap score labels**

Add import:
```tsx
import { Tooltip } from '../shared/Tooltip';
```

Update `SCORE_COMPONENTS` to include tooltip text:
```tsx
const SCORE_COMPONENTS = [
  { key: 'roi', label: 'ROI', tip: 'Return on investment across all closed trades.' },
  { key: 'sharpe', label: 'Sharpe', tip: 'Risk-adjusted returns — higher means better return per unit of risk.' },
  { key: 'win_rate', label: 'Win Rate', tip: 'Percentage of trades that closed with positive PnL.' },
  { key: 'consistency', label: 'Consistency', tip: 'Steadiness of returns across time periods.' },
  { key: 'smart_money', label: 'Smart Money', tip: 'Bonus for addresses tagged as smart money by Nansen.' },
  { key: 'risk_mgmt', label: 'Risk Mgmt', tip: 'Composite of leverage, drawdown, and liquidation distance behavior.' },
] as const;
```

In the `.map()` render, wrap the label `<span>` with `<Tooltip>`:

Change:
```tsx
<span className="w-24 shrink-0 text-xs text-text-muted">{comp.label}</span>
```

To:
```tsx
<Tooltip text={comp.tip}>
  <span className="w-24 shrink-0 text-xs text-text-muted">{comp.label}</span>
</Tooltip>
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/trader/ScoreBreakdown.tsx
git commit -m "feat: add hover tooltips to deep dive score breakdown"
```

---

### Task 5: Add Educational Intro to Allocation Over Time

**Files:**
- Modify: `frontend/src/components/allocation/AllocationTimeline.tsx`

**Step 1: Add intro paragraph below the heading**

In the return JSX, between the `<h3>` heading and the `<ResponsiveContainer>`, add:

```tsx
      <p className="mb-3 text-xs leading-relaxed text-text-muted">
        This chart tracks how capital allocation shifts across tracked traders over time.
        Weights are recalculated every 6 hours based on updated performance scores.
        Rising allocations indicate improving trader performance, while declining weights
        suggest deteriorating metrics. Use this to understand how the system dynamically
        rebalances exposure.
      </p>
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/allocation/AllocationTimeline.tsx
git commit -m "feat: add educational intro to Allocation Over Time section"
```

---

### Task 6: Fix Position Explorer Address Overlap + Copy Icon

**Files:**
- Modify: `frontend/src/components/positions/PositionRowDetail.tsx`

**Step 1: Fix address overflow and grid responsiveness**

Change `grid-cols-4` to responsive:
```tsx
<div className="grid grid-cols-2 gap-4 text-xs sm:grid-cols-4 sm:gap-6">
```

Add `truncate` and max-width to the address `<code>`:
```tsx
<code className="truncate font-mono-nums text-text-primary max-w-[180px]">{position.address}</code>
```

**Step 2: Fix copy handler with try/catch and fallback**

Replace the `handleCopy` function:
```tsx
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(position.address);
    } catch {
      // Fallback for non-HTTPS contexts
      const textarea = document.createElement('textarea');
      textarea.value = position.address;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
```

**Step 3: Add title to copy button for discoverability**

```tsx
<button onClick={handleCopy} title="Copy address" className="shrink-0 text-text-muted hover:text-text-primary">
```

**Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/components/positions/PositionRowDetail.tsx
git commit -m "fix: address overlap with funding USD and broken copy icon on position explorer"
```

---

### Task 7: Visual Verification

**Step 1: Start dev server**

Run: `cd frontend && npm run dev`

**Step 2: Verify each fix in browser**

- [ ] Leaderboard: hover over Growth/Drawdown/Leverage/Liq Dist/Diversity/Consistency headers — tooltips appear
- [ ] Leaderboard mobile: tap Growth/Drawdown labels — tooltips appear
- [ ] Deep Dive: click a trader → Score Breakdown → hover ROI/Sharpe/Win Rate/Consistency/Smart Money/Risk Mgmt — tooltips appear
- [ ] Allocation Over Time: intro paragraph visible below heading
- [ ] Position Explorer: click an address row → address is truncated, not overlapping Funding USD
- [ ] Position Explorer: click copy icon → address copies to clipboard, check icon shows

**Step 3: Final commit if any tweaks needed**
