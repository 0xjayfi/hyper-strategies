import { useParams, useNavigate } from 'react-router';
import { ArrowLeft } from 'lucide-react';
import { useTrader, useTraderTrades, useTraderPnlCurve } from '../api/hooks';
import type { TraderPosition } from '../api/types';
import { PageLayout } from '../components/layout/PageLayout';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { TraderHeader } from '../components/trader/TraderHeader';
import { PnlCurveChart } from '../components/trader/PnlCurveChart';
import { TradeHistoryTable } from '../components/trader/TradeHistoryTable';
import { ScoreBreakdown } from '../components/trader/ScoreBreakdown';
import { AllocationHistory } from '../components/trader/AllocationHistory';
import { SideBadge } from '../components/shared/SideBadge';
import { TokenBadge } from '../components/shared/TokenBadge';
import { PnlDisplay } from '../components/shared/PnlDisplay';
import { formatUsd, formatPct, formatLeverage } from '../lib/utils';
import { usePageTitle } from '../hooks/usePageTitle';

function MetricsCards({ metrics }: { metrics: Record<string, { pnl: number; roi: number; win_rate: number | null; trades: number }> }) {
  const timeframes = ['7d', '30d', '90d'] as const;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {timeframes.map((tf) => {
        const m = metrics[tf];
        if (!m) return null;
        return (
          <div key={tf} className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 text-xs font-medium text-text-muted uppercase">{tf} Metrics</div>
            <div className="grid grid-cols-2 gap-y-2">
              <div>
                <span className="text-xs text-text-muted">PnL</span>
                <div><PnlDisplay value={m.pnl} compact /></div>
              </div>
              <div>
                <span className="text-xs text-text-muted">ROI</span>
                <div className={`font-mono-nums text-sm ${m.roi >= 0 ? 'text-green' : 'text-red'}`}>
                  {formatPct(m.roi)}
                </div>
              </div>
              <div>
                <span className="text-xs text-text-muted">Win Rate</span>
                <div className="font-mono-nums text-sm text-text-primary">
                  {m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '-'}
                </div>
              </div>
              <div>
                <span className="text-xs text-text-muted">Trades</span>
                <div className="font-mono-nums text-sm text-text-primary">{m.trades}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PositionsTable({ positions }: { positions: TraderPosition[] }) {
  if (positions.length === 0) return null;

  return (
    <div className="rounded-lg border border-border">
      <div className="px-4 py-2.5 border-b border-border bg-card">
        <h3 className="text-sm font-medium text-text-primary">Current Positions ({positions.length})</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-card">
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Token</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Side</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Size</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Entry</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Leverage</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">Liq. Price</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-text-muted">uPnL</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos, i) => (
              <tr key={i} className="border-b border-border transition-colors hover:bg-card/50">
                <td className="px-3 py-2"><TokenBadge token={pos.token_symbol} /></td>
                <td className="px-3 py-2"><SideBadge side={pos.side} /></td>
                <td className="px-3 py-2 font-mono-nums text-text-primary">{formatUsd(pos.position_value_usd, true)}</td>
                <td className="px-3 py-2 font-mono-nums text-text-primary">
                  ${pos.entry_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </td>
                <td className="px-3 py-2 font-mono-nums text-text-primary">{formatLeverage(pos.leverage_value)}</td>
                <td className="px-3 py-2 font-mono-nums text-text-muted">
                  {pos.liquidation_price != null
                    ? `$${pos.liquidation_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : '-'}
                </td>
                <td className="px-3 py-2">
                  {pos.unrealized_pnl_usd != null ? <PnlDisplay value={pos.unrealized_pnl_usd} compact /> : <span className="text-text-muted">-</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TraderDeepDive() {
  usePageTitle('Trader Details');
  const { address = '' } = useParams<{ address: string }>();
  const navigate = useNavigate();

  const { data: trader, isLoading, isError, error, refetch, isFetching } = useTrader(address);
  const { data: tradesData, isLoading: tradesLoading, isError: tradesError, error: tradesErr, refetch: refetchTrades } = useTraderTrades(address);
  const { data: pnlData, isLoading: pnlLoading, isError: pnlError, error: pnlErr, refetch: refetchPnl } = useTraderPnlCurve(address);

  return (
    <PageLayout
      title="Trader Deep Dive"
      onRefresh={() => { refetch(); refetchTrades(); refetchPnl(); }}
      isRefreshing={isFetching}
    >
      <div className="space-y-4">
        {/* Back button */}
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back
        </button>

        {/* Trader Header */}
        {isLoading ? (
          <LoadingState message="Loading trader..." />
        ) : isError ? (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load trader'}
            onRetry={() => refetch()}
          />
        ) : trader ? (
          <>
            <TraderHeader trader={trader} />

            {/* Metrics */}
            {trader.metrics && <MetricsCards metrics={trader.metrics} />}

            {/* Positions */}
            <PositionsTable positions={trader.positions} />
          </>
        ) : null}

        {/* PnL Curve */}
        {pnlLoading ? (
          <LoadingState message="Loading PnL curve..." />
        ) : pnlError ? (
          <ErrorState
            message={pnlErr instanceof Error ? pnlErr.message : 'Failed to load PnL curve'}
            onRetry={() => refetchPnl()}
          />
        ) : pnlData && pnlData.points.length > 0 ? (
          <PnlCurveChart points={pnlData.points} />
        ) : null}

        {/* Score + Allocation side by side */}
        {trader && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ScoreBreakdown breakdown={trader.score_breakdown} />
            <AllocationHistory currentWeight={trader.allocation_weight} />
          </div>
        )}

        {/* Trade History */}
        {tradesLoading ? (
          <LoadingState message="Loading trade history..." />
        ) : tradesError ? (
          <ErrorState
            message={tradesErr instanceof Error ? tradesErr.message : 'Failed to load trades'}
            onRetry={() => refetchTrades()}
          />
        ) : tradesData && tradesData.trades.length > 0 ? (
          <div>
            <h3 className="mb-2 text-sm font-medium text-text-primary">
              Trade History ({tradesData.total} total)
            </h3>
            <TradeHistoryTable data={tradesData.trades} />
          </div>
        ) : null}
      </div>
    </PageLayout>
  );
}
