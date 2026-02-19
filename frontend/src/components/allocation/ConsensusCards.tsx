import type { ConsensusToken } from '../../api/types';
import { ArrowUp, ArrowDown } from 'lucide-react';

interface ConsensusCardsProps {
  consensus: Record<string, ConsensusToken>;
}

export function ConsensusCards({ consensus }: ConsensusCardsProps) {
  const entries = Object.entries(consensus);

  if (entries.length === 0) {
    return <p className="py-8 text-center text-sm text-text-muted">No consensus data available</p>;
  }

  return (
    <div className="grid grid-cols-4 gap-4">
      {entries.map(([token, data]) => {
        const isLong = data.direction.toLowerCase() === 'long' || data.direction.toLowerCase() === 'bullish';
        const color = isLong ? '#3fb950' : '#f85149';
        const Icon = isLong ? ArrowUp : ArrowDown;

        return (
          <div key={token} className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-text-primary">{token}</span>
              <Icon className="h-4 w-4" style={{ color }} />
            </div>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-medium" style={{ color }}>
                {data.direction}
              </span>
            </div>
            <div className="mb-1">
              <div className="mb-0.5 flex items-center justify-between text-xs text-text-muted">
                <span>Confidence</span>
                <span className="font-mono">{(data.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${data.confidence * 100}%`, background: color }}
                />
              </div>
            </div>
            <div className="mt-2 text-xs text-text-muted">
              <span className="font-mono text-text-primary">{data.voter_count}</span> voters
            </div>
          </div>
        );
      })}
    </div>
  );
}
