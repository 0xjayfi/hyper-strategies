import type { IndexPortfolioEntry } from '../../api/types';
import { TokenBadge } from '../shared/TokenBadge';
import { SideBadge } from '../shared/SideBadge';
import { formatUsd } from '../../lib/utils';
import type { Side } from '../../api/types';

interface IndexPortfolioTableProps {
  portfolio: IndexPortfolioEntry[];
}

export function IndexPortfolioTable({ portfolio }: IndexPortfolioTableProps) {
  const totalWeight = portfolio.reduce((s, e) => s + e.target_weight, 0);
  const totalUsd = portfolio.reduce((s, e) => s + e.target_usd, 0);

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border bg-card text-xs uppercase tracking-wider text-text-muted">
            <th className="px-4 py-2">Token</th>
            <th className="px-4 py-2">Side</th>
            <th className="px-4 py-2 text-right">Target Weight</th>
            <th className="px-4 py-2 text-right">Target USD</th>
          </tr>
        </thead>
        <tbody>
          {portfolio.map((entry) => (
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
  );
}
