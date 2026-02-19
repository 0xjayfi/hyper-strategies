import { useState } from 'react';
import type { SizingEntry } from '../../api/types';
import { truncateAddress, formatUsd } from '../../lib/utils';

interface SizingCalculatorProps {
  sizingParams: SizingEntry[];
}

export function SizingCalculator({ sizingParams }: SizingCalculatorProps) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [accountValue, setAccountValue] = useState(100000);

  if (sizingParams.length === 0) {
    return <p className="py-8 text-center text-sm text-text-muted">No sizing data available</p>;
  }

  const selected = sizingParams[selectedIdx];
  const positionSize = accountValue * selected.weight * selected.roi_tier;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-xs font-medium uppercase tracking-wider text-text-muted">
        Position Sizing Calculator
      </h3>
      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs text-text-muted">Trader</label>
            <select
              value={selectedIdx}
              onChange={(e) => setSelectedIdx(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              {sizingParams.map((s, i) => (
                <option key={s.address} value={i}>
                  {truncateAddress(s.address)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">Account Value (USD)</label>
            <input
              type="number"
              value={accountValue}
              onChange={(e) => setAccountValue(Number(e.target.value) || 0)}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm text-text-primary focus:border-accent focus:outline-none"
            />
          </div>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-md bg-surface px-3 py-2">
            <span className="text-xs text-text-muted">Weight</span>
            <span className="font-mono text-sm text-text-primary">
              {(selected.weight * 100).toFixed(2)}%
            </span>
          </div>
          <div className="flex items-center justify-between rounded-md bg-surface px-3 py-2">
            <span className="text-xs text-text-muted">ROI Tier Multiplier</span>
            <span className="font-mono text-sm text-text-primary">
              {selected.roi_tier.toFixed(2)}x
            </span>
          </div>
          <div className="flex items-center justify-between rounded-md bg-surface px-3 py-2">
            <span className="text-xs text-text-muted">Max Size (API)</span>
            <span className="font-mono text-sm text-text-primary">
              {formatUsd(selected.max_size_usd)}
            </span>
          </div>
          <div className="flex items-center justify-between rounded-md border border-accent/30 bg-accent/5 px-3 py-2">
            <span className="text-xs font-medium text-accent">Computed Position</span>
            <span className="font-mono text-sm font-semibold text-accent">
              {formatUsd(positionSize)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
