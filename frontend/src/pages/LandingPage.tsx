import { Link } from 'react-router';
import { BarChart3, Trophy, PieChart, ClipboardCheck } from 'lucide-react';
import { NansenIcon } from '../components/icons/NansenIcon';
import { usePageTitle } from '../hooks/usePageTitle';

const FEATURES = [
  {
    to: '/market',
    icon: BarChart3,
    title: 'Market Overview',
    description: 'Live smart money flows across BTC, ETH, SOL, HYPE',
  },
  {
    to: '/leaderboard',
    icon: Trophy,
    title: 'Leaderboard',
    description: 'Top 100 traders ranked by position-based scoring',
  },
  {
    to: '/allocations',
    icon: PieChart,
    title: 'Allocations',
    description: 'Dynamic capital allocation with risk management',
  },
  {
    to: '/assess',
    icon: ClipboardCheck,
    title: 'Assess Trader',
    description: 'Deep-dive analysis of any Hyperliquid address',
  },
] as const;

export function LandingPage() {
  usePageTitle('Hyper Signals');

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface px-4 py-12 md:py-20">
      {/* Hero section */}
      <div className="flex flex-col items-center text-center">
        <NansenIcon className="h-16 w-16 text-[#00FFA7] animate-pulse md:h-20 md:w-20" />
        <h1 className="mt-6 text-3xl font-bold tracking-tight text-text-primary md:text-5xl">
          Hyper Signals
        </h1>
        <p className="mt-3 max-w-md text-sm text-text-muted md:text-base">
          Position-based smart money intelligence powered by Nansen
        </p>
        <p className="mt-2 text-xs font-medium tracking-wide text-[#00FFA7]/70 uppercase md:text-sm">
          Surface the signal. Miss nothing.
        </p>
      </div>

      {/* Feature cards */}
      <div className="mt-10 grid w-full max-w-3xl grid-cols-1 gap-3 md:mt-14 md:grid-cols-2 md:gap-4">
        {FEATURES.map(({ to, icon: Icon, title, description }) => (
          <Link
            key={to}
            to={to}
            className="group flex items-start gap-4 rounded-xl border border-border bg-card p-4 transition-all hover:border-[#00FFA7]/40 hover:bg-card/80 md:p-5"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#00FFA7]/10 text-[#00FFA7] transition-colors group-hover:bg-[#00FFA7]/20">
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-text-primary md:text-base">
                {title}
              </h3>
              <p className="mt-1 text-xs text-text-muted leading-relaxed md:text-sm">
                {description}
              </p>
            </div>
          </Link>
        ))}
      </div>

      {/* Footer */}
      <div className="mt-12 flex items-center gap-2 text-xs text-text-muted md:mt-16">
        <NansenIcon className="h-3.5 w-3.5 text-[#00FFA7]" />
        <span>Powered by Nansen</span>
      </div>
    </div>
  );
}
