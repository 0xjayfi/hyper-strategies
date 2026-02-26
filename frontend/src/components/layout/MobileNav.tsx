import { useEffect } from 'react';
import { NavLink } from 'react-router';
import { BarChart3, Table, Trophy, PieChart, ClipboardCheck, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useHealthCheck } from '../../api/hooks';
import { NansenIcon } from '../icons/NansenIcon';

const NAV_ITEMS = [
  { to: '/market', label: 'Market Overview', icon: BarChart3 },
  { to: '/positions', label: 'Position Explorer', icon: Table },
  { to: '/leaderboard', label: 'Leaderboard', icon: Trophy },
  { to: '/allocations', label: 'Allocations', icon: PieChart },
  { to: '/assess', label: 'Assess Trader', icon: ClipboardCheck },
] as const;

interface MobileNavProps {
  open: boolean;
  onClose: () => void;
}

export function MobileNav({ open, onClose }: MobileNavProps) {
  const { isSuccess, isError } = useHealthCheck();

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-label="Navigation menu">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />

      {/* Slide-out panel */}
      <aside className="absolute left-0 top-0 flex h-full w-[280px] flex-col bg-card border-r border-border">
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <NansenIcon className="h-5 w-5 text-[#00FFA7]" />
            <span className="text-sm font-semibold text-text-primary">Hyper Signals</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded-md p-2.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent'
                    : 'text-text-muted hover:bg-surface hover:text-text-primary'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Connection status */}
        <div className="border-t border-border p-3">
          <div className="flex items-center gap-2 rounded-md px-3 py-1.5">
            <span
              className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                isSuccess ? 'bg-green' : isError ? 'bg-red' : 'bg-text-muted'
              )}
            />
            <span className="text-xs text-text-muted">
              {isSuccess ? 'Connected' : isError ? 'Disconnected' : 'Checking...'}
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
