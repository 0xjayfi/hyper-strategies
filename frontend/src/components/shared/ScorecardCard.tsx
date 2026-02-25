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
