/**
 * MCP Gateway — Phase 0
 * =======================
 * Minimal MCP protocol gateway on Cloudflare Workers.
 * Stock data via Tencent/Yahoo API directly (no Python dependency).
 */

import { Env, JsonRpcRequest, JsonRpcResponse, McpTool } from './types';
import { verifyAuth } from './auth';
import * as tencent from './tools/tencent';
import * as yahoo from './tools/yahoo';

// ───── Tool Registry ─────

const TOOLS: McpTool[] = [
  {
    name: 'get_realtime_quote',
    description: '获取股票实时行情（价格、涨跌幅、成交量等）\nA股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: '股票代码' },
      },
      required: ['code'],
    },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ctype = codeType(code);
      if (ctype === 'a') return tencent.getRealtimeQuote(code);
      if (ctype === 'us' || ctype === 'hk') return yahoo.getRealtimeQuote(code);
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
  {
    name: 'get_kline',
    description: '获取股票历史K线数据\nArgs: code=股票代码, days=最近多少天（默认60）',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: '股票代码' },
        days: { type: 'number', description: '最近多少天（默认60）', default: 60 },
      },
      required: ['code'],
    },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      const days = Math.min(Math.max(parseInt(params?.days) || 60, 1), 365);
      if (!code) return { error: '股票代码不能为空' };
      const ctype = codeType(code);
      if (ctype === 'a') return tencent.getKline(code, days);
      if (ctype === 'us' || ctype === 'hk') return yahoo.getKline(code, days);
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
  {
    name: 'get_stock_info',
    description: '获取股票基本信息（名称、类型等）\nArgs: code=股票代码',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: '股票代码' },
      },
      required: ['code'],
    },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ctype = codeType(code);
      if (ctype === 'a') return tencent.getStockInfo(code);
      if (ctype === 'us' || ctype === 'hk') {
        const quote = await yahoo.getRealtimeQuote(code);
        return { code, name: quote.name || code, type: ctype };
      }
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
];

// ───── MCP Method Handlers ─────

function handleToolsList(): JsonRpcResponse {
  return {
    jsonrpc: '2.0',
    result: TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
    id: null,
  };
}

async function handleToolsCall(request: JsonRpcRequest, env: Env): Promise<JsonRpcResponse> {
  const { name, arguments: args } = request.params || {};
  if (!name) {
    return { jsonrpc: '2.0', error: { code: -32602, message: 'Missing tool name' }, id: request.id };
  }

  const tool = TOOLS.find(t => t.name === name);
  if (!tool) {
    return {
      jsonrpc: '2.0',
      error: { code: -32601, message: `Unknown tool: ${name}. Available: ${TOOLS.map(t => t.name).join(', ')}` },
      id: request.id,
    };
  }

  try {
    const result = await tool.handler(args, env);
    return { jsonrpc: '2.0', result, id: request.id };
  } catch (err: any) {
    return {
      jsonrpc: '2.0',
      error: { code: -32603, message: err.message || 'Internal error' },
      id: request.id,
    };
  }
}

// ───── HTTP Route Handler ─────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const method = request.method;

    // CORS headers
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    };

    if (method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // ─── Admin: health check ───
    if (url.pathname === '/health' && method === 'GET') {
      return new Response(JSON.stringify({ ok: true, version: '0.1.0', tools: TOOLS.length }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── MCP Protocol Endpoint ───
    if (url.pathname === '/mcp' && method === 'POST') {
      // Auth
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32001, message: auth.error || 'Unauthorized' },
          id: null,
        }), { status: 401, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }

      // Parse JSON-RPC request
      let body: JsonRpcRequest;
      try {
        body = await request.json();
      } catch {
        return new Response(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32700, message: 'Parse error: invalid JSON' },
          id: null,
        }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }

      if (body.jsonrpc !== '2.0') {
        return new Response(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32600, message: 'Invalid Request: jsonrpc must be "2.0"' },
          id: body.id || null,
        }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }

      // Route
      let response: JsonRpcResponse;
      switch (body.method) {
        case 'tools/list':
          response = handleToolsList();
          break;
        case 'tools/call':
          response = await handleToolsCall(body, env);
          break;
        default:
          response = {
            jsonrpc: '2.0',
            error: { code: -32601, message: `Method not found: ${body.method}` },
            id: body.id || null,
          };
      }

      // Set response ID
      response.id = response.id ?? body.id ?? null;

      return new Response(JSON.stringify(response), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── SSE Stream Endpoint (for MCP streaming) ───
    if (url.pathname === '/stream' && method === 'GET') {
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response('Unauthorized', { status: 401 });
      }

      const { readable, writable } = new TransformStream();
      const writer = writable.getWriter();
      const encoder = new TextEncoder();

      // Send initial endpoint info
      writer.write(encoder.encode(`event: endpoint\ndata: ${JSON.stringify({ protocol: 'mcp', version: '0.1.0' })}\n\n`));

      return new Response(readable, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          ...corsHeaders,
        },
      });
    }

    // ─── 404 ───
    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', ...corsHeaders },
    });
  },
};

// ───── Helpers ─────

function codeType(code: string): 'a' | 'us' | 'hk' | 'unknown' {
  const c = code.toUpperCase();
  if (c.startsWith('HK')) return 'hk';
  if (c.startsWith('6') || c.startsWith('5') || c.startsWith('0') || c.startsWith('3')) return 'a';
  if (c.startsWith('SH') || c.startsWith('SZ')) return 'a';
  if (/^[A-Z]{1,4}$/.test(c)) return 'us';
  return 'unknown';
}
