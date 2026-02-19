import type { SmartMoneyFlow } from '../../api/types';
import { formatUsd } from '../../lib/utils';

interface SmartMoneyFlowSummaryProps {
  flow: SmartMoneyFlow;
}

export function SmartMoneyFlowSummary({ flow }: SmartMoneyFlowSummaryProps) {
  const total = flow.net_long_usd + flow.net_short_usd;
  const longPct = total > 0 ? (flow.net_long_usd / total) * 100 : 50;
  const shortPct = 100 - longPct;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">
        Smart Money Flow
      </h3>

      {/* Direction Label */}
      <div className="flex items-center justify-center">
        <span className="text-sm font-medium text-text-primary">
          {flow.direction}
        </span>
      </div>

      {/* Bar */}
      <div className="flex items-center gap-3">
        <span className="font-mono-nums text-xs text-green whitespace-nowrap">
          {formatUsd(flow.net_long_usd, true)}
        </span>
        <div className="flex h-3 flex-1 overflow-hidden rounded-full">
          <div className="bg-green" style={{ width: `${longPct}%` }} />
          <div className="bg-red" style={{ width: `${shortPct}%` }} />
        </div>
        <span className="font-mono-nums text-xs text-red whitespace-nowrap">
          {formatUsd(flow.net_short_usd, true)}
        </span>
      </div>

      <div className="flex justify-between text-xs text-text-muted">
        <span>Net Long</span>
        <span>Net Short</span>
      </div>
    </div>
  );
}
