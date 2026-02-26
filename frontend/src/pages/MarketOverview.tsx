/**
 * Market Overview Page
 *
 * Shows a high-level snapshot of 4 tokens (BTC, ETH, SOL, HYPE) with
 * smart money consensus and aggregate flow data.
 *
 * Data source: Live Nansen API only (no SQLite DB).
 *   GET /api/v1/market-overview  ->  backend/routers/market.py
 *
 * How data is fetched:
 *   1. Backend fires concurrent Nansen requests per token:
 *      - fetch_token_perp_positions (smart_money label)
 *      - fetch_token_perp_positions (all_traders label)
 *      - fetch_perp_screener (funding, OI, volume)
 *   2. Aggregates per-token stats: L/S ratio, total position value,
 *      top trader by size, funding rate, OI, 24h volume.
 *   3. Computes smart money consensus per token (direction + confidence)
 *      and aggregate smart money flow across all tokens.
 *
 * Auto-refresh: every 5 minutes (60s stale time).
 *
 * UI components:
 *   - Token cards grid (TokenCard)
 *   - Smart money consensus chips (ConsensusIndicator)
 *   - Smart money flow summary bar (SmartMoneyFlowSummary)
 */
import { useMarketOverview } from '../api/hooks';
import { PageLayout } from '../components/layout/PageLayout';
import { TokenCard } from '../components/market/TokenCard';
import { ConsensusIndicator } from '../components/market/ConsensusIndicator';
import { SmartMoneyFlowSummary } from '../components/market/SmartMoneyFlowSummary';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { EmptyState } from '../components/shared/EmptyState';
import { usePageTitle } from '../hooks/usePageTitle';

export function MarketOverview() {
  usePageTitle('Market Overview');
  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } = useMarketOverview();
  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : undefined;

  return (
    <PageLayout
      title="Market Overview"
      description="Live snapshot of smart money activity across BTC, ETH, SOL, and HYPE. See which direction the smart money is leaning, with consensus signals and aggregate flow data. Auto-refreshes every 5 minutes."
      lastUpdated={lastUpdated}
      onRefresh={() => refetch()}
      isRefreshing={isFetching}
    >
      <div className="space-y-4 md:space-y-6">
        {isLoading ? (
          <LoadingState message="Loading market data..." />
        ) : isError ? (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load market data'}
            onRetry={() => refetch()}
          />
        ) : !data || data.tokens.length === 0 ? (
          <EmptyState message="No market data available" />
        ) : (
          <>
            {/* Token Cards Grid */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:gap-4">
              {data.tokens.map((token) => (
                <TokenCard key={token.symbol} token={token} />
              ))}
            </div>

            {/* Consensus Section */}
            {data.consensus && Object.keys(data.consensus).length > 0 && (
              <div>
                <h2 className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wider">
                  Smart Money Consensus
                </h2>
                <div className="flex gap-3 overflow-x-auto">
                  {Object.entries(data.consensus).map(([symbol, entry]) => (
                    <ConsensusIndicator key={symbol} symbol={symbol} consensus={entry} />
                  ))}
                </div>
              </div>
            )}

            {/* Smart Money Flow */}
            {data.smart_money_flow && (
              <SmartMoneyFlowSummary flow={data.smart_money_flow} />
            )}
          </>
        )}
      </div>
    </PageLayout>
  );
}
