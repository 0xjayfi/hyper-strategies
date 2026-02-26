import { useState, useEffect } from 'react';
import { RefreshCw, Menu } from 'lucide-react';

interface HeaderProps {
  title: string;
  lastUpdated?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  onMenuToggle?: () => void;
}

function timeAgo(isoString: string): string {
  const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes === 1) return '1 minute ago';
  return `${minutes} minutes ago`;
}

export function Header({ title, lastUpdated, onRefresh, isRefreshing, onMenuToggle }: HeaderProps) {
  const [, setTick] = useState(0);

  // Re-render every 30s to keep "X minutes ago" fresh
  useEffect(() => {
    if (!lastUpdated) return;
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  return (
    <div className="relative">
      {/* Pulsing green progress bar during background refetches */}
      {isRefreshing && (
        <div className="absolute inset-x-0 top-0 h-[2px] overflow-hidden bg-[#00FFA7]/20">
          <div className="h-full w-full animate-pulse bg-[#00FFA7]" />
        </div>
      )}

      <header className="flex h-14 items-center justify-between border-b border-border px-4 md:px-6">
        <div className="flex items-center gap-3">
          {onMenuToggle && (
            <button
              onClick={onMenuToggle}
              aria-label="Open navigation menu"
              className="rounded-md p-2.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary md:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
          )}
          <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
        </div>
        <div className="flex items-center gap-3">
          {isRefreshing && (
            <span className="text-xs text-[#00FFA7] animate-pulse">
              Syncing data...
            </span>
          )}
          {lastUpdated && (
            <span className="text-xs text-text-muted">
              Updated {timeAgo(lastUpdated)}
            </span>
          )}
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
          )}
        </div>
      </header>
    </div>
  );
}
