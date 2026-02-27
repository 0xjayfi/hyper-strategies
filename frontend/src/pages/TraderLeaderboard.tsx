/**
 * Trader Leaderboard Page
 *
 * Ranked list of traders with 6-component position-based scores.
 * Clicking a row shows a radar chart sidebar and navigates to trader detail.
 *
 * Data source: Dual-source (SQLite DB preferred, Nansen API fallback).
 *   GET /api/v1/leaderboard  ->  backend/routers/leaderboard.py
 *
 * Auto-refresh: every 1 hour (5 min stale time).
 */
import { useState } from 'react';
import { useLeaderboard } from '../api/hooks';
import { PageLayout } from '../components/layout/PageLayout';
import { LeaderboardTable } from '../components/leaderboard/LeaderboardTable';
import { ScoreRadarChart } from '../components/leaderboard/ScoreRadarChart';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { EmptyState } from '../components/shared/EmptyState';
import { Info, Clock } from 'lucide-react';
import { usePageTitle } from '../hooks/usePageTitle';

export function TraderLeaderboard() {
  usePageTitle('Trader Leaderboard');
  const [selectedTrader, setSelectedTrader] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } =
    useLeaderboard();

  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : undefined;

  const hasScores = data?.traders.some((t) => t.score != null) ?? false;

  const selectedTraderData = data?.traders.find((t) => t.address === selectedTrader);

  const scoreBreakdown = selectedTraderData?.score != null
    ? {
        growth: selectedTraderData.score_growth ?? 0,
        drawdown: selectedTraderData.score_drawdown ?? 0,
        leverage: selectedTraderData.score_leverage ?? 0,
        liq_distance: selectedTraderData.score_liq_distance ?? 0,
        diversity: selectedTraderData.score_diversity ?? 0,
        consistency: selectedTraderData.score_consistency ?? 0,
      }
    : null;

  return (
    <PageLayout
      title="Trader Leaderboard"
      description="Top traders ranked by a 6-component position-based score: account growth, drawdown control, leverage discipline, liquidation safety, portfolio diversity, and consistency. Traders must pass eligibility gates to receive allocation weights. Auto-refreshes hourly."
      lastUpdated={lastUpdated}
      onRefresh={() => refetch()}
      isRefreshing={isFetching}
    >
      <div className="space-y-4">
        {/* Last scored timestamp */}
        {data?.scored_at && (
          <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2">
            <Clock className="h-3.5 w-3.5 text-text-muted shrink-0" />
            <span className="text-xs text-text-muted">
              Last scored {new Date(data.scored_at).toLocaleString()}
            </span>
          </div>
        )}

        {/* Info banner when scores unavailable */}
        {!hasScores && !isLoading && data && data.traders.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5">
            <Info className="h-4 w-4 text-accent shrink-0" />
            <span className="text-xs text-text-muted">
              Scores will appear once the scoring engine completes its first cycle
            </span>
          </div>
        )}

        {/* Radar chart — above table on mobile, sidebar on desktop */}
        {scoreBreakdown && (
          <div className="lg:hidden">
            <ScoreRadarChart scoreBreakdown={scoreBreakdown} />
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
              <EmptyState message="No traders found" />
            ) : (
              <LeaderboardTable
                data={data.traders}
                onSelectTrader={setSelectedTrader}
              />
            )}
          </div>

          {/* Radar chart sidebar — desktop only */}
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
