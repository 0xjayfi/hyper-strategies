import { Check, X } from 'lucide-react';

interface FilterBadgesProps {
  status: { passed: boolean; failures: string[] } | null;
}

export function FilterBadges({ status }: FilterBadgesProps) {
  if (status == null) {
    return <span className="text-text-muted">—</span>;
  }

  if (status.passed) {
    return (
      <span className="inline-flex items-center gap-1 text-green">
        <Check className="h-3.5 w-3.5" />
      </span>
    );
  }

  return (
    <span className="group relative inline-flex items-center gap-1 text-red cursor-help">
      <X className="h-3.5 w-3.5" />
      <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-surface border border-border px-2 py-1 text-xs text-text-primary shadow-lg group-hover:block">
        Failed: {status.failures.join(', ')}
      </span>
    </span>
  );
}
