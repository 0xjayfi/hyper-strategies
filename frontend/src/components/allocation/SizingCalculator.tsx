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
    <div className="space-y-4">
      <div className="rounded-lg border border-border/50 bg-surface/50 px-4 py-3 text-xs leading-relaxed text-text-muted">
        <h4 className="mb-2 font-semibold uppercase tracking-wider">Strategy #5 — Per-Trade Sizing</h4>
        <p className="mb-2">
          When you copy a trade from a tracked trader, this strategy determines how large your copied position should be.
          It scales proportionally based on the trader's quality (allocation weight) and recent momentum (ROI tier).
        </p>
        <h5 className="mb-1 font-semibold text-text-primary">Calculation</h5>
        <ol className="mb-2 list-inside list-decimal space-y-1">
          <li>
            <span className="text-text-primary">Proportional sizing</span> — compute what fraction of the trader's account
            the trade represents: <span className="font-mono text-text-primary">trade_value / trader_account_value</span>.
          </li>
          <li>
            <span className="text-text-primary">Apply allocation weight</span> — multiply by the trader's allocation weight
            (0-1). Higher-scored traders get proportionally larger copies.
          </li>
          <li>
            <span className="text-text-primary">Apply copy ratio</span> — multiply by
            <span className="font-mono text-text-primary"> 0.5x</span> for conservatism (copy at half scale).
          </li>
          <li>
            <span className="text-text-primary">Apply ROI tier</span> — multiply by the trader's recent 7-day ROI tier:
            <span className="font-mono text-text-primary"> 1.0x</span> if 7d ROI {'>'} 10% (hot streak),
            <span className="font-mono text-text-primary"> 0.75x</span> if 0-10% (moderate),
            <span className="font-mono text-text-primary"> 0.5x</span> if {'<'} 0% (underperforming).
          </li>
          <li>
            <span className="text-text-primary">Hard cap</span> — no single copied position can exceed
            <span className="font-mono text-text-primary"> 10%</span> of your account value.
          </li>
        </ol>
        <p className="mb-2">
          Full formula: <span className="font-mono text-text-primary">your_account x (trade_value / trader_account) x weight x 0.5 x roi_tier</span>
        </p>
        <h5 className="mb-1 font-semibold text-text-primary">Field definitions</h5>
        <ul className="list-inside list-disc space-y-0.5">
          <li><span className="text-text-primary">Weight</span> — the trader's current allocation weight from the composite scoring pipeline (softmax + risk caps).</li>
          <li><span className="text-text-primary">ROI Tier Multiplier</span> — momentum adjustment based on the trader's 7-day realized ROI.</li>
          <li><span className="text-text-primary">Max Size (API)</span> — the maximum position size this trader can generate, given the current weight and a $100k default account.</li>
          <li><span className="text-text-primary">Computed Position</span> — the estimated position size for your entered account value (weight x roi_tier x account).</li>
        </ul>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-xs font-medium uppercase tracking-wider text-text-muted">
          Position Sizing Calculator
        </h3>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6">
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
    </div>
  );
}
