/**
 * Allocation Dashboard Page
 *
 * Displays the output of the PnL-weighted allocation engine: who the system
 * is allocating capital to, how much, and the derived strategy signals.
 *
 * Data source: SQLite DB only (zero Nansen API calls). Falls back to mock
 * data if the DB is empty.
 *   GET /api/v1/allocations             ->  backend/routers/allocations.py
 *   GET /api/v1/allocations/strategies  ->  same router (called in parallel)
 *
 * How data is fetched:
 *   /allocations endpoint:
 *     1. Reads allocations table for {address: final_weight} mapping.
 *     2. Enriches with labels from traders table and roi_tier from
 *        trader_scores table.
 *     3. Sorts by weight descending, caps at MAX_TOTAL_POSITIONS (5).
 *     4. Computes risk cap utilisation (position count, max exposure,
 *        directional long/short estimates).
 *
 *   /allocations/strategies endpoint:
 *     1. Index Portfolio — build_index_portfolio() weight-averages all
 *        trader positions (from position_snapshots) by allocation weight,
 *        normalised to 50% of $100k account value.
 *     2. Consensus — weighted_consensus() per token, aggregating long vs
 *        short exposure weighted by allocation. Requires >= 3 voters.
 *     3. Sizing — per-trader max_size_usd = weight * $100k account value.
 *
 * Auto-refresh: every 1 hour (5 min stale time).
 *
 * UI components:
 *   - Allocation weights donut chart (WeightsDonut)
 *   - Risk cap gauge bars (RiskGauges)
 *   - Allocation over time stacked area chart (AllocationTimeline)
 *   - Tabbed strategy section:
 *       Tab 1: Index Portfolio table (IndexPortfolioTable)
 *       Tab 2: Consensus cards per token (ConsensusCards)
 *       Tab 3: Interactive sizing calculator (SizingCalculator)
 */
import { useState } from 'react';
import { Info } from 'lucide-react';
import { useAllocations, useAllocationStrategies } from '../api/hooks';
import { PageLayout } from '../components/layout/PageLayout';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { WeightsDonut } from '../components/allocation/WeightsDonut';
import { RiskGauges } from '../components/allocation/RiskGauges';
import { AllocationTimeline } from '../components/allocation/AllocationTimeline';
import { IndexPortfolioTable } from '../components/allocation/IndexPortfolioTable';
import { ConsensusCards } from '../components/allocation/ConsensusCards';
import { SizingCalculator } from '../components/allocation/SizingCalculator';
import { usePageTitle } from '../hooks/usePageTitle';

const TABS = ['Index Portfolio', 'Consensus', 'Sizing Calculator'] as const;

export function AllocationDashboard() {
  usePageTitle('Allocations');
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const alloc = useAllocations();
  const strat = useAllocationStrategies();

  const isLoading = alloc.isLoading || strat.isLoading;
  const isError = alloc.isError || strat.isError;
  const error = alloc.error || strat.error;
  const lastUpdated = alloc.dataUpdatedAt ? new Date(alloc.dataUpdatedAt).toISOString() : undefined;

  return (
    <PageLayout
      title="Allocation Dashboard"
      description="The output of the scoring engine: which traders receive capital allocation, how much weight each gets, and the derived portfolio signals. Includes index portfolio construction, consensus direction per token, and risk cap monitoring. Auto-refreshes hourly."
      lastUpdated={lastUpdated}
      onRefresh={() => { alloc.refetch(); strat.refetch(); }}
      isRefreshing={alloc.isFetching || strat.isFetching}
    >
      <div className="space-y-4 md:space-y-6">
        {isLoading ? (
          <LoadingState message="Loading allocation data..." />
        ) : isError ? (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load allocation data'}
            onRetry={() => { alloc.refetch(); strat.refetch(); }}
          />
        ) : !alloc.data || alloc.data.allocations.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <Info className="h-8 w-8 text-text-muted" />
            <p className="text-sm text-text-muted">
              No allocation data available. Run the allocation engine or enable mock data mode.
            </p>
          </div>
        ) : (
          <>
            {/* Top row: Donut + Risk Gauges */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
              <div className="md:col-span-3">
                <WeightsDonut allocations={alloc.data.allocations} />
              </div>
              <div className="md:col-span-2">
                <RiskGauges riskCaps={alloc.data.risk_caps} />
              </div>
            </div>

            {/* Timeline */}
            <AllocationTimeline
              allocations={alloc.data.allocations}
              computedAt={alloc.data.computed_at}
            />

            {/* Strategy Tabs */}
            <div>
              <div className="flex overflow-x-auto border-b border-border">
                {TABS.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors ${
                      activeTab === tab
                        ? 'border-b-2 border-accent text-accent'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <div className="pt-4">
                {activeTab === 'Index Portfolio' && strat.data && (
                  <IndexPortfolioTable portfolio={strat.data.index_portfolio} />
                )}
                {activeTab === 'Consensus' && strat.data && (
                  <ConsensusCards consensus={strat.data.consensus} />
                )}
                {activeTab === 'Sizing Calculator' && strat.data && (
                  <SizingCalculator sizingParams={strat.data.sizing_params} />
                )}
                {!strat.data && (
                  <p className="py-8 text-center text-sm text-text-muted">
                    Strategy data not available
                  </p>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </PageLayout>
  );
}
