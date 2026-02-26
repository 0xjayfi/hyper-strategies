import { Link } from 'react-router';
import { FileQuestion } from 'lucide-react';
import { PageLayout } from '../components/layout/PageLayout';

export function NotFound() {
  return (
    <PageLayout title="Not Found">
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <FileQuestion className="h-10 w-10 text-text-muted" />
        <h2 className="text-lg font-medium text-text-primary">Page not found</h2>
        <p className="text-sm text-text-muted">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <Link
          to="/"
          className="mt-2 rounded-md bg-accent/10 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/20"
        >
          Go to Dashboard
        </Link>
      </div>
    </PageLayout>
  );
}
