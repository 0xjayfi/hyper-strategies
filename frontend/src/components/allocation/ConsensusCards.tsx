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
    <div className="space-y-4">
      <div className="rounded-lg border border-border/50 bg-surface/50 px-4 py-3 text-xs leading-relaxed text-text-muted">
        <h4 className="mb-2 font-semibold uppercase tracking-wider">Strategy #3 — Consensus Voting</h4>
        <p className="mb-2">
          Measures how much the top traders agree on a token's direction. Each trader "votes" with their position,
          and votes are weighted by both their allocation weight and position size.
        </p>
        <h5 className="mb-1 font-semibold text-text-primary">Calculation</h5>
        <ol className="mb-2 list-inside list-decimal space-y-1">
          <li>
            <span className="text-text-primary">Gather positions</span> — for a given token, find every allocated trader
            who currently holds a position in it.
          </li>
          <li>
            <span className="text-text-primary">Compute weighted exposure</span> — for each trader, multiply their
            position's USD value by their allocation weight. Sum these into a
            <span className="font-mono text-text-primary"> long_weight</span> bucket and a
            <span className="font-mono text-text-primary"> short_weight</span> bucket.
          </li>
          <li>
            <span className="text-text-primary">Determine direction</span> — whichever bucket is larger wins. If
            <span className="font-mono text-text-primary"> long_weight {'>'}= short_weight</span>, the consensus is Long;
            otherwise Short.
          </li>
          <li>
            <span className="text-text-primary">Compute confidence</span> — the winning side's exposure divided by total
            exposure: <span className="font-mono text-text-primary">confidence = max(long, short) / (long + short)</span>.
            Ranges from 50% (evenly split) to 100% (unanimous).
          </li>
          <li>
            <span className="text-text-primary">Filter by voters</span> — only tokens where
            <span className="font-mono text-text-primary"> 3+</span> traders hold a position are shown. Fewer voters
            don't constitute meaningful consensus.
          </li>
        </ol>
        <h5 className="mb-1 font-semibold text-text-primary">Card definitions</h5>
        <ul className="list-inside list-disc space-y-0.5">
          <li><span className="text-text-primary">Direction</span> — Long (green) or Short (red), the consensus view.</li>
          <li><span className="text-text-primary">Confidence</span> — how lopsided the weighted vote is. 100% = all voters agree; 50% = evenly split.</li>
          <li><span className="text-text-primary">Voters</span> — number of allocated traders who hold any position (long or short) in this token. A trader counts as 1 voter regardless of position size.</li>
        </ul>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 md:gap-4">
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
    </div>
  );
}
