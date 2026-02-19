import type { ConsensusEntry } from '../../api/types';
import { cn } from '../../lib/utils';

interface ConsensusIndicatorProps {
  symbol: string;
  consensus: ConsensusEntry;
}

const DIRECTION_STYLES: Record<string, string> = {
  Bullish: 'bg-green/15 text-green',
  Bearish: 'bg-red/15 text-red',
  Neutral: 'bg-text-muted/15 text-text-muted',
};

export function ConsensusIndicator({ symbol, consensus }: ConsensusIndicatorProps) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 min-w-[140px]">
      <span className="text-xs font-medium text-text-primary">{symbol}</span>

      <span
        className={cn(
          'inline-flex self-start rounded px-1.5 py-0.5 text-xs font-medium',
          DIRECTION_STYLES[consensus.direction] || DIRECTION_STYLES.Neutral
        )}
      >
        {consensus.direction}
      </span>

      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-text-muted">Confidence</span>
          <span className="font-mono-nums text-xs text-text-primary">
            {consensus.confidence.toFixed(0)}%
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
          <div
            className={cn(
              'h-full rounded-full transition-all',
              consensus.direction === 'Bullish' ? 'bg-green' :
              consensus.direction === 'Bearish' ? 'bg-red' : 'bg-text-muted'
            )}
            style={{ width: `${Math.min(consensus.confidence, 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
