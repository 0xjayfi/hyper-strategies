import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { apiClient } from './client';
import type {
  PositionResponse,
  LabelType,
  Side,
  MarketOverviewResponse,
  LeaderboardResponse,
  TraderDetailResponse,
  TradesResponse,
  PnlCurveResponse,
  AllocationsResponse,
  AllocationHistoryResponse,
  StrategiesResponse,
  AssessmentResponse,
} from './types';
import { REFRESH_INTERVALS } from '../lib/constants';

export interface PositionFilters {
  token: string;
  label_type?: LabelType;
  side?: Side;
  min_position_usd?: number;
  limit?: number;
}

/**
 * Helper: returns a `hardRefresh` function + `isHardRefreshing` flag.
 *
 * Fetches with bust_cache=true to clear the server-side cache, then
 * writes the result into the React Query cache.  Tracks loading state
 * via useState so the spinner works reliably.
 */
function useHardRefresh<T>(queryKey: readonly unknown[], fetchFn: (bustCache?: boolean) => Promise<T>) {
  const queryClient = useQueryClient();
  const [isHardRefreshing, setIsHardRefreshing] = useState(false);
  const hardRefresh = useCallback(async () => {
    setIsHardRefreshing(true);
    try {
      const freshData = await fetchFn(true);
      queryClient.setQueryData(queryKey, freshData);
    } finally {
      setIsHardRefreshing(false);
    }
  }, [queryClient, queryKey, fetchFn]);
  return { hardRefresh, isHardRefreshing };
}

export function usePositions(filters: PositionFilters) {
  const queryKey = ['positions', filters] as const;
  const fetchPositions = useCallback((bustCache?: boolean) =>
    apiClient.get<PositionResponse>('/api/v1/positions', {
      token: filters.token,
      label_type: filters.label_type,
      side: filters.side,
      min_position_usd: filters.min_position_usd,
      limit: filters.limit,
      bust_cache: bustCache || undefined,
    }), [filters]);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchPositions(),
    refetchInterval: REFRESH_INTERVALS.positions,
    staleTime: 60_000,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchPositions);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useMarketOverview() {
  const queryKey = ['market-overview'] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<MarketOverviewResponse>('/api/v1/market-overview', {
      bust_cache: bustCache || undefined,
    }), []);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    refetchInterval: REFRESH_INTERVALS.positions,
    staleTime: 60_000,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useLeaderboard() {
  const queryKey = ['leaderboard'] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<LeaderboardResponse>('/api/v1/leaderboard', {
      bust_cache: bustCache || undefined,
    }), []);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    refetchInterval: REFRESH_INTERVALS.leaderboard,
    staleTime: 5 * 60_000,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useTrader(address: string) {
  const queryKey = ['trader', address] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<TraderDetailResponse>(`/api/v1/traders/${address}`, {
      bust_cache: bustCache || undefined,
    }), [address]);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useTraderTrades(address: string, days: number = 30) {
  const queryKey = ['trader-trades', address, days] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<TradesResponse>(`/api/v1/traders/${address}/trades`, {
      days, bust_cache: bustCache || undefined,
    }), [address, days]);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useTraderPnlCurve(address: string, days: number = 90) {
  const queryKey = ['trader-pnl-curve', address, days] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<PnlCurveResponse>(`/api/v1/traders/${address}/pnl-curve`, {
      days, bust_cache: bustCache || undefined,
    }), [address, days]);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useAllocations() {
  const queryKey = ['allocations'] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<AllocationsResponse>('/api/v1/allocations', {
      bust_cache: bustCache || undefined,
    }), []);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    refetchInterval: REFRESH_INTERVALS.allocations,
    staleTime: 5 * 60_000,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useAllocationHistory(days: number = 30) {
  const queryKey = ['allocation-history', days] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => apiClient.get<AllocationHistoryResponse>('/api/v1/allocations/history', { days }),
    refetchInterval: REFRESH_INTERVALS.allocations,
    staleTime: 5 * 60_000,
  });
  return query;
}

export function useAllocationStrategies() {
  const queryKey = ['allocation-strategies'] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<StrategiesResponse>('/api/v1/allocations/strategies', {
      bust_cache: bustCache || undefined,
    }), []);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    refetchInterval: REFRESH_INTERVALS.allocations,
    staleTime: 5 * 60_000,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useAssessment(address: string, windowDays: number = 30) {
  const queryKey = ['assessment', address, windowDays] as const;
  const fetchData = useCallback((bustCache?: boolean) =>
    apiClient.get<AssessmentResponse>(`/api/v1/assess/${address}`, {
      window_days: windowDays,
      bust_cache: bustCache || undefined,
    }), [address, windowDays]);

  const query = useQuery({
    queryKey,
    queryFn: () => fetchData(),
    staleTime: 5 * 60_000,
    enabled: !!address,
    retry: 1,
  });
  const { hardRefresh, isHardRefreshing } = useHardRefresh(queryKey, fetchData);
  return { ...query, hardRefresh, isFetching: query.isFetching || isHardRefreshing };
}

export function useHealthCheck() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiClient.get<{ status: string }>('/api/v1/health'),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: false,
  });
}
