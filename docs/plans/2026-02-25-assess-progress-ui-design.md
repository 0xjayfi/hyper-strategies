# Assess Page: Progress Animation & Nansen Branding

**Date:** 2026-02-25
**Status:** Approved

## Overview

Enhance the assess trader page with a simulated progress animation for slow requests and light Nansen branding. The loading experience only appears when the API response takes longer than 300ms (uncached addresses). Cached results render instantly with no loading UI.

## Design Decisions

- **Progress type:** Simulated step-by-step animation (no backend changes)
- **Visibility threshold:** 300ms delay — progress UI only mounts if query is still pending
- **Nansen branding:** Light touch — compass icon + "Powered by Nansen" attribution, Nansen green (#00FFA7) on progress bar only
- **Step count:** 6 steps matching the real backend flow

## Delayed Loading Hook

`useDelayedLoading(300)` returns `true` only after 300ms. The assess query fires immediately — if data returns before 300ms, the progress component never renders. If still pending at 300ms, the progress animation begins.

## Progress Stepper Component

`<AssessmentProgress>` renders inside the existing `<PageLayout>`, centered in `max-w-2xl`.

**Layout (top to bottom):**
- Large percentage counter (smooth `requestAnimationFrame` interpolation)
- Horizontal progress bar with Nansen green (#00FFA7) fill
- 6-row vertical step list with dot indicators (grey=pending, green pulse=active, green+check=complete)
- "Powered by Nansen" attribution with compass icon

**Timing (total ~50s):**

| Step | Label | Duration | Cumulative % |
|------|-------|----------|-------------|
| 1 | Checking cache... | 1s | 0-5% |
| 2 | Fetching positions from Nansen... | 5s | 5-20% |
| 3 | Fetching trade history... | 20s | 20-65% |
| 4 | Computing metrics... | 7s | 65-80% |
| 5 | Running 10 scoring strategies... | 7s | 80-95% |
| 6 | Finalizing assessment... | 5s | 95-99% |

Percentage pauses at 99% until the actual API response arrives. On response: jumps to 100%, all steps check off, 200ms "complete" flash, then results render.

## Nansen Branding

- **Compass icon:** Inline SVG, used at 16px in progress stepper and results header
- **Nansen green (#00FFA7):** Progress bar fill and active step dot pulse only. Does not replace existing accent color (#58a6ff)
- **Attribution:** "Powered by Nansen" in progress stepper, "Data by Nansen" in results header next to cached badge
- **No theme changes:** Results page, radar chart, scorecard keep current colors

## File Changes

**New files:**
- `frontend/src/hooks/useDelayedLoading.ts`
- `frontend/src/components/assess/AssessmentProgress.tsx`
- `frontend/src/components/icons/NansenIcon.tsx`

**Modified files:**
- `frontend/src/pages/AssessmentResults.tsx` — replace `<LoadingState>` with delayed progress logic, add Nansen attribution in results header

**No backend changes.**
