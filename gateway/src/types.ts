// ───── MCP Protocol Types (JSON-RPC 2.0) ─────

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  method: string;
  params?: any;
  id: string | number;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  result?: any;
  error?: { code: number; message: string; data?: any };
  id: string | number | null;
}

// ───── MCP Tool Definition ─────

export interface McpTool {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, any>;
    required?: string[];
    [key: string]: any;
  };
  handler: (params: any, env: Env) => Promise<any>;
  /** Internal: price per call (USD cents), 0 = free */
  price?: number;
  /** Rate limit per minute */
  rateLimit?: number;
}

// ───── Worker Bindings ─────

export interface Env {
  GATEWAY_KV?: KVNamespace;     // Phase 1+ for API key management
  GATEWAY_DB?: D1Database;      // Phase 2+ for usage tracking
  GATEWAY_API_KEY?: string;
  GATEWAY_ADMIN_KEY?: string;
  // AI analysis LLM config
  STOCK_LLM_BASE_URL?: string;
  STOCK_LLM_API_KEY?: string;
  STOCK_LLM_MODEL?: string;
  STOCK_LLM_TIMEOUT?: string;
}

// ───── Stock Types ─────

export interface RealtimeQuote {
  code: string;
  name?: string;
  price?: number;
  change?: number;
  change_pct?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  amount?: number;
  pre_close?: number;
  turnover_rate?: number;
  pe_ratio?: number;
  market_cap?: number;
  amp?: number;
  [key: string]: any;
}

export interface KlineRecord {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount?: number;
}

// ───── Technical Analysis Types ─────

export interface TrendResult {
  status: string;
  score: number;
  ma5: number;
  ma10: number;
  ma20: number;
  ma60: number;
}

export interface MacdResult {
  dif: number;
  dea: number;
  bar: number;
  status: string;
  signal: string;
}

export interface RsiResult {
  value: number;
  status: string;
}

export interface BollingerResult {
  upper: number;
  middle: number;
  lower: number;
  bandwidth: number;
  position: string;
}

export interface IchimokuResult {
  tenkan?: number;
  kijun?: number;
  span_a?: number;
  span_b?: number;
  chiko?: number;
  trend?: string;
  status?: string;
}

export interface CandlePattern {
  date: string;
  patterns: string[];
}

export interface TechnicalResult {
  trend: TrendResult;
  macd: MacdResult;
  rsi: RsiResult;
  bollinger: BollingerResult;
  volume_ratio: number;
  bias: { ma5: number; ma20: number };
  support: { ma5: boolean; ma10: boolean };
  ichimoku: IchimokuResult;
  candle_patterns: CandlePattern[];
  price: number;
  score: number;
  advice: string;
  analysis_count: number;
  [key: string]: any;
}

// ───── ST Risk Types ─────

export interface RiskSignal {
  dimension: string;
  level: number;
  level_name: string;
  detail: string;
  suggestion: string;
}

export interface RiskReport {
  code: string;
  name: string;
  max_level: number;
  level_name: string;
  is_st: boolean;
  signals: RiskSignal[];
  signal_count: number;
  source: string;
}

// ───── News Types ─────

export interface NewsItem {
  title: string;
  url: string;
  source: string;
}

export interface NewsResult {
  stock_code: string;
  stock_name: string;
  news: NewsItem[];
  count: number;
  time: string;
}

// ───── Backtest Types ─────

export interface BacktestSignal {
  date: string;
  action: "buy" | "sell" | "hold";
  price: number;
  reason: string;
}

export interface BacktestTrade {
  buy_date: string;
  sell_date: string;
  buy_price: number;
  sell_price: number;
  shares: number;
  commission: number;
  stamp_tax: number;
  profit: number;
  profit_pct: number;
  hold_days: number;
}

export interface EquityPoint {
  date: string;
  value: number;
}

export interface BacktestMetrics {
  total_return_pct: number;
  annual_return_pct?: number;
  max_drawdown_pct: number;
  max_drawdown_start?: string;
  max_drawdown_end?: string;
  sharpe_ratio: number;
  win_rate_pct: number;
  win_count?: number;
  loss_count?: number;
  total_trades?: number;
  profit_factor: number;
  avg_hold_days?: number;
  total_days?: number;
  [key: string]: any;
}

export interface BacktestResult {
  code: string;
  strategy_id: string;
  strategy_name: string;
  strategy_params: Record<string, any>;
  period: { start: string; end: string; trading_days: number };
  capital: { initial: number; final: number };
  metrics: BacktestMetrics;
  trades: BacktestTrade[];
  trade_count: number;
  equity_curve: EquityPoint[];
  equity_curve_points: number;
  success: boolean;
  note: string;
  [key: string]: any;
}
