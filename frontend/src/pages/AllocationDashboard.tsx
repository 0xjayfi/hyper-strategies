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
      lastUpdated={lastUpdated}
      onRefresh={() => { alloc.refetch(); strat.refetch(); }}
      isRefreshing={alloc.isFetching || strat.isFetching}
    >
      <div className="space-y-6">
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
            <div className="grid grid-cols-5 gap-4">
              <div className="col-span-3">
                <WeightsDonut allocations={alloc.data.allocations} />
              </div>
              <div className="col-span-2">
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
              <div className="flex border-b border-border">
                {TABS.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-2 text-sm font-medium transition-colors ${
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
