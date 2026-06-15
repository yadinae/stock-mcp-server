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
  [key: string]: any;
}
