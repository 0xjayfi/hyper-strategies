/**
 * Trader Leaderboard Page
 *
 * Ranked list of traders with scores, PnL, ROI, win rate, profit factor,
 * anti-luck status, and allocation weights.  Clicking a row shows a radar
 * chart sidebar and navigates to the trader detail page.
 *
 * Data source: Dual-source (SQLite DB preferred, Nansen API fallback).
 *   GET /api/v1/leaderboard?timeframe=X&token=Y&sort_by=Z
 *   ->  backend/routers/leaderboard.py
 *
 * How data is fetched:
 *   Path 1 — DataStore (preferred, when allocation engine has run):
 *     1. Reads trader_scores table for composite scores + anti-luck status.
 *     2. Reads trade_metrics table for win_rate, profit_factor, trade count,
 *        total PnL, ROI proxy.
 *     3. Reads allocations table for current allocation weights.
 *     4. Sorts by score (default), PnL, or ROI.
 *
 *   Path 2 — Nansen fallback (when no DataStore scores exist):
 *     1. Calls nansen_client.fetch_leaderboard() or fetch_pnl_leaderboard()
 *        for the selected timeframe + optional token filter.
 *     2. Returns raw PnL/ROI rankings without scores or anti-luck data.
 *
 * Auto-refresh: every 1 hour (5 min stale time).
 *
 * UI components:
 *   - Timeframe toggle (7d/30d/90d) + token dropdown (TimeframeToggle)
 *   - Info banner when scores are unavailable
 *   - Sortable leaderboard table (LeaderboardTable)
 *   - Score radar chart sidebar on row selection (ScoreRadarChart)
 */
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

  // Build score breakdown from real API data when available (DataStore path),
  // fall back to approximations for the Nansen fallback path (score components are null).
  const scoreBreakdown = selectedTraderData?.score != null
    ? {
        roi: selectedTraderData.score_roi ?? selectedTraderData.score * 0.8,
        sharpe: selectedTraderData.score_sharpe ?? selectedTraderData.score * 0.7,
        win_rate: selectedTraderData.score_win_rate ?? selectedTraderData.score * 0.9,
        consistency: selectedTraderData.score_consistency ?? selectedTraderData.score * 0.75,
        smart_money: selectedTraderData.score_smart_money ?? 0,
        risk_mgmt: selectedTraderData.score_risk_mgmt ?? selectedTraderData.score * 0.85,
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
              <EmptyState message="No traders found for the selected filters" />
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
