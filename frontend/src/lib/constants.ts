export const TOKENS = ['BTC', 'ETH', 'SOL', 'HYPE'] as const;
export type Token = typeof TOKENS[number];

export const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const REFRESH_INTERVALS = {
  positions: 5 * 60 * 1000,  // 5 min
  leaderboard: 60 * 60 * 1000,  // 1 hour
  allocations: 60 * 60 * 1000,  // 1 hour
} as const;

export const COLORS = {
  surface: '#0d1117',
  card: '#161b22',
  textPrimary: '#e6edf3',
  textMuted: '#8b949e',
  border: '#30363d',
  green: '#3fb950',
  red: '#f85149',
  accent: '#58a6ff',
} as const;
