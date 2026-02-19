import { TOKENS } from '../../lib/constants';
import type { Side } from '../../api/types';
import { cn } from '../../lib/utils';

const SIDE_OPTIONS: Array<{ label: string; value: Side | undefined }> = [
  { label: 'All', value: undefined },
  { label: 'Long', value: 'Long' },
  { label: 'Short', value: 'Short' },
];

interface PositionFiltersProps {
  token: string;
  side: Side | undefined;
  smartMoneyOnly: boolean;
  onTokenChange: (token: string) => void;
  onSideChange: (side: Side | undefined) => void;
  onSmartMoneyChange: (checked: boolean) => void;
}

export function PositionFilters({
  token,
  side,
  smartMoneyOnly,
  onTokenChange,
  onSideChange,
  onSmartMoneyChange,
}: PositionFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      {/* Token Selector */}
      <div className="flex rounded-md border border-border">
        {TOKENS.map((t) => (
          <button
            key={t}
            onClick={() => onTokenChange(t)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md',
              token === t
                ? 'bg-accent text-white'
                : 'text-text-muted hover:bg-surface hover:text-text-primary'
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Side Filter */}
      <div className="flex rounded-md border border-border">
        {SIDE_OPTIONS.map(({ label, value }) => (
          <button
            key={label}
            onClick={() => onSideChange(value)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md',
              side === value
                ? 'bg-accent text-white'
                : 'text-text-muted hover:bg-surface hover:text-text-primary'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Smart Money Toggle */}
      <label className="flex cursor-pointer items-center gap-2 text-xs text-text-muted">
        <input
          type="checkbox"
          checked={smartMoneyOnly}
          onChange={(e) => onSmartMoneyChange(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-border accent-accent"
        />
        Smart Money Only
      </label>
    </div>
  );
}
