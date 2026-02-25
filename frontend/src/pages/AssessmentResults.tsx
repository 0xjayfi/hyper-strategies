import { useParams, Link } from 'react-router';
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer } from 'recharts';
import { ArrowLeft, CheckCircle2, XCircle, Shield } from 'lucide-react';
import { PageLayout } from '../components/layout/PageLayout';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { useAssessment } from '../api/hooks';
import type { AssessmentStrategyResult } from '../api/types';
import { cn } from '../lib/utils';
import { useIsMobile } from '../hooks/useIsMobile';
import { ScorecardCardList } from '../components/shared/ScorecardCard';

const TIER_COLORS: Record<string, string> = {
  Elite: 'bg-green/20 text-green border-green/30',
  Strong: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  Moderate: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  Weak: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  Avoid: 'bg-red/20 text-red border-red/30',
  'Insufficient Data': 'bg-text-muted/20 text-text-muted border-text-muted/30',
};

const CATEGORY_COLORS: Record<string, string> = {
  'Core Performance': '#58a6ff',
  'Behavioral Quality': '#3fb950',
  'Risk Discipline': '#f0883e',
  'Pattern Quality': '#bc8cff',
};

function truncateAddress(addr: string): string {
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function RadarSection({ strategies }: { strategies: AssessmentStrategyResult[] }) {
  const data = strategies.map((s) => ({
    strategy: s.name.replace(' ', '\n'),
    score: s.score,
    fullMark: 100,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-4 text-sm font-medium text-text-primary">Score Radar</h2>
      <ResponsiveContainer width="100%" height={300}>
        <RadarChart data={data}>
          <PolarGrid stroke="#30363d" />
          <PolarAngleAxis dataKey="strategy" tick={{ fill: '#8b949e', fontSize: 11 }} />
          <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#8b949e', fontSize: 10 }} />
          <Radar name="Score" dataKey="score" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.2} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScorecardTable({ strategies }: { strategies: AssessmentStrategyResult[] }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium text-text-primary">Strategy Scorecard</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-text-muted">
              <th className="px-4 py-2 font-medium">Strategy</th>
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="px-4 py-2 font-medium">Score</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Explanation</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr key={s.name} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-text-primary">{s.name}</td>
                <td className="px-4 py-3">
                  <span
                    className="inline-block rounded px-2 py-0.5 text-xs font-medium"
                    style={{ color: CATEGORY_COLORS[s.category] || '#8b949e', backgroundColor: `${CATEGORY_COLORS[s.category] || '#8b949e'}20` }}
                  >
                    {s.category}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${s.score}%`,
                          backgroundColor: s.score >= 70 ? '#3fb950' : s.score >= 40 ? '#f0883e' : '#f85149',
                        }}
                      />
                    </div>
                    <span className="text-xs text-text-muted">{s.score}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  {s.passed ? (
                    <span className="inline-flex items-center gap-1 text-xs text-green">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Pass
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-red">
                      <XCircle className="h-3.5 w-3.5" /> Fail
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-text-muted">{s.explanation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AssessmentResults() {
  const { address } = useParams<{ address: string }>();
  const { data, isLoading, isError, error, refetch } = useAssessment(address || '');
  const isMobile = useIsMobile();

  if (isLoading) {
    return (
      <PageLayout title="Assessing Trader...">
        <LoadingState message="Fetching trades and computing strategies..." />
      </PageLayout>
    );
  }

  if (isError || !data) {
    return (
      <PageLayout title="Assessment Failed">
        <ErrorState
          message={error?.message || 'Failed to assess trader'}
          onRetry={() => refetch()}
        />
      </PageLayout>
    );
  }

  const tierClass = TIER_COLORS[data.confidence.tier] || TIER_COLORS.Avoid;

  return (
    <PageLayout title="Assessment Results">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-4">
          <Link
            to="/assess"
            className="flex items-center gap-1 text-sm text-text-muted transition-colors hover:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" /> Assess another
          </Link>

          <div className="flex items-center gap-3">
            <h1 className="font-mono text-base md:text-lg text-text-primary">{truncateAddress(data.address)}</h1>
            <span className={cn('rounded-md border px-2.5 py-1 text-xs font-semibold', tierClass)}>
              {data.confidence.tier}
            </span>
            <span className="flex items-center gap-1 text-sm text-text-muted">
              <Shield className="h-4 w-4" />
              {data.confidence.passed}/{data.confidence.total} passed
            </span>
          </div>

          {data.is_cached && (
            <span className="rounded bg-surface px-2 py-0.5 text-xs text-text-muted">Cached</span>
          )}

          <span className="text-xs text-text-muted">
            {data.trade_count} trades ({data.window_days}d)
          </span>

          <Link
            to={`/traders/${data.address}`}
            className="ml-auto text-xs text-accent hover:underline"
          >
            View Deep Dive
          </Link>
        </div>

        {/* Radar Chart */}
        <RadarSection strategies={data.strategies} />

        {/* Scorecard */}
        {isMobile ? (
          <ScorecardCardList strategies={data.strategies} />
        ) : (
          <ScorecardTable strategies={data.strategies} />
        )}
      </div>
    </PageLayout>
  );
}
