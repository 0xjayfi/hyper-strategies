# Mobile Responsiveness Design

## Goal

Adapt the frontend dashboard to work cleanly on phone screens (375–430px). Tablet (768–1023px) benefits naturally from phone-first fixes.

## Decisions

- **Target**: Phone-first (< 768px breakpoint)
- **Tables**: Hybrid — card variants for complex tables, horizontal scroll for simple ones
- **Charts**: All visible and full-width on mobile
- **Navigation**: Hamburger slide-out menu replaces sidebar on mobile

## Breakpoints

| Range | Label | Behavior |
|-------|-------|----------|
| < 768px (md) | Mobile | All mobile adaptations active |
| 768px–1023px | Tablet | Benefits from mobile fixes + existing lg breakpoints |
| >= 1024px (lg) | Desktop | Unchanged |

## 1. Layout & Navigation

**Sidebar → Hamburger menu (< md):**
- Hide sidebar completely (`hidden md:flex`)
- Add hamburger icon button to left side of Header
- Slide-out overlay from left: full height, ~280px wide, semi-transparent backdrop
- Contains same nav links + connection status indicator
- Tap link or backdrop to close
- State managed in PageLayout — no new libraries

**PageLayout:**
- Remove left padding/margin for sidebar on mobile
- Content takes full viewport width
- Page description panel: full-width, smaller padding on mobile

**Header:**
- Add hamburger button (visible only below md)
- Reduce padding: `px-4` instead of `px-6` on mobile
- Title + refresh button remain, "Updated X ago" wraps naturally

## 2. Tables

### Card variants (too many columns to scroll):

**LeaderboardTable** (8+ columns):
- Card: address + rank at top, 2x2 grid of key metrics (PnL, ROI, Win Rate, Score), allocation weight bar at bottom
- Tap → navigate to Trader Deep Dive

**TradeHistoryTable** (7 columns):
- Card: token badge + side badge top row, entry/exit prices second row, PnL prominent, timestamp muted

**ScorecardTable** (5 columns with long text):
- Card: strategy name + pass/fail badge top, score bar, explanation text below

### Horizontal scroll (fewer columns, work fine):

- PositionTable — `overflow-x-auto` wrapper
- IndexPortfolioTable — `overflow-x-auto` wrapper
- PositionsTable (Trader Deep Dive) — `overflow-x-auto` wrapper

### Implementation pattern:

- `useIsMobile()` hook: `window.matchMedia` listener for `max-width: 768px`
- Card variant components alongside their table files (e.g., `LeaderboardCard.tsx`)
- Toggle between table/cards using the hook

## 3. Charts & Visualizations

All charts full-width on mobile with adjusted heights:

| Chart | Current Behavior | Mobile Behavior |
|-------|-----------------|-----------------|
| ScoreRadarChart (Leaderboard) | Hidden sidebar, `lg:block` | Full-width above table, 250px height |
| RadarSection (Assessment) | Inline | Full-width, 250px height |
| WeightsDonut (Allocation) | 3/5 column grid | Full-width, 250px height, stacked above gauges |
| RiskGauges (Allocation) | 2/5 column grid | Full-width horizontal bars below donut |
| AllocationTimeline | Inline | Full-width, ~200px height |
| PnlCurveChart (Trader) | Inline | Full-width, 250px height |
| Token cards grid (Market) | `grid-cols-2` | `grid-cols-1` |
| ConsensusCards (Allocation) | Grid | Stack vertically |

## 4. Typography & Spacing

**Font sizes (< md):**
- Page titles: `text-2xl` → `text-xl`
- Section headings: `text-lg` → `text-base`
- Body text: `text-sm` (unchanged)
- Muted text: `text-xs` (unchanged)
- Large metrics: `text-xl` → `text-lg`

**Spacing (< md):**
- Page padding: `p-6` → `p-4`
- Card padding: `p-4` → `p-3`
- Grid gaps: `gap-6` → `gap-4`, `gap-4` → `gap-3`
- Section margins: `space-y-6` → `space-y-4`

**Overflow prevention:**
- Text containers: `overflow-hidden text-ellipsis` where needed
- Main content: `overflow-x-hidden`
- Tab bars: `overflow-x-auto whitespace-nowrap`

**Touch targets:**
- All clickable elements minimum 44px height
- Filter toggles get larger tap areas on mobile

## 5. Page-by-Page Summary

| Page | Layout Changes | Component Changes |
|------|---------------|-------------------|
| Market Overview | Token grid: 2-col → 1-col | TokenCards full-width, reduce padding |
| Position Explorer | Filters wrap vertically, table `overflow-x-auto` | PositionFilters stack, meta stats wrap |
| Leaderboard | Radar chart above table (not sidebar) | LeaderboardTable → LeaderboardCard list |
| Trader Deep Dive | All sections stack vertically | PnL chart 250px, TradeHistory → cards, Positions horizontal scroll |
| Allocation Dashboard | Donut + Gauges → vertical stack, tabs scroll | WeightsDonut/RiskGauges full-width, IndexPortfolio horizontal scroll, Consensus stack, SizingCalculator inputs stack |
| Assess Trader | Form full-width, history full-width | Minimal changes |
| Assessment Results | Radar full-width above scorecard | ScorecardTable → cards |

## 6. New Files

- `src/hooks/useIsMobile.ts` — shared media query hook
- `src/components/leaderboard/LeaderboardCard.tsx` — mobile card variant
- `src/components/trader/TradeHistoryCard.tsx` — mobile card variant
- `src/components/shared/ScorecardCard.tsx` — mobile card variant
- `src/components/layout/MobileNav.tsx` — hamburger slide-out overlay

## 7. Modified Files (~20)

- `PageLayout.tsx` — mobile padding, hamburger state, hide sidebar
- `Header.tsx` — hamburger button, mobile padding
- `Sidebar.tsx` — `hidden md:flex`
- `MarketOverview.tsx` — grid responsive classes
- `TokenCard.tsx` — mobile padding/font
- `PositionExplorer.tsx` — filter stacking, table wrapper
- `PositionFilters.tsx` — vertical stack on mobile
- `PositionTable.tsx` — overflow-x-auto wrapper
- `TraderLeaderboard.tsx` — radar chart placement
- `LeaderboardTable.tsx` — toggle to cards on mobile
- `ScoreRadarChart.tsx` — mobile sizing
- `TraderDeepDive.tsx` — section stacking
- `PnlCurveChart.tsx` — mobile height
- `TradeHistoryTable.tsx` — toggle to cards on mobile
- `AllocationDashboard.tsx` — grid stacking, tab scroll
- `WeightsDonut.tsx` — full-width mobile
- `RiskGauges.tsx` — full-width mobile
- `AllocationTimeline.tsx` — mobile height
- `ConsensusCards.tsx` — stack vertically
- `SizingCalculator.tsx` — inputs stack vertically
- `AssessmentResults.tsx` — radar placement, scorecard toggle

No files deleted. No library additions.
