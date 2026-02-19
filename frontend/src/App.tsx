import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LoadingState } from './components/shared/LoadingState';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';

const MarketOverview = lazy(() => import('./pages/MarketOverview').then(m => ({ default: m.MarketOverview })));
const PositionExplorer = lazy(() => import('./pages/PositionExplorer').then(m => ({ default: m.PositionExplorer })));
const TraderLeaderboard = lazy(() => import('./pages/TraderLeaderboard').then(m => ({ default: m.TraderLeaderboard })));
const TraderDeepDive = lazy(() => import('./pages/TraderDeepDive').then(m => ({ default: m.TraderDeepDive })));
const AllocationDashboard = lazy(() => import('./pages/AllocationDashboard').then(m => ({ default: m.AllocationDashboard })));

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
    <Suspense fallback={<LoadingState message="Loading..." />}>
      <Routes>
        <Route path="/" element={<MarketOverview />} />
        <Route path="/positions" element={<PositionExplorer />} />
        <Route path="/leaderboard" element={<TraderLeaderboard />} />
        <Route path="/traders/:address" element={<TraderDeepDive />} />
        <Route path="/allocations" element={<AllocationDashboard />} />
      </Routes>
    </Suspense>
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
