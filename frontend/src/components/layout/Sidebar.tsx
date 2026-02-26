import { useState } from 'react';
import { NavLink } from 'react-router';
import { BarChart3, Table, Trophy, PieChart, PanelLeftClose, PanelLeft, ClipboardCheck } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useHealthCheck } from '../../api/hooks';
import { NansenIcon } from '../icons/NansenIcon';

const NAV_ITEMS = [
  { to: '/market', label: 'Market Overview', icon: BarChart3, shortcut: '1' },
  { to: '/positions', label: 'Position Explorer', icon: Table, shortcut: '2' },
  { to: '/leaderboard', label: 'Leaderboard', icon: Trophy, shortcut: '3' },
  { to: '/allocations', label: 'Allocations', icon: PieChart, shortcut: '4' },
  { to: '/assess', label: 'Assess Trader', icon: ClipboardCheck, shortcut: '5' },
] as const;

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const { isSuccess, isError } = useHealthCheck();

  return (
    <aside
      className={cn(
        'hidden md:flex h-screen flex-col border-r border-border bg-card transition-[width] duration-200',
        collapsed ? 'w-[60px]' : 'w-60 max-lg:w-[60px]'
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <NansenIcon className="h-5 w-5 shrink-0 text-[#00FFA7]" />
        <span
          className={cn(
            'text-sm font-semibold text-text-primary whitespace-nowrap overflow-hidden transition-opacity duration-200',
            collapsed ? 'opacity-0 w-0' : 'max-lg:opacity-0 max-lg:w-0'
          )}
        >
          Hyper Signals
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon, shortcut }) => (
          <NavLink
            key={to}
            to={to}
            end
            title={label}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-accent/10 text-accent'
                  : 'text-text-muted hover:bg-surface hover:text-text-primary'
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span
              className={cn(
                'whitespace-nowrap overflow-hidden transition-opacity duration-200',
                collapsed ? 'opacity-0 w-0' : 'max-lg:opacity-0 max-lg:w-0'
              )}
            >
              {label}
            </span>
            <span
              className={cn(
                'ml-auto font-mono text-[10px] text-text-muted/50 transition-opacity duration-200',
                collapsed ? 'opacity-0 w-0' : 'max-lg:opacity-0 max-lg:w-0'
              )}
            >
              {shortcut}
            </span>
          </NavLink>
        ))}
      </nav>

      {/* Bottom: connection status + collapse toggle */}
      <div className="border-t border-border p-2 space-y-1">
        {/* Connection status */}
        <div
          className={cn(
            'flex items-center gap-2 rounded-md px-3 py-1.5',
          )}
          title={isSuccess ? 'Connected' : isError ? 'Disconnected' : 'Checking...'}
        >
          <span
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              isSuccess ? 'bg-green' : isError ? 'bg-red' : 'bg-text-muted'
            )}
          />
          <span
            className={cn(
              'text-xs text-text-muted whitespace-nowrap overflow-hidden transition-opacity duration-200',
              collapsed ? 'opacity-0 w-0' : 'max-lg:opacity-0 max-lg:w-0'
            )}
          >
            {isSuccess ? 'Connected' : isError ? 'Disconnected' : 'Checking...'}
          </span>
        </div>

        {/* Collapse toggle (hidden on small screens where sidebar auto-collapses) */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="hidden w-full items-center gap-2 rounded-md px-3 py-1.5 text-text-muted transition-colors hover:bg-surface hover:text-text-primary lg:flex"
        >
          {collapsed ? (
            <PanelLeft className="h-4 w-4 shrink-0" />
          ) : (
            <PanelLeftClose className="h-4 w-4 shrink-0" />
          )}
          <span
            className={cn(
              'text-xs whitespace-nowrap overflow-hidden transition-opacity duration-200',
              collapsed ? 'opacity-0 w-0' : ''
            )}
          >
            Collapse
          </span>
        </button>
      </div>
    </aside>
  );
}
