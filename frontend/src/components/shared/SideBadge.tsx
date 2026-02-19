import { cn } from '../../lib/utils';
import type { Side } from '../../api/types';

interface SideBadgeProps {
  side: Side;
  className?: string;
}

export function SideBadge({ side, className }: SideBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium',
        side === 'Long' ? 'bg-green/15 text-green' : 'bg-red/15 text-red',
        className
      )}
    >
      {side}
    </span>
  );
}
