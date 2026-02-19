import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  message?: string;
}

export function EmptyState({ message = 'No data found' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <Inbox className="h-6 w-6 text-text-muted" />
      <span className="text-sm text-text-muted">{message}</span>
    </div>
  );
}
