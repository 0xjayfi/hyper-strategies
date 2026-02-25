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
      {/* Live analysis banner */}
      <div className="mb-6 rounded-lg border border-border bg-card px-4 py-3 text-center text-sm text-text-muted">
        This address has not been assessed before — running live analysis
      </div>

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
