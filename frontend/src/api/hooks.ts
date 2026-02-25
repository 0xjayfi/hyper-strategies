import { useQuery } from '@tanstack/react-query';
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

export function usePositions(filters: PositionFilters) {
  return useQuery({
    queryKey: ['positions', filters],
    queryFn: () => apiClient.get<PositionResponse>('/api/v1/positions', {
      token: filters.token,
      label_type: filters.label_type,
      side: filters.side,
      min_position_usd: filters.min_position_usd,
      limit: filters.limit,
    }),
    refetchInterval: REFRESH_INTERVALS.positions,
    staleTime: 60_000,
  });
}

export function useMarketOverview() {
  return useQuery({
    queryKey: ['market-overview'],
    queryFn: () => apiClient.get<MarketOverviewResponse>('/api/v1/market-overview'),
    refetchInterval: REFRESH_INTERVALS.positions,
    staleTime: 60_000,
  });
}

export function useLeaderboard(timeframe: string = '30d', token?: string, sortBy?: string) {
  return useQuery({
    queryKey: ['leaderboard', timeframe, token, sortBy],
    queryFn: () => apiClient.get<LeaderboardResponse>('/api/v1/leaderboard', {
      timeframe,
      token,
      sort_by: sortBy,
    }),
    refetchInterval: REFRESH_INTERVALS.leaderboard,
    staleTime: 5 * 60_000,
  });
}

export function useTrader(address: string) {
  return useQuery({
    queryKey: ['trader', address],
    queryFn: () => apiClient.get<TraderDetailResponse>(`/api/v1/traders/${address}`),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
}

export function useTraderTrades(address: string, days: number = 30) {
  return useQuery({
    queryKey: ['trader-trades', address, days],
    queryFn: () => apiClient.get<TradesResponse>(`/api/v1/traders/${address}/trades`, { days }),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
}

export function useTraderPnlCurve(address: string, days: number = 90) {
  return useQuery({
    queryKey: ['trader-pnl-curve', address, days],
    queryFn: () => apiClient.get<PnlCurveResponse>(`/api/v1/traders/${address}/pnl-curve`, { days }),
    staleTime: 5 * 60_000,
    enabled: !!address,
  });
}

export function useAllocations() {
  return useQuery({
    queryKey: ['allocations'],
    queryFn: () => apiClient.get<AllocationsResponse>('/api/v1/allocations'),
    refetchInterval: REFRESH_INTERVALS.allocations,
    staleTime: 5 * 60_000,
  });
}

export function useAllocationStrategies() {
  return useQuery({
    queryKey: ['allocation-strategies'],
    queryFn: () => apiClient.get<StrategiesResponse>('/api/v1/allocations/strategies'),
    refetchInterval: REFRESH_INTERVALS.allocations,
    staleTime: 5 * 60_000,
  });
}

export function useAssessment(address: string, windowDays: number = 30) {
  return useQuery({
    queryKey: ['assessment', address, windowDays],
    queryFn: () => apiClient.get<AssessmentResponse>(`/api/v1/assess/${address}`, {
      window_days: windowDays,
    }),
    staleTime: 5 * 60_000,
    enabled: !!address,
    retry: 1,
  });
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
