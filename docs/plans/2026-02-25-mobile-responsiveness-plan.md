# Mobile Responsiveness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make all 7 dashboard pages work cleanly on phone screens (375–430px) using a phone-first approach with `< md` (768px) as the mobile breakpoint.

**Architecture:** Approach B — build mobile layout infrastructure (hamburger nav, responsive PageLayout), then fix components in two passes: Tailwind class adjustments for simple components, and dedicated card variant components for complex tables (Leaderboard, TradeHistory, Scorecard). A shared `useIsMobile()` hook toggles between table and card rendering.

**Tech Stack:** React 19, Tailwind CSS 4, Recharts, Lightweight Charts, TanStack React Table, Lucide icons. No new libraries needed.

---

## Task 1: Create `useIsMobile` Hook

**Files:**
- Create: `frontend/src/hooks/useIsMobile.ts`

**Step 1: Create the hook**

```tsx
import { useState, useEffect } from 'react';

const MOBILE_BREAKPOINT = '(max-width: 767px)';

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_BREAKPOINT).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_BREAKPOINT);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return isMobile;
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useIsMobile.ts
git commit -m "feat(mobile): add useIsMobile hook with matchMedia listener"
```

---

## Task 2: Create `MobileNav` Component

**Files:**
- Create: `frontend/src/components/layout/MobileNav.tsx`
- Reference: `frontend/src/components/layout/Sidebar.tsx` (copy NAV_ITEMS + connection status)

**Step 1: Create the component**

```tsx
import { NavLink } from 'react-router';
import { BarChart3, Table, Trophy, PieChart, ClipboardCheck, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useHealthCheck } from '../../api/hooks';

const NAV_ITEMS = [
  { to: '/', label: 'Market Overview', icon: BarChart3 },
  { to: '/positions', label: 'Position Explorer', icon: Table },
  { to: '/leaderboard', label: 'Leaderboard', icon: Trophy },
  { to: '/allocations', label: 'Allocations', icon: PieChart },
  { to: '/assess', label: 'Assess Trader', icon: ClipboardCheck },
] as const;

interface MobileNavProps {
  open: boolean;
  onClose: () => void;
}

export function MobileNav({ open, onClose }: MobileNavProps) {
  const { isSuccess, isError } = useHealthCheck();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Slide-out panel */}
      <aside className="absolute left-0 top-0 flex h-full w-[280px] flex-col bg-card border-r border-border">
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-accent" />
            <span className="text-sm font-semibold text-text-primary">Hyper Signals</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent'
                    : 'text-text-muted hover:bg-surface hover:text-text-primary'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Connection status */}
        <div className="border-t border-border p-3">
          <div className="flex items-center gap-2 rounded-md px-3 py-1.5">
            <span
              className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                isSuccess ? 'bg-green' : isError ? 'bg-red' : 'bg-text-muted'
              )}
            />
            <span className="text-xs text-text-muted">
              {isSuccess ? 'Connected' : isError ? 'Disconnected' : 'Checking...'}
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

**Step 3: Commit**

```bash
git add frontend/src/components/layout/MobileNav.tsx
git commit -m "feat(mobile): add MobileNav slide-out overlay component"
```

---

## Task 3: Update Sidebar, Header, and PageLayout for Mobile Navigation

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx:21` — add `hidden md:flex` to aside
- Modify: `frontend/src/components/layout/Header.tsx` — add hamburger button prop + mobile padding
- Modify: `frontend/src/components/layout/PageLayout.tsx` — add MobileNav state, pass hamburger toggle to Header

### Step 1: Update Sidebar — hide on mobile

In `Sidebar.tsx`, change line 21 (the `<aside>` className):

From:
```tsx
        'flex h-screen flex-col border-r border-border bg-card transition-[width] duration-200',
```
To:
```tsx
        'hidden md:flex h-screen flex-col border-r border-border bg-card transition-[width] duration-200',
```

### Step 2: Update Header — add hamburger button

In `Header.tsx`:

Add import at top:
```tsx
import { RefreshCw, Menu } from 'lucide-react';
```

Update the interface to accept an `onMenuToggle` prop:
```tsx
interface HeaderProps {
  title: string;
  lastUpdated?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  onMenuToggle?: () => void;
}
```

Update the function signature:
```tsx
export function Header({ title, lastUpdated, onRefresh, isRefreshing, onMenuToggle }: HeaderProps) {
```

Update the `<header>` element — change `px-6` to `px-4 md:px-6` and add the hamburger button before the title:
```tsx
      <header className="flex h-14 items-center justify-between border-b border-border px-4 md:px-6">
        <div className="flex items-center gap-3">
          {onMenuToggle && (
            <button
              onClick={onMenuToggle}
              className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary md:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
          )}
          <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
        </div>
```

The right side `<div>` with refresh and timestamp stays unchanged.

### Step 3: Update PageLayout — wire up MobileNav + mobile padding

In `PageLayout.tsx`:

Add imports:
```tsx
import { type ReactNode, useState } from 'react';
import { Info, ChevronDown, ChevronUp } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { MobileNav } from './MobileNav';
```

Add state for mobile nav inside the component:
```tsx
const [showDesc, setShowDesc] = useState(false);
const [mobileNavOpen, setMobileNavOpen] = useState(false);
```

Update the JSX — add MobileNav and pass `onMenuToggle` to Header, and update main padding:
```tsx
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          title={title}
          lastUpdated={lastUpdated}
          onRefresh={onRefresh}
          isRefreshing={isRefreshing}
          onMenuToggle={() => setMobileNavOpen(true)}
        />
        <main className="flex-1 overflow-y-auto overflow-x-hidden p-4 md:p-6">
```

The rest of PageLayout stays unchanged.

### Step 4: Verify build

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

### Step 5: Commit

```bash
git add frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/Header.tsx frontend/src/components/layout/PageLayout.tsx
git commit -m "feat(mobile): add hamburger nav, hide sidebar on mobile, adjust layout padding"
```

---

## Task 4: Create LeaderboardCard Component

**Files:**
- Create: `frontend/src/components/leaderboard/LeaderboardCard.tsx`
- Reference types: `frontend/src/api/types.ts` — `LeaderboardTrader`

**Step 1: Create the card component**

```tsx
import { useNavigate } from 'react-router';
import type { LeaderboardTrader } from '../../api/types';
import { truncateAddress, formatPct } from '../../lib/utils';
import { PnlDisplay } from '../shared/PnlDisplay';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { FilterBadges } from './FilterBadges';

interface LeaderboardCardProps {
  data: LeaderboardTrader[];
  onSelectTrader?: (address: string) => void;
}

export function LeaderboardCardList({ data, onSelectTrader }: LeaderboardCardProps) {
  const navigate = useNavigate();

  return (
    <div className="space-y-3">
      {data.map((trader) => (
        <div
          key={trader.address}
          className="cursor-pointer rounded-lg border border-border bg-card p-3 transition-colors active:bg-card/70"
          onClick={() => {
            onSelectTrader?.(trader.address);
            navigate(`/traders/${trader.address}`);
          }}
        >
          {/* Top row: rank + address + badges */}
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-medium text-text-muted">#{trader.rank}</span>
            <div className="min-w-0 flex-1">
              {trader.label && (
                <span className="block truncate text-sm font-medium text-text-primary">{trader.label}</span>
              )}
              <span className="font-mono-nums text-xs text-text-muted">
                {truncateAddress(trader.address)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {trader.is_smart_money && <SmartMoneyBadge />}
              {trader.anti_luck_status && <FilterBadges status={trader.anti_luck_status} />}
            </div>
          </div>

          {/* 2x2 metrics grid */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div>
              <span className="text-[10px] text-text-muted">PnL</span>
              <div><PnlDisplay value={trader.pnl_usd} compact /></div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">ROI</span>
              <div className={`font-mono-nums text-sm ${trader.roi_pct >= 0 ? 'text-green' : 'text-red'}`}>
                {formatPct(trader.roi_pct)}
              </div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Win Rate</span>
              <div className="font-mono-nums text-sm text-text-primary">
                {trader.win_rate != null ? `${(trader.win_rate * 100).toFixed(1)}%` : '—'}
              </div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Score</span>
              <div className="flex items-center gap-2">
                {trader.score != null ? (
                  <>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${Math.min(trader.score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono-nums text-xs text-text-primary">
                      {trader.score.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-text-muted">—</span>
                )}
              </div>
            </div>
          </div>

          {/* Allocation weight bar */}
          {trader.allocation_weight != null && (
            <div className="mt-2 pt-2 border-t border-border">
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-text-muted">Weight</span>
                <span className="font-mono-nums text-text-primary">
                  {(trader.allocation_weight * 100).toFixed(1)}%
                </span>
              </div>
              <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${trader.allocation_weight * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/leaderboard/LeaderboardCard.tsx
git commit -m "feat(mobile): add LeaderboardCardList component for mobile view"
```

---

## Task 5: Create TradeHistoryCard Component

**Files:**
- Create: `frontend/src/components/trader/TradeHistoryCard.tsx`
- Reference types: `frontend/src/api/types.ts` — `TradeItem`

**Step 1: Create the card component**

```tsx
import type { TradeItem } from '../../api/types';
import { TokenBadge } from '../shared/TokenBadge';
import { PnlDisplay } from '../shared/PnlDisplay';
import { formatUsd } from '../../lib/utils';

interface TradeHistoryCardListProps {
  data: TradeItem[];
}

export function TradeHistoryCardList({ data }: TradeHistoryCardListProps) {
  return (
    <div className="space-y-2">
      {data.map((trade, i) => (
        <div key={i} className="rounded-lg border border-border bg-card p-3">
          {/* Top row: token + side + timestamp */}
          <div className="mb-2 flex items-center gap-2">
            <TokenBadge token={trade.token_symbol} />
            {trade.side && (
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${
                  trade.side === 'Long' ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
                }`}
              >
                {trade.side}
              </span>
            )}
            <span className="ml-auto font-mono-nums text-[10px] text-text-muted">
              {new Date(trade.timestamp).toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>

          {/* Middle row: action + size + price */}
          <div className="mb-2 flex items-center gap-4 text-xs">
            <span className="font-medium text-text-primary">{trade.action}</span>
            <span className="font-mono-nums text-text-muted">
              {formatUsd(trade.value_usd, true)}
            </span>
            <span className="font-mono-nums text-text-muted">
              @ ${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          {/* Bottom row: PnL + fee */}
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] text-text-muted">Closed PnL</span>
              <div><PnlDisplay value={trade.closed_pnl} compact /></div>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-text-muted">Fee</span>
              <div className="font-mono-nums text-xs text-text-muted">{formatUsd(trade.fee_usd)}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/trader/TradeHistoryCard.tsx
git commit -m "feat(mobile): add TradeHistoryCardList component for mobile view"
```

---

## Task 6: Create ScorecardCard Component

**Files:**
- Create: `frontend/src/components/shared/ScorecardCard.tsx`
- Reference: `frontend/src/pages/AssessmentResults.tsx` — `CATEGORY_COLORS`, `AssessmentStrategyResult` type

**Step 1: Create the card component**

```tsx
import { CheckCircle2, XCircle } from 'lucide-react';
import type { AssessmentStrategyResult } from '../../api/types';

const CATEGORY_COLORS: Record<string, string> = {
  'Core Performance': '#58a6ff',
  'Behavioral Quality': '#3fb950',
  'Risk Discipline': '#f0883e',
  'Pattern Quality': '#bc8cff',
};

interface ScorecardCardListProps {
  strategies: AssessmentStrategyResult[];
}

export function ScorecardCardList({ strategies }: ScorecardCardListProps) {
  return (
    <div className="space-y-3">
      {strategies.map((s) => {
        const catColor = CATEGORY_COLORS[s.category] || '#8b949e';

        return (
          <div key={s.name} className="rounded-lg border border-border bg-card p-3">
            {/* Top: strategy name + pass/fail */}
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-text-primary">{s.name}</span>
              {s.passed ? (
                <span className="inline-flex items-center gap-1 text-xs text-green">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Pass
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-red">
                  <XCircle className="h-3.5 w-3.5" /> Fail
                </span>
              )}
            </div>

            {/* Category badge */}
            <span
              className="mb-2 inline-block rounded px-2 py-0.5 text-xs font-medium"
              style={{ color: catColor, backgroundColor: `${catColor}20` }}
            >
              {s.category}
            </span>

            {/* Score bar */}
            <div className="mb-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${s.score}%`,
                    backgroundColor: s.score >= 70 ? '#3fb950' : s.score >= 40 ? '#f0883e' : '#f85149',
                  }}
                />
              </div>
              <span className="text-xs font-mono-nums text-text-muted">{s.score}</span>
            </div>

            {/* Explanation */}
            <p className="text-xs leading-relaxed text-text-muted">{s.explanation}</p>
          </div>
        );
      })}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/shared/ScorecardCard.tsx
git commit -m "feat(mobile): add ScorecardCardList component for mobile view"
```

---

## Task 7: Wire Up Mobile Card Variants in LeaderboardTable and TradeHistoryTable

**Files:**
- Modify: `frontend/src/components/leaderboard/LeaderboardTable.tsx`
- Modify: `frontend/src/components/trader/TradeHistoryTable.tsx`

### Step 1: Update LeaderboardTable

Add at top of `LeaderboardTable.tsx`:
```tsx
import { useIsMobile } from '../../hooks/useIsMobile';
import { LeaderboardCardList } from './LeaderboardCard';
```

At the start of the `LeaderboardTable` function body, add:
```tsx
  const isMobile = useIsMobile();

  if (isMobile) {
    return <LeaderboardCardList data={data} onSelectTrader={onSelectTrader} />;
  }
```

### Step 2: Update TradeHistoryTable

Add at top of `TradeHistoryTable.tsx`:
```tsx
import { useIsMobile } from '../../hooks/useIsMobile';
import { TradeHistoryCardList } from './TradeHistoryCard';
```

At the start of the `TradeHistoryTable` function body, add:
```tsx
  const isMobile = useIsMobile();

  if (isMobile) {
    return <TradeHistoryCardList data={data} />;
  }
```

### Step 3: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 4: Commit

```bash
git add frontend/src/components/leaderboard/LeaderboardTable.tsx frontend/src/components/trader/TradeHistoryTable.tsx
git commit -m "feat(mobile): wire up card variants in LeaderboardTable and TradeHistoryTable"
```

---

## Task 8: Wire Up ScorecardCard in AssessmentResults

**Files:**
- Modify: `frontend/src/pages/AssessmentResults.tsx`

### Step 1: Update AssessmentResults

The `ScorecardTable` is defined inline in `AssessmentResults.tsx`. We need to add the mobile toggle.

Add import at top:
```tsx
import { useIsMobile } from '../hooks/useIsMobile';
import { ScorecardCardList } from '../components/shared/ScorecardCard';
```

Replace the ScorecardTable usage (near the bottom of the `AssessmentResults` component):

From:
```tsx
        {/* Scorecard Table */}
        <ScorecardTable strategies={data.strategies} />
```
To:
```tsx
        {/* Scorecard */}
        {isMobile ? (
          <ScorecardCardList strategies={data.strategies} />
        ) : (
          <ScorecardTable strategies={data.strategies} />
        )}
```

Add `const isMobile = useIsMobile();` at the top of the `AssessmentResults` component body (after the `useAssessment` hook call, before the early returns — must be before any conditional returns so hooks always run in the same order):

Move the hook calls to the top:
```tsx
export function AssessmentResults() {
  const { address } = useParams<{ address: string }>();
  const { data, isLoading, isError, error, refetch } = useAssessment(address || '');
  const isMobile = useIsMobile();
```

Also update the `RadarSection` height to be responsive — in the `RadarSection` function, change `height={400}` to `height={isMobile ? 250 : 400}`. But since `RadarSection` is a local function that doesn't have access to `isMobile`, instead change the ResponsiveContainer height to use a CSS-responsive approach. The simplest fix: change the hard-coded height.

In `RadarSection` component (line 41), change:
```tsx
      <ResponsiveContainer width="100%" height={400}>
```
To:
```tsx
      <ResponsiveContainer width="100%" height={300}>
```

(300px works well on both mobile and desktop)

Also update the header section for mobile wrapping — the `flex-wrap` is already there, so the header items will wrap on narrow screens. But update the address font size:

Change line 155:
```tsx
            <h1 className="font-mono text-lg text-text-primary">{truncateAddress(data.address)}</h1>
```
To:
```tsx
            <h1 className="font-mono text-base md:text-lg text-text-primary">{truncateAddress(data.address)}</h1>
```

### Step 2: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 3: Commit

```bash
git add frontend/src/pages/AssessmentResults.tsx
git commit -m "feat(mobile): add mobile card view for scorecard, responsive radar height"
```

---

## Task 9: Market Overview — Responsive Token Grid

**Files:**
- Modify: `frontend/src/pages/MarketOverview.tsx:73`
- Modify: `frontend/src/components/market/TokenCard.tsx:16`

### Step 1: Update token grid to single column on mobile

In `MarketOverview.tsx`, change line 73:
```tsx
            <div className="grid grid-cols-2 gap-4">
```
To:
```tsx
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:gap-4">
```

Also update the outer spacing on line 60:
```tsx
        <div className="space-y-6">
```
To:
```tsx
        <div className="space-y-4 md:space-y-6">
```

### Step 2: Update TokenCard padding

In `TokenCard.tsx`, change line 16:
```tsx
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
```
To:
```tsx
    <div className="rounded-lg border border-border bg-card p-3 md:p-4 space-y-3">
```

### Step 3: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 4: Commit

```bash
git add frontend/src/pages/MarketOverview.tsx frontend/src/components/market/TokenCard.tsx
git commit -m "feat(mobile): responsive token grid (1-col mobile, 2-col desktop)"
```

---

## Task 10: Position Explorer — Responsive Filters and Meta Stats

**Files:**
- Modify: `frontend/src/pages/PositionExplorer.tsx:88`
- Modify: `frontend/src/components/positions/PositionFilters.tsx:29`

### Step 1: Update meta stats to wrap on mobile

In `PositionExplorer.tsx`, change line 88 (the meta summary div):
```tsx
          <div className="flex gap-6 rounded-lg border border-border bg-card px-4 py-3">
```
To:
```tsx
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card px-3 py-3 md:flex md:gap-6 md:px-4">
```

### Step 2: Update PositionFilters — ensure wrapping and touch targets

In `PositionFilters.tsx`, the filter buttons use `px-3 py-1.5` which is okay for touch. The `flex-wrap` on line 29 already handles wrapping. Add gap adjustment:

Change line 29:
```tsx
    <div className="flex flex-wrap items-center gap-4">
```
To:
```tsx
    <div className="flex flex-wrap items-center gap-3 md:gap-4">
```

### Step 3: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 4: Commit

```bash
git add frontend/src/pages/PositionExplorer.tsx frontend/src/components/positions/PositionFilters.tsx
git commit -m "feat(mobile): responsive meta stats grid and filter spacing"
```

---

## Task 11: Trader Leaderboard — Radar Chart Placement on Mobile

**Files:**
- Modify: `frontend/src/pages/TraderLeaderboard.tsx:136-161`

### Step 1: Move radar chart above table on mobile

Currently the layout is `flex` with table and radar side-by-side, with radar hidden below `lg`. We want radar to show above the table on mobile when a trader is selected.

Replace lines 136-161 (the content section):
```tsx
        {/* Content */}
        <div className="flex gap-4">
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <LoadingState message="Loading leaderboard..." />
            ) : isError ? (
              <ErrorState
                message={error instanceof Error ? error.message : 'Failed to load leaderboard'}
                onRetry={() => refetch()}
              />
            ) : !data || data.traders.length === 0 ? (
              <EmptyState message="No traders found for the selected filters" />
            ) : (
              <LeaderboardTable
                data={data.traders}
                onSelectTrader={setSelectedTrader}
              />
            )}
          </div>

          {/* Radar chart sidebar */}
          {scoreBreakdown && (
            <div className="hidden w-72 shrink-0 lg:block">
              <ScoreRadarChart scoreBreakdown={scoreBreakdown} />
            </div>
          )}
        </div>
```

With:
```tsx
        {/* Radar chart — above table on mobile, sidebar on desktop */}
        {scoreBreakdown && (
          <div className="lg:hidden">
            <ScoreRadarChart scoreBreakdown={scoreBreakdown} />
          </div>
        )}

        {/* Content */}
        <div className="flex gap-4">
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <LoadingState message="Loading leaderboard..." />
            ) : isError ? (
              <ErrorState
                message={error instanceof Error ? error.message : 'Failed to load leaderboard'}
                onRetry={() => refetch()}
              />
            ) : !data || data.traders.length === 0 ? (
              <EmptyState message="No traders found for the selected filters" />
            ) : (
              <LeaderboardTable
                data={data.traders}
                onSelectTrader={setSelectedTrader}
              />
            )}
          </div>

          {/* Radar chart sidebar — desktop only */}
          {scoreBreakdown && (
            <div className="hidden w-72 shrink-0 lg:block">
              <ScoreRadarChart scoreBreakdown={scoreBreakdown} />
            </div>
          )}
        </div>
```

### Step 2: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 3: Commit

```bash
git add frontend/src/pages/TraderLeaderboard.tsx
git commit -m "feat(mobile): show radar chart above leaderboard table on mobile"
```

---

## Task 12: Trader Deep Dive — Responsive Sections

**Files:**
- Modify: `frontend/src/pages/TraderDeepDive.tsx`
- Modify: `frontend/src/components/trader/PnlCurveChart.tsx:44-45,125`

### Step 1: Update PnlCurveChart height for mobile

In `PnlCurveChart.tsx`, change the chart creation height (line 44):
```tsx
      height: 300,
```
To:
```tsx
      height: container.clientWidth < 768 ? 220 : 300,
```

Also change the container div height (line 125):
```tsx
      <div ref={chartContainerRef} style={{ height: 300 }} />
```
To:
```tsx
      <div ref={chartContainerRef} className="h-[220px] md:h-[300px]" />
```

And update the chart creation to not set a fixed height but use the container:
Change line 44 from hardcoded `height: 300` to:
```tsx
      height: container.clientHeight,
```

### Step 2: Update TraderDeepDive spacing

In `TraderDeepDive.tsx`, the outer container already uses `space-y-4` which is fine for mobile. The `grid-cols-1 lg:grid-cols-2` on line 166 is already responsive. No changes needed for the page layout.

Update the TraderHeader font sizes — in `frontend/src/components/trader/TraderHeader.tsx`, change line 33:
```tsx
              <h2 className="text-xl font-semibold text-text-primary">{trader.label}</h2>
```
To:
```tsx
              <h2 className="text-lg md:text-xl font-semibold text-text-primary">{trader.label}</h2>
```

And change the metric values on line 62 and 69 (`text-lg` to `text-base md:text-lg`):
```tsx
                <div className="font-mono-nums text-base md:text-lg text-text-primary">
```
```tsx
                <div className="font-mono-nums text-base md:text-lg text-accent">
```

And change the card padding on line 29:
```tsx
        <div className="rounded-lg border border-border bg-card p-5">
```
To:
```tsx
        <div className="rounded-lg border border-border bg-card p-4 md:p-5">
```

### Step 3: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 4: Commit

```bash
git add frontend/src/pages/TraderDeepDive.tsx frontend/src/components/trader/PnlCurveChart.tsx frontend/src/components/trader/TraderHeader.tsx
git commit -m "feat(mobile): responsive PnL chart height and trader header sizing"
```

---

## Task 13: Allocation Dashboard — Responsive Grid, Tabs, Charts

**Files:**
- Modify: `frontend/src/pages/AllocationDashboard.tsx:108,125-126`
- Modify: `frontend/src/components/allocation/WeightsDonut.tsx:22`
- Modify: `frontend/src/components/allocation/RiskGauges.tsx:60`
- Modify: `frontend/src/components/allocation/ConsensusCards.tsx:59`
- Modify: `frontend/src/components/allocation/SizingCalculator.tsx:69`

### Step 1: Update Allocation Dashboard — donut/gauges grid + tabs

In `AllocationDashboard.tsx`, change line 108 (the donut/gauges grid):
```tsx
            <div className="grid grid-cols-5 gap-4">
              <div className="col-span-3">
                <WeightsDonut allocations={alloc.data.allocations} />
              </div>
              <div className="col-span-2">
                <RiskGauges riskCaps={alloc.data.risk_caps} />
              </div>
            </div>
```
To:
```tsx
            <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
              <div className="md:col-span-3">
                <WeightsDonut allocations={alloc.data.allocations} />
              </div>
              <div className="md:col-span-2">
                <RiskGauges riskCaps={alloc.data.risk_caps} />
              </div>
            </div>
```

Update the tab bar (line 125-126) for horizontal scrolling:
```tsx
              <div className="flex border-b border-border">
```
To:
```tsx
              <div className="flex overflow-x-auto border-b border-border">
```

And update the tab buttons to prevent wrapping:
```tsx
                    className={`px-4 py-2 text-sm font-medium transition-colors ${
```
To:
```tsx
                    className={`whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors ${
```

Update outer spacing on line 90:
```tsx
        <div className="space-y-6">
```
To:
```tsx
        <div className="space-y-4 md:space-y-6">
```

### Step 2: Update RiskGauges — single column on mobile

In `RiskGauges.tsx`, change line 60:
```tsx
        <div className="grid grid-cols-2 gap-4">
```
To:
```tsx
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:gap-4">
```

### Step 3: Update ConsensusCards — responsive grid

In `ConsensusCards.tsx`, change line 59:
```tsx
      <div className="grid grid-cols-4 gap-4">
```
To:
```tsx
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 md:gap-4">
```

### Step 4: Update SizingCalculator — stack inputs on mobile

In `SizingCalculator.tsx`, change line 69:
```tsx
        <div className="grid grid-cols-2 gap-6">
```
To:
```tsx
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6">
```

### Step 5: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 6: Commit

```bash
git add frontend/src/pages/AllocationDashboard.tsx frontend/src/components/allocation/WeightsDonut.tsx frontend/src/components/allocation/RiskGauges.tsx frontend/src/components/allocation/ConsensusCards.tsx frontend/src/components/allocation/SizingCalculator.tsx
git commit -m "feat(mobile): responsive allocation dashboard grids, tabs, and calculator"
```

---

## Task 14: Assess Trader — Minor Mobile Tweaks

**Files:**
- Modify: `frontend/src/pages/AssessTrader.tsx:47`

### Step 1: Reduce top padding on mobile

In `AssessTrader.tsx`, change line 47:
```tsx
      <div className="mx-auto max-w-2xl pt-12">
```
To:
```tsx
      <div className="mx-auto max-w-2xl pt-6 md:pt-12">
```

### Step 2: Verify build

Run: `cd frontend && npx tsc --noEmit`

### Step 3: Commit

```bash
git add frontend/src/pages/AssessTrader.tsx
git commit -m "feat(mobile): reduce top padding on assess trader page for mobile"
```

---

## Task 15: Final Visual QA Pass

This is a manual verification task. Run the dev server and check each page at 375px width using browser dev tools.

### Step 1: Start dev server

Run: `cd frontend && npm run dev`

### Step 2: Checklist to verify in browser (375px width)

For each page, verify:
- [ ] No horizontal scrollbar on the page (except intentional table scroll)
- [ ] Hamburger menu opens/closes properly
- [ ] Nav links work and close the menu
- [ ] All text is readable (no truncation cutting off important info)
- [ ] Cards/grids stack properly in single columns
- [ ] Charts render at full width
- [ ] Touch targets are at least 44px
- [ ] No overlapping elements

Pages to check:
1. `/` — Market Overview: single column token cards
2. `/positions` — Position Explorer: wrapped filters, meta stats grid, scrollable table
3. `/leaderboard` — Leaderboard: card list (not table), radar above when selected
4. `/traders/0x...` — Trader Deep Dive: stacked sections, shorter PnL chart, trade cards
5. `/allocations` — Allocation Dashboard: stacked donut/gauges, scrollable tabs
6. `/assess` — Assess Trader: centered form with less top padding
7. `/assess/0x...` — Assessment Results: radar chart + scorecard cards

### Step 3: Fix any issues found

If any visual issues are found during QA, fix them and commit.

### Step 4: Final commit (if fixes were needed)

```bash
git add -A
git commit -m "fix(mobile): visual QA fixes"
```
