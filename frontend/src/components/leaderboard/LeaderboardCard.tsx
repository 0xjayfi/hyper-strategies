import { useNavigate } from 'react-router';
import type { LeaderboardTrader } from '../../api/types';
import { truncateAddress, formatPct } from '../../lib/utils';
import { PnlDisplay } from '../shared/PnlDisplay';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { FilterBadges } from './FilterBadges';

interface LeaderboardCardProps {
  data: LeaderboardTrader[];
  onSelectTrader?: (address: string) => void;
}

export function LeaderboardCardList({ data, onSelectTrader }: LeaderboardCardProps) {
  const navigate = useNavigate();

  return (
    <div className="space-y-3">
      {data.map((trader) => (
        <div
          key={trader.address}
          className="cursor-pointer rounded-lg border border-border bg-card p-3 transition-colors active:bg-card/70"
          onClick={() => {
            onSelectTrader?.(trader.address);
            navigate(`/traders/${trader.address}`);
          }}
        >
          {/* Top row: rank + address + badges */}
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-medium text-text-muted">#{trader.rank}</span>
            <div className="min-w-0 flex-1">
              {trader.label && (
                <span className="block truncate text-sm font-medium text-text-primary">{trader.label}</span>
              )}
              <span className="font-mono-nums text-xs text-text-muted">
                {truncateAddress(trader.address)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {trader.is_smart_money && <SmartMoneyBadge />}
              {trader.anti_luck_status && <FilterBadges status={trader.anti_luck_status} />}
            </div>
          </div>

          {/* 2x2 metrics grid */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div>
              <span className="text-[10px] text-text-muted">PnL</span>
              <div><PnlDisplay value={trader.pnl_usd} compact /></div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">ROI</span>
              <div className={`font-mono-nums text-sm ${trader.roi_pct >= 0 ? 'text-green' : 'text-red'}`}>
                {formatPct(trader.roi_pct)}
              </div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Win Rate</span>
              <div className="font-mono-nums text-sm text-text-primary">
                {trader.win_rate != null ? `${(trader.win_rate * 100).toFixed(1)}%` : '—'}
              </div>
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Score</span>
              <div className="flex items-center gap-2">
                {trader.score != null ? (
                  <>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${Math.min(trader.score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono-nums text-xs text-text-primary">
                      {trader.score.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-text-muted">—</span>
                )}
              </div>
            </div>
          </div>

          {/* Allocation weight bar */}
          {trader.allocation_weight != null && (
            <div className="mt-2 pt-2 border-t border-border">
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-text-muted">Weight</span>
                <span className="font-mono-nums text-text-primary">
                  {(trader.allocation_weight * 100).toFixed(1)}%
                </span>
              </div>
              <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${trader.allocation_weight * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
