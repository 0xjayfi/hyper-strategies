import type { TradeItem } from '../../api/types';
import { TokenBadge } from '../shared/TokenBadge';
import { PnlDisplay } from '../shared/PnlDisplay';
import { formatUsd } from '../../lib/utils';

interface TradeHistoryCardListProps {
  data: TradeItem[];
}

export function TradeHistoryCardList({ data }: TradeHistoryCardListProps) {
  return (
    <div className="space-y-2">
      {data.map((trade, i) => (
        <div key={i} className="rounded-lg border border-border bg-card p-3">
          {/* Top row: token + side + timestamp */}
          <div className="mb-2 flex items-center gap-2">
            <TokenBadge token={trade.token_symbol} />
            {trade.side && (
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${
                  trade.side === 'Long' ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
                }`}
              >
                {trade.side}
              </span>
            )}
            <span className="ml-auto font-mono-nums text-[10px] text-text-muted">
              {new Date(trade.timestamp).toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>

          {/* Middle row: action + size + price */}
          <div className="mb-2 flex items-center gap-4 text-xs">
            <span className="font-medium text-text-primary">{trade.action}</span>
            <span className="font-mono-nums text-text-muted">
              {formatUsd(trade.value_usd, true)}
            </span>
            <span className="font-mono-nums text-text-muted">
              @ ${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          {/* Bottom row: PnL + fee */}
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] text-text-muted">Closed PnL</span>
              <div><PnlDisplay value={trade.closed_pnl} compact /></div>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-text-muted">Fee</span>
              <div className="font-mono-nums text-xs text-text-muted">{formatUsd(trade.fee_usd)}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
