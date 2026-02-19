import type { Timeframe } from '../../api/types';
import { cn } from '../../lib/utils';

const TIMEFRAMES: Timeframe[] = ['7d', '30d', '90d'];

interface TimeframeToggleProps {
  value: string;
  onChange: (timeframe: string) => void;
}

export function TimeframeToggle({ value, onChange }: TimeframeToggleProps) {
  return (
    <div className="flex rounded-md border border-border">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          onClick={() => onChange(tf)}
          className={cn(
            'px-3 py-1.5 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md',
            value === tf
              ? 'bg-accent text-white'
              : 'text-text-muted hover:bg-surface hover:text-text-primary'
          )}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}
