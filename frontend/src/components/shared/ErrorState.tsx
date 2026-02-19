import { useState, useEffect } from 'react';
import { AlertTriangle, WifiOff, Clock, KeyRound } from 'lucide-react';
import { ApiError } from '../../api/client';

interface ErrorStateProps {
  message?: string;
  error?: Error | ApiError;
  onRetry?: () => void;
}

function isApiError(err: unknown): err is ApiError {
  return err instanceof Error && err.name === 'ApiError' && 'status' in err;
}

function RateLimitedError({ onRetry }: { onRetry?: () => void }) {
  const [countdown, setCountdown] = useState(30);

  useEffect(() => {
    if (countdown <= 0) {
      onRetry?.();
      return;
    }
    const id = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [countdown, onRetry]);

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <Clock className="h-6 w-6 text-yellow-500" />
      <span className="text-sm text-text-muted">
        Rate limited. Retrying in {countdown} seconds...
      </span>
    </div>
  );
}

export function ErrorState({ message, error, onRetry }: ErrorStateProps) {
  // Detect error type from ApiError status
  if (error && isApiError(error)) {
    if (error.status === 429) {
      return <RateLimitedError onRetry={onRetry} />;
    }

    if (error.status === 401 || error.status === 403) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 py-16">
          <KeyRound className="h-6 w-6 text-yellow-500" />
          <span className="text-sm text-text-muted">Backend API key not configured</span>
          <span className="text-xs text-text-muted">
            Set NANSEN_API_KEY in your environment and restart the backend
          </span>
        </div>
      );
    }
  }

  // Detect network errors (fetch failures)
  if (error && !(error instanceof ApiError) && error.message?.includes('fetch')) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16">
        <WifiOff className="h-6 w-6 text-red" />
        <span className="text-sm text-text-muted">Connection error</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="rounded-md bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/20"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  // Generic error
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <AlertTriangle className="h-6 w-6 text-red" />
      <span className="text-sm text-text-muted">{message || error?.message || 'Something went wrong'}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-md bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/20"
        >
          Try again
        </button>
      )}
    </div>
  );
}
