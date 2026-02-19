import { cn } from '../../lib/utils';
import { formatUsd } from '../../lib/utils';

interface PnlDisplayProps {
  value: number;
  compact?: boolean;
  className?: string;
}

export function PnlDisplay({ value, compact = false, className }: PnlDisplayProps) {
  const formatted = formatUsd(Math.abs(value), compact);
  const prefix = value >= 0 ? '+' : '-';

  return (
    <span
      className={cn(
        'font-mono-nums',
        value >= 0 ? 'text-green' : 'text-red',
        className
      )}
    >
      {prefix}{formatted}
    </span>
  );
}
