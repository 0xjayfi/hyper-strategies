import { Sparkles } from 'lucide-react';
import { cn } from '../../lib/utils';

interface SmartMoneyBadgeProps {
  className?: string;
}

export function SmartMoneyBadge({ className }: SmartMoneyBadgeProps) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium bg-accent/15 text-accent', className)}>
      <Sparkles className="h-3 w-3" />
      Smart Money
    </span>
  );
}
