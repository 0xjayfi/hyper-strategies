import type { MarketTokenOverview } from '../../api/types';
import { TokenBadge } from '../shared/TokenBadge';
import { SideBadge } from '../shared/SideBadge';
import { formatUsd } from '../../lib/utils';

interface TokenCardProps {
  token: MarketTokenOverview;
}

export function TokenCard({ token }: TokenCardProps) {
  const longPct = token.long_short_ratio / (1 + token.long_short_ratio) * 100;
  const shortPct = 100 - longPct;
  const fundingPositive = token.funding_rate >= 0;

  return (
    <div className="rounded-lg border border-border bg-card p-3 md:p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <TokenBadge token={token.symbol} className="text-sm" />
        <span
          className={`rounded px-1.5 py-0.5 text-xs font-medium font-mono-nums ${
            fundingPositive ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
          }`}
        >
          Funding {fundingPositive ? '+' : ''}{(token.funding_rate * 100).toFixed(4)}%
        </span>
      </div>

      {/* Long/Short Ratio Bar */}
      <div>
        <div className="flex justify-between text-xs text-text-muted mb-1">
          <span>Long {longPct.toFixed(1)}%</span>
          <span>Short {shortPct.toFixed(1)}%</span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full">
          <div className="bg-green" style={{ width: `${longPct}%` }} />
          <div className="bg-red" style={{ width: `${shortPct}%` }} />
        </div>
      </div>

      {/* Total Position Value */}
      <div>
        <span className="text-xs text-text-muted">Total Position Value</span>
        <div className="font-mono-nums text-sm text-text-primary">
          {formatUsd(token.total_position_value, true)}
        </div>
      </div>

      {/* Top Trader */}
      <div>
        <span className="text-xs text-text-muted">Top Trader</span>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-text-primary truncate">
            {token.top_trader_label || 'Unknown'}
          </span>
          <SideBadge side={token.top_trader_side} />
          <span className="font-mono-nums text-xs text-text-muted">
            {formatUsd(token.top_trader_size_usd, true)}
          </span>
        </div>
      </div>
    </div>
  );
}
