import { useNavigate } from 'react-router';
import type { LeaderboardTrader } from '../../api/types';
import { truncateAddress } from '../../lib/utils';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';

interface LeaderboardCardProps {
  data: LeaderboardTrader[];
  onSelectTrader?: (address: string) => void;
}

function MiniBar({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-sm text-text-muted">—</span>;
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-border">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      <span className="font-mono-nums text-xs text-text-primary">
        {value.toFixed(2)}
      </span>
    </div>
  );
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
            </div>
          </div>

          {/* 2x2 metrics grid */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div>
              <span className="text-[10px] text-text-muted">Score</span>
              <MiniBar value={trader.score} />
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Growth</span>
              <MiniBar value={trader.score_growth} />
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Drawdown</span>
              <MiniBar value={trader.score_drawdown} />
            </div>
            <div>
              <span className="text-[10px] text-text-muted">Weight</span>
              <div className="font-mono-nums text-sm text-text-primary">
                {trader.allocation_weight != null
                  ? `${(trader.allocation_weight * 100).toFixed(1)}%`
                  : '—'}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
