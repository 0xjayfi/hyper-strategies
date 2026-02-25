# Assess Page Progress Animation & Nansen Branding — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a simulated progress stepper with Nansen branding to the assess page loading state, shown only for slow requests (>300ms).

**Architecture:** A `useDelayedLoading` hook gates visibility. A new `<AssessmentProgress>` component renders an animated vertical stepper with percentage counter, progress bar, and Nansen attribution. The Nansen compass icon is an inline SVG component. No backend changes.

**Tech Stack:** React 19, Tailwind CSS 4, lucide-react for checkmarks, requestAnimationFrame for smooth animation.

---

### Task 1: Create `useDelayedLoading` Hook

**Files:**
- Create: `frontend/src/hooks/useDelayedLoading.ts`

**Step 1: Create the hook**

```ts
import { useState, useEffect } from 'react';

/**
 * Returns `true` only after `delayMs` has elapsed.
 * If the component unmounts before the delay, it never returns true.
 * Use this to avoid flashing loading UI for fast responses.
 */
export function useDelayedLoading(delayMs: number = 300): boolean {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShow(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  return show;
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useDelayedLoading.ts
git commit -m "feat(assess): add useDelayedLoading hook"
```

---

### Task 2: Create Nansen Compass Icon Component

**Files:**
- Create: `frontend/src/components/icons/NansenIcon.tsx`

The Nansen compass icon is a stylized compass with crossing elliptical orbital paths and a diamond center point. Recreate as an inline SVG from the brand guidelines (page 21). The icon should accept `className` for sizing via Tailwind.

**Step 1: Create the icon component**

```tsx
import type { SVGProps } from 'react';

/**
 * Nansen compass icon — stylized orbital paths with diamond center.
 * Recreated from Nansen Brand Guidelines (Aug 2023).
 */
export function NansenIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      {/* Three crossing elliptical orbital paths */}
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(0 32 32)"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(60 32 32)"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(120 32 32)"
      />
      {/* Center diamond point */}
      <rect
        x="29"
        y="29"
        width="6"
        height="6"
        rx="1"
        transform="rotate(45 32 32)"
        fill="currentColor"
      />
    </svg>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/icons/NansenIcon.tsx
git commit -m "feat(assess): add Nansen compass icon SVG component"
```

---

### Task 3: Create `<AssessmentProgress>` Component

**Files:**
- Create: `frontend/src/components/assess/AssessmentProgress.tsx`

This is the main component — a vertical stepper with animated percentage, progress bar, step list, and Nansen attribution.

**Step 1: Create the component**

```tsx
import { useState, useEffect, useRef, useCallback } from 'react';
import { Check } from 'lucide-react';
import { NansenIcon } from '../icons/NansenIcon';
import { cn } from '../../lib/utils';

const STEPS = [
  { label: 'Checking cache...', startPct: 0, endPct: 5, durationMs: 1000 },
  { label: 'Fetching positions from Nansen...', startPct: 5, endPct: 20, durationMs: 5000 },
  { label: 'Fetching trade history...', startPct: 20, endPct: 65, durationMs: 20000 },
  { label: 'Computing metrics...', startPct: 65, endPct: 80, durationMs: 7000 },
  { label: 'Running 10 scoring strategies...', startPct: 80, endPct: 95, durationMs: 7000 },
  { label: 'Finalizing assessment...', startPct: 95, endPct: 99, durationMs: 5000 },
] as const;

const TOTAL_DURATION_MS = STEPS.reduce((sum, s) => sum + s.durationMs, 0);

function getProgressAtTime(elapsedMs: number): { percentage: number; activeStep: number } {
  let accumulated = 0;
  for (let i = 0; i < STEPS.length; i++) {
    const step = STEPS[i];
    if (elapsedMs <= accumulated + step.durationMs) {
      const stepElapsed = elapsedMs - accumulated;
      const stepProgress = stepElapsed / step.durationMs;
      const percentage = step.startPct + (step.endPct - step.startPct) * stepProgress;
      return { percentage, activeStep: i };
    }
    accumulated += step.durationMs;
  }
  // Past all steps — clamp at 99%
  return { percentage: 99, activeStep: STEPS.length - 1 };
}

export function AssessmentProgress() {
  const [elapsed, setElapsed] = useState(0);
  const startTimeRef = useRef(performance.now());
  const rafRef = useRef<number>(0);

  const tick = useCallback(() => {
    const now = performance.now();
    setElapsed(now - startTimeRef.current);
    rafRef.current = requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [tick]);

  const { percentage, activeStep } = getProgressAtTime(elapsed);
  const displayPct = Math.min(99, Math.round(percentage));

  return (
    <div className="mx-auto max-w-md py-12">
      {/* Percentage counter */}
      <div className="mb-6 text-center">
        <span className="text-5xl font-bold tabular-nums text-text-primary">
          {displayPct}
          <span className="text-3xl text-text-muted">%</span>
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-8 h-1.5 w-full overflow-hidden rounded-full bg-surface">
        <div
          className="h-full rounded-full transition-[width] duration-300 ease-linear"
          style={{
            width: `${percentage}%`,
            backgroundColor: '#00FFA7',
          }}
        />
      </div>

      {/* Step list */}
      <div className="space-y-3">
        {STEPS.map((step, i) => {
          const isComplete = i < activeStep;
          const isActive = i === activeStep;
          const isPending = i > activeStep;

          return (
            <div key={step.label} className="flex items-center gap-3">
              {/* Dot / check indicator */}
              <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                {isComplete ? (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full" style={{ backgroundColor: '#00FFA7' }}>
                    <Check className="h-3 w-3 text-[#0d1117]" strokeWidth={3} />
                  </div>
                ) : isActive ? (
                  <div className="relative flex h-3 w-3 items-center justify-center">
                    <div
                      className="absolute h-3 w-3 animate-ping rounded-full opacity-40"
                      style={{ backgroundColor: '#00FFA7' }}
                    />
                    <div
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: '#00FFA7' }}
                    />
                  </div>
                ) : (
                  <div className="h-2 w-2 rounded-full bg-border" />
                )}
              </div>

              {/* Label */}
              <span
                className={cn(
                  'text-sm transition-colors duration-300',
                  isComplete && 'text-text-muted',
                  isActive && 'text-text-primary font-medium',
                  isPending && 'text-text-muted/50',
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Nansen attribution */}
      <div className="mt-10 flex items-center justify-center gap-1.5 text-text-muted/60">
        <NansenIcon className="h-4 w-4" />
        <span className="text-xs">Powered by Nansen</span>
      </div>
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/assess/AssessmentProgress.tsx
git commit -m "feat(assess): add AssessmentProgress stepper component"
```

---

### Task 4: Integrate into `AssessmentResults` Page

**Files:**
- Modify: `frontend/src/pages/AssessmentResults.tsx`

Replace the current `<LoadingState>` block with the delayed progress logic. Add Nansen attribution in the results header.

**Step 1: Update imports and loading block**

In `AssessmentResults.tsx`, replace the current loading section (lines 1-9 imports, and lines 124-130 loading block) with the new logic.

Updated imports — add:
```ts
import { useDelayedLoading } from '../hooks/useDelayedLoading';
import { AssessmentProgress } from '../components/assess/AssessmentProgress';
import { NansenIcon } from '../components/icons/NansenIcon';
```

Remove this import (no longer needed):
```ts
import { LoadingState } from '../components/shared/LoadingState';
```

Replace the loading block (lines 124-130):
```tsx
  // OLD:
  if (isLoading) {
    return (
      <PageLayout title="Assessing Trader...">
        <LoadingState message="Fetching trades and computing strategies..." />
      </PageLayout>
    );
  }

  // NEW:
  const showProgress = useDelayedLoading(300);

  if (isLoading) {
    return (
      <PageLayout title="Assessing Trader...">
        {showProgress ? <AssessmentProgress /> : null}
      </PageLayout>
    );
  }
```

**IMPORTANT:** The `useDelayedLoading` hook must be called unconditionally at the top level of the component (React hooks rules). Move it above the early returns. The final structure should be:

```tsx
export function AssessmentResults() {
  const { address } = useParams<{ address: string }>();
  const { data, isLoading, isError, error, refetch } = useAssessment(address || '');
  const isMobile = useIsMobile();
  const showProgress = useDelayedLoading(300);

  if (isLoading) {
    return (
      <PageLayout title="Assessing Trader...">
        {showProgress ? <AssessmentProgress /> : null}
      </PageLayout>
    );
  }

  if (isError || !data) {
    // ... existing error handling unchanged
  }

  // ... rest of component unchanged
```

**Step 2: Add Nansen attribution in results header**

In the results header section (around line 168 where `data.is_cached` badge is), add the Nansen attribution nearby. Insert after the cached badge:

```tsx
{data.is_cached && (
  <span className="rounded bg-surface px-2 py-0.5 text-xs text-text-muted">Cached</span>
)}

{/* Add this right after the cached badge */}
<span className="flex items-center gap-1 text-xs text-text-muted/60">
  <NansenIcon className="h-3.5 w-3.5" />
  Data by Nansen
</span>
```

**Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Manual test — cached address (fast)**

1. Open browser to `/assess/0x5d2f4460ac3514ada79f5d9838916e508ab39bb7`
2. Expected: Results appear instantly (no progress animation visible)
3. Verify "Data by Nansen" attribution visible in header

**Step 5: Manual test — uncached address (slow)**

1. Pick an address NOT in the DB (any valid 0x address)
2. Navigate to `/assess/<that-address>`
3. Expected: After ~300ms delay, progress stepper appears
4. Verify: Percentage counts up smoothly, steps light up in sequence, Nansen green progress bar fills
5. When results arrive: verify smooth transition to results page

**Step 6: Commit**

```bash
git add frontend/src/pages/AssessmentResults.tsx
git commit -m "feat(assess): integrate progress stepper and Nansen attribution"
```

---

### Task 5: Visual Polish & Edge Cases

**Files:**
- Modify: `frontend/src/components/assess/AssessmentProgress.tsx` (if needed)
- Modify: `frontend/src/pages/AssessmentResults.tsx` (if needed)

**Step 1: Test error during loading**

1. Stop the backend
2. Navigate to assess an uncached address
3. Verify: Progress animation shows, then error state renders correctly when request fails
4. Restart backend

**Step 2: Test page navigation during loading**

1. Start assessing an uncached address
2. While progress is showing, click browser back or navigate away
3. Verify: No console errors, animation cleans up (no memory leaks from requestAnimationFrame)

**Step 3: Test mobile view**

1. Open browser DevTools, set viewport to 375px width
2. Navigate to assess page and submit an address
3. Verify: Progress stepper is readable, percentage isn't cut off, steps don't overflow

**Step 4: Final commit (if any fixes needed)**

```bash
git add -u
git commit -m "fix(assess): polish progress stepper edge cases"
```

---

## Summary

| Task | Description | New/Modified Files |
|------|-------------|-------------------|
| 1 | `useDelayedLoading` hook | Create: `hooks/useDelayedLoading.ts` |
| 2 | Nansen compass icon SVG | Create: `components/icons/NansenIcon.tsx` |
| 3 | `AssessmentProgress` stepper | Create: `components/assess/AssessmentProgress.tsx` |
| 4 | Integrate into results page | Modify: `pages/AssessmentResults.tsx` |
| 5 | Visual polish & edge cases | Modify: as needed |
