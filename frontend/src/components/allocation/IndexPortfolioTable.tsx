import { useMemo, useState } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import type { IndexPortfolioEntry, Side } from '../../api/types';
import { TokenBadge } from '../shared/TokenBadge';
import { SideBadge } from '../shared/SideBadge';
import { formatUsd } from '../../lib/utils';

interface IndexPortfolioTableProps {
  portfolio: IndexPortfolioEntry[];
}

type SortKey = 'token' | 'side' | 'target_weight' | 'target_usd';
type SortDir = 'asc' | 'desc';

function comparePrimitive(a: string | number, b: string | number, dir: SortDir): number {
  if (a < b) return dir === 'asc' ? -1 : 1;
  if (a > b) return dir === 'asc' ? 1 : -1;
  return 0;
}

export function IndexPortfolioTable({ portfolio }: IndexPortfolioTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('target_usd');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sorted = useMemo(() => {
    return [...portfolio].sort((a, b) => comparePrimitive(a[sortKey], b[sortKey], sortDir));
  }, [portfolio, sortKey, sortDir]);

  const totalWeight = portfolio.reduce((s, e) => s + e.target_weight, 0);
  const totalUsd = portfolio.reduce((s, e) => s + e.target_usd, 0);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'token' || key === 'side' ? 'asc' : 'desc');
    }
  }

  function SortIcon({ column }: { column: SortKey }) {
    if (sortKey !== column) return <ChevronDown className="inline h-3 w-3 opacity-0 group-hover:opacity-40" />;
    return sortDir === 'asc'
      ? <ChevronUp className="inline h-3 w-3 text-accent" />
      : <ChevronDown className="inline h-3 w-3 text-accent" />;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border/50 bg-surface/50 px-4 py-3 text-xs leading-relaxed text-text-muted">
        <h4 className="mb-2 font-semibold uppercase tracking-wider">Strategy #2 — Index Portfolio Rebalancing</h4>
        <p className="mb-2">
          Builds a single target portfolio by combining the open positions of the top 5 allocated traders, weighted by
          their composite score. Think of it as an "index fund" of the best traders' current positions.
        </p>
        <h5 className="mb-1 font-semibold text-text-primary">Calculation</h5>
        <ol className="mb-2 list-inside list-decimal space-y-1">
          <li>
            <span className="text-text-primary">Collect positions</span> — fetch every open perp position from the 5 traders
            in the current allocation set.
          </li>
          <li>
            <span className="text-text-primary">Weight by allocation</span> — each position's USD value is multiplied by
            the trader's allocation weight (e.g., a $10k BTC Long from a trader with 0.25 weight contributes $2,500).
          </li>
          <li>
            <span className="text-text-primary">Aggregate by (token, side)</span> — positions are grouped by token AND
            direction. If Trader A is Long BTC and Trader B is Short BTC, both show as separate rows rather than canceling
            out, so you can see when traders disagree.
          </li>
          <li>
            <span className="text-text-primary">Top 10</span> — only the 10 largest positions by USD value are kept;
            smaller tail positions are dropped.
          </li>
          <li>
            <span className="text-text-primary">Normalize to $50k</span> — all values are proportionally scaled so that
            Target USD sums to $50,000 and Target Weight sums to 100%.
          </li>
        </ol>
        <h5 className="mb-1 font-semibold text-text-primary">Column definitions</h5>
        <ul className="list-inside list-disc space-y-0.5">
          <li><span className="text-text-primary">Token</span> — the perpetual contract symbol (BTC, ETH, etc.).</li>
          <li><span className="text-text-primary">Side</span> — Long or Short direction for this line item.</li>
          <li><span className="text-text-primary">Target Weight</span> — this position's share of the total portfolio (sums to 100%).</li>
          <li><span className="text-text-primary">Target USD</span> — the dollar amount to allocate to this position (sums to $50k).</li>
        </ul>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border bg-card text-xs uppercase tracking-wider text-text-muted">
              <th className="group cursor-pointer select-none px-4 py-2" onClick={() => handleSort('token')}>
                Token <SortIcon column="token" />
              </th>
              <th className="group cursor-pointer select-none px-4 py-2" onClick={() => handleSort('side')}>
                Side <SortIcon column="side" />
              </th>
              <th className="group cursor-pointer select-none px-4 py-2 text-right" onClick={() => handleSort('target_weight')}>
                Target Weight <SortIcon column="target_weight" />
              </th>
              <th className="group cursor-pointer select-none px-4 py-2 text-right" onClick={() => handleSort('target_usd')}>
                Target USD <SortIcon column="target_usd" />
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry) => (
              <tr key={`${entry.token}-${entry.side}`} className="border-b border-border last:border-0">
                <td className="px-4 py-2">
                  <TokenBadge token={entry.token} />
                </td>
                <td className="px-4 py-2">
                  <SideBadge side={entry.side as Side} />
                </td>
                <td className="px-4 py-2 text-right font-mono text-text-primary">
                  {(entry.target_weight * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-2 text-right font-mono text-text-primary">
                  {formatUsd(entry.target_usd)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-border bg-card">
              <td className="px-4 py-2 text-xs font-medium text-text-muted" colSpan={2}>
                Total
              </td>
              <td className="px-4 py-2 text-right font-mono text-text-primary">
                {(totalWeight * 100).toFixed(1)}%
              </td>
              <td className="px-4 py-2 text-right font-mono text-text-primary">
                {formatUsd(totalUsd)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
