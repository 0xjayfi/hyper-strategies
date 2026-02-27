import { Info } from 'lucide-react';
import type { ScoreBreakdown as ScoreBreakdownType } from '../../api/types';
import { Tooltip } from '../shared/Tooltip';

const SCORE_COMPONENTS = [
  { key: 'roi', label: 'ROI', tip: 'Return on investment across all closed trades.' },
  { key: 'sharpe', label: 'Sharpe', tip: 'Risk-adjusted returns — higher means better return per unit of risk.' },
  { key: 'win_rate', label: 'Win Rate', tip: 'Percentage of trades that closed with positive PnL.' },
  { key: 'consistency', label: 'Consistency', tip: 'Steadiness of returns across time periods.' },
  { key: 'smart_money', label: 'Smart Money', tip: 'Bonus for addresses tagged as smart money by Nansen.' },
  { key: 'risk_mgmt', label: 'Risk Mgmt', tip: 'Composite of leverage, drawdown, and liquidation distance behavior.' },
] as const;

interface ScoreBreakdownProps {
  breakdown: ScoreBreakdownType | null;
}

export function ScoreBreakdown({ breakdown }: ScoreBreakdownProps) {
  if (!breakdown) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-medium text-text-primary">Score Breakdown</h3>
        <div className="flex items-center gap-2 py-6 text-center">
          <Info className="mx-auto h-5 w-5 text-text-muted" />
        </div>
        <p className="text-center text-xs text-text-muted">
          Scores not yet computed. Run the allocation engine.
        </p>
      </div>
    );
  }

  const maxScore = Math.max(
    ...SCORE_COMPONENTS.map((c) => breakdown[c.key]),
    0.01
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-medium text-text-primary">Score Breakdown</h3>

      <div className="space-y-3">
        {SCORE_COMPONENTS.map((comp) => {
          const value = breakdown[comp.key];
          const pct = maxScore > 0 ? (value / maxScore) * 100 : 0;
          return (
            <div key={comp.key} className="flex items-center gap-3">
              <Tooltip text={comp.tip}>
                <span className="w-24 shrink-0 text-xs text-text-muted">{comp.label}</span>
              </Tooltip>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
              <span className="w-12 shrink-0 text-right font-mono-nums text-xs text-text-primary">
                {value.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex gap-4 border-t border-border pt-3">
        <div>
          <span className="text-xs text-text-muted">Style Mult.</span>
          <div className="font-mono-nums text-sm text-text-primary">
            {breakdown.style_multiplier.toFixed(2)}x
          </div>
        </div>
        <div>
          <span className="text-xs text-text-muted">Recency Decay</span>
          <div className="font-mono-nums text-sm text-text-primary">
            {breakdown.recency_decay.toFixed(2)}
          </div>
        </div>
        <div>
          <span className="text-xs text-text-muted">Final Score</span>
          <div className="font-mono-nums text-sm font-semibold text-accent">
            {breakdown.final_score.toFixed(3)}
          </div>
        </div>
      </div>
    </div>
  );
}
