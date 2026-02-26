/**
 * Position Explorer Page
 *
 * Browse individual perpetual positions for a selected token, with filters
 * for side (Long/Short) and smart money only.
 *
 * Data source: Live Nansen API (cached server-side for 5 min).
 *   GET /api/v1/positions?token=X&side=Y&label_type=Z
 *   ->  backend/routers/positions.py
 *
 * How data is fetched:
 *   1. Backend calls nansen_client.fetch_token_perp_positions() for the
 *      selected token + label_type, fetching up to 100 positions.
 *   2. Response is cached by (token, label_type) key for 5 minutes.
 *   3. Server-side filtering is applied for side and min_position_usd.
 *   4. Meta stats are computed from the filtered result set: total long
 *      value, total short value, L/S ratio, smart money count.
 *
 * Auto-refresh: every 5 minutes (60s stale time).
 *
 * UI components:
 *   - Filter bar: token selector, side toggle, smart money checkbox (PositionFilters)
 *   - Meta summary strip: total long, total short, L/S ratio, SM count
 *   - Sortable position table with expandable row details (PositionTable)
 */
import { useState, useMemo } from 'react';
import type { Side } from '../api/types';
import { usePositions } from '../api/hooks';
import { PageLayout } from '../components/layout/PageLayout';
import { PositionFilters } from '../components/positions/PositionFilters';
import { PositionTable } from '../components/positions/PositionTable';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { EmptyState } from '../components/shared/EmptyState';
import { formatUsd } from '../lib/utils';
import { usePageTitle } from '../hooks/usePageTitle';

export function PositionExplorer() {
  usePageTitle('Position Explorer');
  const [token, setToken] = useState('BTC');
  const [side, setSide] = useState<Side | undefined>(undefined);
  const [smartMoneyOnly, setSmartMoneyOnly] = useState(false);

  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } = usePositions({
    token,
    side,
    label_type: smartMoneyOnly ? 'smart_money' : undefined,
  });

  const filteredPositions = useMemo(() => {
    if (!data?.positions) return [];
    return data.positions;
  }, [data?.positions]);

  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : undefined;

  return (
    <PageLayout
      title="Position Explorer"
      description="Browse individual perpetual positions for any token. Filter by direction (Long/Short) and smart money traders. See position sizes, entry prices, and leverage across the market. Auto-refreshes every 5 minutes."
      lastUpdated={lastUpdated}
      onRefresh={() => refetch()}
      isRefreshing={isFetching}
    >
      <div className="space-y-4">
        <PositionFilters
          token={token}
          side={side}
          smartMoneyOnly={smartMoneyOnly}
          onTokenChange={setToken}
          onSideChange={setSide}
          onSmartMoneyChange={setSmartMoneyOnly}
        />

        {/* Meta Summary */}
        {data?.meta && (
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card px-3 py-3 md:flex md:gap-6 md:px-4">
            <div>
              <span className="text-xs text-text-muted">Total Long</span>
              <div className="font-mono-nums text-sm text-green">
                {formatUsd(data.meta.total_long_value, true)}
              </div>
            </div>
            <div>
              <span className="text-xs text-text-muted">Total Short</span>
              <div className="font-mono-nums text-sm text-red">
                {formatUsd(data.meta.total_short_value, true)}
              </div>
            </div>
            <div>
              <span className="text-xs text-text-muted">L/S Ratio</span>
              <div className="font-mono-nums text-sm text-text-primary">
                {data.meta.long_short_ratio.toFixed(2)}
              </div>
            </div>
            <div>
              <span className="text-xs text-text-muted">Smart Money</span>
              <div className="font-mono-nums text-sm text-accent">
                {data.meta.smart_money_count}
              </div>
            </div>
          </div>
        )}

        {/* Content */}
        {isLoading ? (
          <LoadingState message="Loading positions..." />
        ) : isError ? (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load positions'}
            onRetry={() => refetch()}
          />
        ) : filteredPositions.length === 0 ? (
          <EmptyState message="No positions found for the selected filters" />
        ) : (
          <PositionTable data={filteredPositions} />
        )}
      </div>
    </PageLayout>
  );
}
