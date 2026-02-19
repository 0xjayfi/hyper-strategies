import { cn } from '../../lib/utils';

const TOKEN_COLORS: Record<string, string> = {
  BTC: 'bg-orange-500',
  ETH: 'bg-blue-500',
  SOL: 'bg-purple-500',
  HYPE: 'bg-green-500',
};

interface TokenBadgeProps {
  token: string;
  className?: string;
}

export function TokenBadge({ token, className }: TokenBadgeProps) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs font-medium text-text-primary', className)}>
      <span className={cn('h-2 w-2 rounded-full', TOKEN_COLORS[token] || 'bg-text-muted')} />
      {token}
    </span>
  );
}
