import { useState } from 'react';
import { useLeaderboard } from '../api/hooks';
import { TOKENS } from '../lib/constants';
import { PageLayout } from '../components/layout/PageLayout';
import { TimeframeToggle } from '../components/leaderboard/TimeframeToggle';
import { LeaderboardTable } from '../components/leaderboard/LeaderboardTable';
import { ScoreRadarChart } from '../components/leaderboard/ScoreRadarChart';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { EmptyState } from '../components/shared/EmptyState';
import { Info } from 'lucide-react';
import { usePageTitle } from '../hooks/usePageTitle';

export function TraderLeaderboard() {
  usePageTitle('Trader Leaderboard');
  const [timeframe, setTimeframe] = useState('30d');
  const [tokenFilter, setTokenFilter] = useState<string | undefined>(undefined);
  const [selectedTrader, setSelectedTrader] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } =
    useLeaderboard(timeframe, tokenFilter);

  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : undefined;

  const hasScores = data?.traders.some((t) => t.score != null) ?? false;

  const selectedTraderData = data?.traders.find((t) => t.address === selectedTrader);

  // Build a score breakdown from trader data if available
  // The radar chart expects individual score components; since the API returns a composite score,
  // we derive a placeholder breakdown. When real breakdown data is available, this can be updated.
  const scoreBreakdown = selectedTraderData?.score != null
    ? {
        roi: selectedTraderData.roi_pct > 0 ? Math.min(selectedTraderData.roi_pct / 100, 1) : 0,
        sharpe: selectedTraderData.score,
        win_rate: selectedTraderData.win_rate ?? 0,
        consistency: selectedTraderData.score,
        smart_money: selectedTraderData.is_smart_money ? 1 : 0,
        risk_mgmt: selectedTraderData.profit_factor != null
          ? Math.min(selectedTraderData.profit_factor / 5, 1)
          : 0,
      }
    : null;

  return (
    <PageLayout
      title="Trader Leaderboard"
      lastUpdated={lastUpdated}
      onRefresh={() => refetch()}
      isRefreshing={isFetching}
    >
      <div className="space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-4">
          <TimeframeToggle value={timeframe} onChange={setTimeframe} />
          <select
            value={tokenFilter ?? ''}
            onChange={(e) => setTokenFilter(e.target.value || undefined)}
            className="rounded-md border border-border bg-card px-3 py-1.5 text-xs text-text-primary outline-none focus:border-accent"
          >
            <option value="">All Tokens</option>
            {TOKENS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        {/* Info banner when scores unavailable */}
        {!hasScores && !isLoading && data && data.traders.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5">
            <Info className="h-4 w-4 text-accent shrink-0" />
            <span className="text-xs text-text-muted">
              Run the allocation engine to see trader scores and allocation weights
            </span>
          </div>
        )}

        {/* Content */}
        <div className="flex gap-4">
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <LoadingState message="Loading leaderboard..." />
            ) : isError ? (
              <ErrorState
                message={error instanceof Error ? error.message : 'Failed to load leaderboard'}
                onRetry={() => refetch()}
              />
            ) : !data || data.traders.length === 0 ? (
              <EmptyState message="No traders found for the selected filters" />
            ) : (
              <LeaderboardTable
                data={data.traders}
                onSelectTrader={setSelectedTrader}
              />
            )}
          </div>

          {/* Radar chart sidebar */}
          {scoreBreakdown && (
            <div className="hidden w-72 shrink-0 lg:block">
              <ScoreRadarChart scoreBreakdown={scoreBreakdown} />
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  );
}
