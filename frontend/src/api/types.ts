export type Token = 'BTC' | 'ETH' | 'SOL' | 'HYPE';
export type Side = 'Long' | 'Short';
export type LabelType = 'smart_money' | 'whale' | 'public_figure' | 'all_traders';
export type Timeframe = '7d' | '30d' | '90d';

export interface TokenPerpPosition {
  rank: number;
  address: string;
  address_label: string | null;
  side: Side;
  position_value_usd: number;
  position_size: number;
  leverage: number;
  leverage_type: string;
  entry_price: number;
  mark_price: number;
  liquidation_price: number | null;
  funding_usd: number;
  upnl_usd: number;
  is_smart_money: boolean;
  smart_money_labels: string[];
}

export interface PositionMeta {
  total_long_value: number;
  total_short_value: number;
  long_short_ratio: number;
  smart_money_count: number;
  fetched_at: string;
}

export interface PositionResponse {
  token: string;
  positions: TokenPerpPosition[];
  meta: PositionMeta;
}

export interface LeaderboardTrader {
  rank: number;
  address: string;
  label: string | null;
  pnl_usd: number;
  roi_pct: number;
  win_rate: number | null;
  profit_factor: number | null;
  num_trades: number;
  score: number | null;
  allocation_weight: number | null;
  is_smart_money: boolean;
  is_blacklisted: boolean;
  anti_luck_status: { passed: boolean; failures: string[] } | null;
}

export interface MarketTokenOverview {
  symbol: string;
  long_short_ratio: number;
  total_position_value: number;
  top_trader_label: string | null;
  top_trader_side: Side;
  top_trader_size_usd: number;
  funding_rate: number;
  smart_money_net_direction: string;
  smart_money_confidence_pct: number;
}

export interface ConsensusEntry {
  direction: 'Bullish' | 'Bearish' | 'Neutral';
  confidence: number;
}

export interface SmartMoneyFlow {
  net_long_usd: number;
  net_short_usd: number;
  direction: string;
}

export interface MarketOverviewResponse {
  tokens: MarketTokenOverview[];
  consensus: Record<string, ConsensusEntry>;
  smart_money_flow: SmartMoneyFlow;
  fetched_at: string;
}

export interface LeaderboardResponse {
  timeframe: string;
  traders: LeaderboardTrader[];
  source: string;
}

export interface TraderPosition {
  token_symbol: string;
  side: Side;
  position_value_usd: number;
  entry_price: number;
  leverage_value: number;
  liquidation_price: number | null;
  unrealized_pnl_usd: number | null;
}

export interface TimeframeMetrics {
  pnl: number;
  roi: number;
  win_rate: number | null;
  trades: number;
}

export interface ScoreBreakdown {
  roi: number;
  sharpe: number;
  win_rate: number;
  consistency: number;
  smart_money: number;
  risk_mgmt: number;
  style_multiplier: number;
  recency_decay: number;
  final_score: number;
}

export interface TraderDetailResponse {
  address: string;
  label: string | null;
  is_smart_money: boolean;
  trading_style: string | null;
  last_active: string | null;
  positions: TraderPosition[];
  account_value_usd: number | null;
  metrics: Record<string, TimeframeMetrics> | null;
  score_breakdown: ScoreBreakdown | null;
  allocation_weight: number | null;
  anti_luck_status: { passed: boolean; failures: string[] } | null;
  is_blacklisted: boolean;
}

export interface TradeItem {
  timestamp: string;
  token_symbol: string;
  action: string;
  side: string | null;
  size: number;
  value_usd: number;
  price: number;
  closed_pnl: number;
  fee_usd: number;
}

export interface TradesResponse {
  trades: TradeItem[];
  total: number;
}

export interface PnlPoint {
  timestamp: string;
  cumulative_pnl: number;
}

export interface PnlCurveResponse {
  points: PnlPoint[];
}

export interface AllocationEntry {
  address: string;
  label: string | null;
  weight: number;
  roi_tier: number;
}

export interface RiskCapStatus {
  current: number;
  max: number;
}

export interface RiskCaps {
  position_count: RiskCapStatus;
  max_token_exposure: RiskCapStatus;
  directional_long: RiskCapStatus;
  directional_short: RiskCapStatus;
}

export interface AllocationsResponse {
  allocations: AllocationEntry[];
  softmax_temperature: number;
  total_allocated_traders: number;
  risk_caps: RiskCaps;
  computed_at: string | null;
}

export interface IndexPortfolioEntry {
  token: string;
  side: string;
  target_weight: number;
  target_usd: number;
}

export interface ConsensusToken {
  direction: string;
  confidence: number;
  voter_count: number;
}

export interface SizingEntry {
  address: string;
  weight: number;
  roi_tier: number;
  max_size_usd: number;
}

export interface StrategiesResponse {
  index_portfolio: IndexPortfolioEntry[];
  consensus: Record<string, ConsensusToken>;
  sizing_params: SizingEntry[];
}

// Assessment
export interface AssessmentStrategyResult {
  name: string;
  category: string;
  score: number;
  passed: boolean;
  explanation: string;
}

export interface AssessmentConfidence {
  passed: number;
  total: number;
  tier: string;
}

export interface AssessmentResponse {
  address: string;
  is_cached: boolean;
  window_days: number;
  trade_count: number;
  confidence: AssessmentConfidence;
  strategies: AssessmentStrategyResult[];
  computed_at: string;
}
