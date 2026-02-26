import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LoadingState } from './components/shared/LoadingState';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';

const LandingPage = lazy(() => import('./pages/LandingPage').then(m => ({ default: m.LandingPage })));
const MarketOverview = lazy(() => import('./pages/MarketOverview').then(m => ({ default: m.MarketOverview })));
const PositionExplorer = lazy(() => import('./pages/PositionExplorer').then(m => ({ default: m.PositionExplorer })));
const TraderLeaderboard = lazy(() => import('./pages/TraderLeaderboard').then(m => ({ default: m.TraderLeaderboard })));
const TraderDeepDive = lazy(() => import('./pages/TraderDeepDive').then(m => ({ default: m.TraderDeepDive })));
const AllocationDashboard = lazy(() => import('./pages/AllocationDashboard').then(m => ({ default: m.AllocationDashboard })));
const AssessTrader = lazy(() => import('./pages/AssessTrader').then(m => ({ default: m.AssessTrader })));
const AssessmentResults = lazy(() => import('./pages/AssessmentResults').then(m => ({ default: m.AssessmentResults })));
const NotFound = lazy(() => import('./pages/NotFound').then(m => ({ default: m.NotFound })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function AppRoutes() {
  useKeyboardShortcuts();

  return (
    <ErrorBoundary>
      <Suspense fallback={<LoadingState message="Loading..." />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/market" element={<MarketOverview />} />
          <Route path="/positions" element={<PositionExplorer />} />
          <Route path="/leaderboard" element={<TraderLeaderboard />} />
          <Route path="/traders/:address" element={<TraderDeepDive />} />
          <Route path="/allocations" element={<AllocationDashboard />} />
          <Route path="/assess" element={<AssessTrader />} />
          <Route path="/assess/:address" element={<AssessmentResults />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
