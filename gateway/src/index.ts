/**
 * MCP Gateway — Full 12-tool implementation on Cloudflare Workers
 * ==============================================================
 *
 * Migrated from stock-mcp-server (Python) to TypeScript.
 * All tools run inline via fetch() — zero Python dependencies.
 */

import { Env, JsonRpcRequest, JsonRpcResponse, McpTool } from './types';
import { verifyAuth } from './auth';
import * as tencent from './tools/tencent';
import * as yahoo from './tools/yahoo';
import { analyze as analyzeTechnical } from './tools/technical';
import { getStRisk } from './tools/st_risk';
import { searchNews } from './tools/news';
import { analyzeStock } from './tools/analyzer';
import { analyzeTrapRisk } from './tools/trap';
import { analyzeLhb } from './tools/lhb';
import { fetchFinancials } from './tools/financials';
import { computeDcf } from './tools/dcf';
import { buildIcMemo } from './tools/icmemo';
import { buildUnitEconomics } from './tools/unit_econ';
import { buildValuePlan } from './tools/value_plan';
import { buildDdChecklist } from './tools/dd_checklist';
import { runBacktest, listStrategies } from './tools/backtest/index';
import { initCache, getCacheStats, makeCacheKey, TTL_ST_RISK } from './cache';
import { getHealthTracker } from './health';
import { checkRateLimit, getUsageStats } from './rate_limit';
import { queryAuditLogs } from './audit_log';
import { recordUsage, getUsageHistory, getBillingReport, getMonthlyUsage, TOOL_PRICES, pad2 } from './usage';

// ───── Tool Registry ─────

const TOOLS: McpTool[] = [
  // ═══ Data Tools ═══
  {
    name: 'get_realtime_quote',
    description: '获取股票实时行情（价格、涨跌幅、成交量等）\nA股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct === 'a') return tencent.getRealtimeQuote(code);
      if (ct === 'us' || ct === 'hk') return yahoo.getRealtimeQuote(code);
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
  {
    name: 'get_kline',
    description: '获取股票历史K线数据\nArgs: code=股票代码, days=最近多少天（默认60, 最大365）',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' }, days: { type: 'number', description: '最近多少天（默认60）', default: 60 } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      const days = Math.min(Math.max(parseInt(params?.days) || 60, 1), 365);
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct === 'a') return tencent.getKline(code, days);
      if (ct === 'us' || ct === 'hk') return yahoo.getKline(code, days);
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
  {
    name: 'get_stock_info',
    description: '获取股票基本信息（名称、类型等）\nArgs: code=股票代码',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct === 'a') return tencent.getStockInfo(code);
      if (ct === 'us' || ct === 'hk') {
        const quote = await yahoo.getRealtimeQuote(code);
        return { code, name: quote.name || code, type: ct };
      }
      return { error: `无法识别股票代码: ${code}` };
    },
    price: 0,
  },
  {
    name: 'get_stock_context',
    description: '获取股票综合数据（一次调用返回实时行情 + K线数据）\nArgs: code=股票代码',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      let quote, kline;
      if (ct === 'a') {
        [quote, kline] = await Promise.all([tencent.getRealtimeQuote(code), tencent.getKline(code)]);
      } else if (ct === 'us' || ct === 'hk') {
        [quote, kline] = await Promise.all([yahoo.getRealtimeQuote(code), yahoo.getKline(code)]);
      } else {
        return { error: `无法识别股票代码: ${code}` };
      }
      return { code, name: quote.name || code, realtime: quote, kline };
    },
    price: 0,
  },

  // ═══ Analysis Tools ═══
  {
    name: 'get_technical_analysis',
    description: '获取股票技术分析（MA/MACD/RSI/布林带/趋势判断/量价分析/Ichimoku/K线形态）\nArgs: code=股票代码',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      let records: any[];
      if (ct === 'a') {
        const kline = await tencent.getKline(code, 90);
        records = kline.records || [];
      } else if (ct === 'us' || ct === 'hk') {
        const kline = await yahoo.getKline(code, 90);
        records = kline.records || [];
      } else {
        return { error: `无法识别股票代码: ${code}` };
      }
      return await analyzeTechnical(records, code);
    },
    price: 0,
  },
  {
    name: 'check_st_risk',
    description: '检测股票的 ST/退市/异常风险\nArgs: code=股票代码\n检测维度: ST状态, 面值退市风险, 量能异常',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      let quote: any;
      if (ct === 'a') quote = await tencent.getRealtimeQuote(code);
      else if (ct === 'us' || ct === 'hk') quote = await yahoo.getRealtimeQuote(code);
      else return { error: `无法识别股票代码: ${code}` };
      return getStRisk(code, quote);
    },
    price: 0,
  },
  {
    name: 'search_stock_news',
    description: '搜索股票相关新闻（新浪财经+百度，免费无需API key）\nArgs: code=股票代码, name=股票名称（可选提高准确度）',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' }, name: { type: 'string', description: '股票名称（可选）' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      const name = (params?.name || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      return searchNews(code, name);
    },
    price: 0,
  },
  {
    name: 'analyze_stock_ai',
    description: 'AI 智能分析股票，生成决策仪表盘（含评分、买卖建议、技术面、消息面）\nArgs: code=股票代码, name=股票名称（可选）\n并行获取实时行情+K线+新闻+技术分析数据，然后调用LLM分析。',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' }, name: { type: 'string', description: '股票名称（可选）' } }, required: ['code'] },
    handler: async (params, env) => {
      const code = (params?.code || '').toString().trim();
      const name = (params?.name || '').toString().trim();
      if (!code) return { code: '', success: false, error: '股票代码不能为空' };

      const ct = codeType(code);
      if (ct === 'unknown') return { code, success: false, error: `无法识别股票代码: ${code}` };

      // Parallel fetch all data
      let quoteP: Promise<any>, klineP: Promise<any>;
      if (ct === 'a') {
        quoteP = tencent.getRealtimeQuote(code);
        klineP = tencent.getKline(code, 90);
      } else {
        quoteP = yahoo.getRealtimeQuote(code);
        klineP = yahoo.getKline(code, 90);
      }

      const [quote, kline] = await Promise.all([quoteP, klineP]);
      const stockName = name || quote.name || code;
      const records = kline.records || [];
      const technical = records.length > 0 ? await analyzeTechnical(records, code) : { error: '无K线数据' };
      const news = await searchNews(code, stockName);

      return analyzeStock(code, stockName, quote, kline, technical, news, env);
    },
    price: 0,
  },
  {
    name: 'analyze_stocks',
    description: '批量分析多只股票的行情摘要\nArgs: stock_list=逗号分隔的股票代码，如 "600519,000001,AAPL,HK00700"',
    inputSchema: { type: 'object', properties: { stock_list: { type: 'string', description: '逗号分隔的股票代码' } }, required: ['stock_list'] },
    handler: async (params) => {
      const list = (params?.stock_list || '').toString().trim();
      if (!list) return { error: '股票代码列表不能为空' };
      const codes = list.split(/[,，\s]+/).filter(Boolean);
      if (codes.length > 20) return { error: '一次最多分析20只股票' };

      const results = await Promise.all(codes.map(async (code: string) => {
        const ct = codeType(code);
        try {
          if (ct === 'a') {
            const q = await tencent.getRealtimeQuote(code);
            return { code, name: q.name, price: q.price, change_pct: q.change_pct, volume: q.volume };
          }
          if (ct === 'us' || ct === 'hk') {
            const q = await yahoo.getRealtimeQuote(code);
            return { code, name: q.name, price: q.price, change_pct: q.change_pct, volume: q.volume };
          }
          return { code, error: '无法识别股票代码' };
        } catch (e: any) {
          return { code, error: e.message };
        }
      }));

      return { stocks: results, count: results.length };
    },
    price: 0,
  },

  // ═══ Backtest Tool ═══
  {
    name: 'check_backtest',
    description: '策略回测 — 基于历史K线模拟交易，评估策略表现\nArgs: code=股票代码, strategy=策略ID, days=回测天数(最大730), capital=初始资金(默认100000)\n策略: ma_crossover=MA金叉/死叉, macd=MACD, rsi=RSI均值回归, bollinger=布林带反弹, combined=组合信号\n注意：回测仅作研究参考，不代表未来收益',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: '股票代码' },
        strategy: { type: 'string', description: '策略ID', default: 'ma_crossover' },
        days: { type: 'number', description: '回测天数（默认365，最大730）', default: 365 },
        capital: { type: 'number', description: '初始资金（默认100,000）', default: 100000 },
      },
      required: ['code'],
    },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const days = Math.min(Math.max(parseInt(params?.days) || 365, 30), 730);
      const strategy = (params?.strategy || 'ma_crossover').toString().trim();
      const capital = parseFloat(params?.capital) || 100000;

      const ct = codeType(code);
      let records: any[];
      if (ct === 'a') {
        const kline = await tencent.getKline(code, days);
        records = (kline.records || []).reverse(); // Tencent returns newest-first
      } else if (ct === 'us' || ct === 'hk') {
        const kline = await yahoo.getKline(code, days);
        records = kline.records || [];
      } else {
        return { error: `无法识别股票代码: ${code}` };
      }

      return runBacktest(code, records, strategy, days, capital);
    },
    price: 0,
  },

  {
    name: 'check_trap_risk',
    description: '杀猪盘检测 — 从K线 + 新闻检测推广/拉盘/出货等杀猪盘特征信号\nArgs: code=股票代码, name=股票名称（可选提高准确度）\n自动获取K线数据并搜索新闻中的推广关键词，输出风险评级',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' }, name: { type: 'string', description: '股票名称（可选）' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      const name = (params?.name || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };

      // Fetch kline data for analysis
      const ct = codeType(code);
      let records: any[];
      if (ct === 'a') {
        const kline = await tencent.getKline(code, 60);
        records = kline.records || [];
      } else if (ct === 'us' || ct === 'hk') {
        const kline = await yahoo.getKline(code, 60);
        records = kline.records || [];
      } else {
        return { error: `无法识别股票代码: ${code}` };
      }

      // Get realtime quote for price/volume
      let quote: any;
      if (ct === 'a') quote = await tencent.getRealtimeQuote(code);
      else quote = await yahoo.getRealtimeQuote(code);

      return analyzeTrapRisk({
        code,
        name: name || quote.name || code,
        price: quote.price,
        volume: quote.volume,
        marketCap: quote.market_cap_raw || quote.circulating_cap_raw,
        klineRecords: records,
      });
    },
    price: 0,
  },
  {
    name: 'analyze_lhb',
    description: '龙虎榜分析 — 个股近30日龙虎榜数据、游资席位识别、机构vs游资博弈\nArgs: code=股票代码（仅A股）\n通过东方财富数据接口获取，自动匹配22位知名游资席位',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码（仅A股）' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct !== 'a') return { error: '龙虎榜数据仅支持A股' };
      return analyzeLhb(code);
    },
    price: 0,
  },
  {
    name: 'fetch_financials',
    description: '获取股票财务报表核心数据 — 营收、利润、EPS、FCF、负债、流通股本等\nArgs: code=股票代码\n数据源：东方财富 F10 主要财务指标，自动覆盖近5期',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const fin = await fetchFinancials(code);
      return fin;
    },
    price: 0,
  },
  {
    name: 'dcf_valuation',
    description: 'DCF 估值模型 — 两阶段自由现金流折现 + 5×5 敏感性表\nArgs: code=股票代码\n基于最新财报 FCF 和营收增长率，自动计算内含价值和安全边际\nA股默认参数：无风险利率2.5%，股权风险溢价6%，永续增长2.5%',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };

      const [fin, quote] = await Promise.all([
        fetchFinancials(code),
        tencent.getRealtimeQuote(code).catch(() => ({ price: 0 })),
      ]);

      const currentPrice = (quote as any)?.price || 0;
      return computeDcf({ fin, currentPrice });
    },
    price: 0,
  },

  // ═══ UZI-Skill Port: IC Memo ═══
  {
    name: 'ic_memo',
    description: '投委会备忘录 — 质量评分 × DCF估值 → P0-P4 级别买入/观望/回避建议\\nArgs: code=股票代码\\n基于财务数据和DCF估值，从质量(ROE/FCF/净利率/负债率)和估值(安全边际)两个维度评分，产出正式投资建议',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct !== 'a') return { error: 'IC Memo 目前仅支持A股' };

      const [fin, quote] = await Promise.all([
        fetchFinancials(code),
        tencent.getRealtimeQuote(code).catch(() => ({ price: 0, name: code })),
      ]);

      let dcf = null;
      try {
        const currentPrice = (quote as any)?.price || 0;
        dcf = await computeDcf({ fin, currentPrice });
      } catch { /* DCF may fail for banks/insurers */ }

      return buildIcMemo(code, (quote as any)?.name || code, fin, dcf, quote as any);
    },
    price: 0,
  },

  // ═══ UZI-Skill Port: Unit Economics ═══
  {
    name: 'unit_economics',
    description: '单元经济分析 — SaaS: ARPU/LTV/CAC/回本周期 | 非SaaS: 毛利瀑布分解\\nArgs: code=股票代码\\n基于财务数据分析业务模型健康度',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct !== 'a') return { error: 'Unit Economics 目前仅支持A股' };

      const [fin, quote] = await Promise.all([
        fetchFinancials(code),
        tencent.getRealtimeQuote(code).catch(() => ({ price: 0, name: code })),
      ]);

      return buildUnitEconomics(code, (quote as any)?.name || code, fin);
    },
    price: 0,
  },

  // ═══ UZI-Skill Port: Value Creation Plan ═══
  {
    name: 'value_creation_plan',
    description: '价值创造计划 — 5年EBITDA Bridge: 营收增长/交叉销售/定价优化/供应链/营运资本\\nArgs: code=股票代码',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };
      const ct = codeType(code);
      if (ct !== 'a') return { error: '该功能目前仅支持A股' };

      const [fin, quote] = await Promise.all([
        fetchFinancials(code),
        tencent.getRealtimeQuote(code).catch(() => ({ price: 0, name: code })),
      ]);

      return buildValuePlan(code, (quote as any)?.name || code, fin);
    },
    price: 0,
  },

  // ═══ UZI-Skill Port: DD Checklist ═══
  {
    name: 'dd_checklist',
    description: '尽调清单 — 5大工作流（财务/商业/法律/运营/市场）自动尽调\\nArgs: code=股票代码\\n基于现有数据自动标注完成状态，输出完整尽调清单和完成度',
    inputSchema: { type: 'object', properties: { code: { type: 'string', description: '股票代码' } }, required: ['code'] },
    handler: async (params) => {
      const code = (params?.code || '').toString().trim();
      if (!code) return { error: '股票代码不能为空' };

      let fin = null, dcf = null, trap = null, risk = null;
      let stockName = code;
      try {
        const q = await tencent.getRealtimeQuote(code);
        stockName = (q as any)?.name || code;
        fin = await fetchFinancials(code);

        if (fin && fin.code !== '' && (q as any)?.price > 0) {
          dcf = await computeDcf({ fin, currentPrice: (q as any).price });
        }
        trap = await analyzeTrapRisk({
          code, name: stockName,
          price: (q as any)?.price, volume: (q as any)?.volume,
          marketCap: (q as any)?.market_cap_raw,
          klineRecords: [],
        });
        risk = await getStRisk(code, q as any);
      } catch { /* best-effort */ }

      return buildDdChecklist(code, stockName, fin, dcf, trap, risk);
    },
    price: 0,
  },

  // ═══ System Tools ═══
  {
    name: 'get_cache_stats',
    description: '获取缓存统计（命中率、条目数、各TTL分布）',
    inputSchema: { type: 'object', properties: {} },
    handler: async () => {
      return getCacheStats();
    },
    price: 0,
  },
  {
    name: 'get_data_source_health',
    description: '获取数据源健康状态（腾讯、Yahoo 的可用性和成功率）',
    inputSchema: { type: 'object', properties: {} },
    handler: async () => {
      return { sources: getHealthTracker().getReport() };
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

// ───── List all strategies as a utility prompt ─────

const STRATEGY_LIST = listStrategies().map(s => `${s.id}: ${s.name}(${JSON.stringify(s.params)})`).join('\n');

// ───── HTTP Route Handler ─────

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Init cache with KV binding (if available)
    initCache(env);

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
      return new Response(JSON.stringify({
        ok: true,
        version: '1.0.0',
        tools: TOOLS.length,
        tool_names: TOOLS.map(t => t.name),
        cache: getCacheStats(),
        strategies: STRATEGY_LIST,
      }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── Admin: strategies list ───
    if (url.pathname === '/strategies' && method === 'GET') {
      return new Response(JSON.stringify({ strategies: listStrategies() }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── Admin: usage stats (enhanced with billing info) ───
    if (url.pathname === '/usage' && method === 'GET') {
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const key = url.searchParams.get('key') || auth.key || '';
      const daysStr = url.searchParams.get('days') || '1';
      if (!key || !env.GATEWAY_KV) {
        return new Response(JSON.stringify({ error: 'No KV binding or key specified' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }

      // Current rate limit stats
      const rateStats = await getUsageStats(env.GATEWAY_KV, key);

      // Today's usage aggregate
      const days = Math.min(parseInt(daysStr, 10) || 1, 90);
      const usageHistory = await getUsageHistory(env.GATEWAY_KV, key, days);

      // Current month
      const now = new Date();
      const monthKey = `${now.getFullYear()}${pad2(now.getMonth() + 1)}`;
      const currentMonth = await getMonthlyUsage(env.GATEWAY_KV, key, monthKey);

      return new Response(JSON.stringify({
        key: key.slice(0, 8) + '...',
        realtime: {
          currentMinute: rateStats.currentMinute,
          currentDay: rateStats.currentDay,
          remainingMinute: Math.max(0, 60 - rateStats.currentMinute),
          remainingDay: Math.max(0, 5000 - rateStats.currentDay),
        },
        limits: {
          perMinute: 60,
          perDay: 5000,
          expensivePerMinute: 20,
          expensivePerDay: 500,
        },
        recent: {
          days,
          totalCalls: usageHistory.totals.calls,
          totalCost: usageHistory.totals.cost,
          daily: usageHistory.daily,
        },
        currentMonth: currentMonth ? {
          month: monthKey,
          calls: currentMonth.count,
          cost: currentMonth.cost,
        } : null,
        toolPrices: TOOL_PRICES,
      }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── Admin: usage history ───
    if (url.pathname === '/usage/history' && method === 'GET') {
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const key = url.searchParams.get('key') || auth.key || '';
      const days = Math.min(parseInt(url.searchParams.get('days') || '7', 10), 90);
      if (!key || !env.GATEWAY_KV) {
        return new Response(JSON.stringify({ error: 'No KV binding or key specified' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const history = await getUsageHistory(env.GATEWAY_KV, key, days);
      return new Response(JSON.stringify({
        key: key.slice(0, 8) + '...',
        days,
        ...history,
      }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── Admin: billing report ───
    if (url.pathname === '/usage/billing' && method === 'GET') {
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const key = url.searchParams.get('key') || auth.key || '';
      const month = url.searchParams.get('month') || '';
      if (!key || !env.GATEWAY_KV) {
        return new Response(JSON.stringify({ error: 'No KV binding or key specified' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      if (!month || !/^\d{6}$/.test(month)) {
        return new Response(JSON.stringify({ error: 'Invalid month format. Use YYYYMM, e.g. 202606' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const report = await getBillingReport(env.GATEWAY_KV, key, month);
      if (!report) {
        return new Response(JSON.stringify({ key: key.slice(0, 8) + '...', month, error: 'No usage data for this month' }), { headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      return new Response(JSON.stringify({
        key: key.slice(0, 8) + '...',
        ...report,
      }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // ─── Audit logs ───
    if (url.pathname === '/logs' && method === 'GET') {
      const auth = await verifyAuth(request, env);
      if (!auth.ok) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      if (!env.GATEWAY_KV) {
        return new Response(JSON.stringify({ error: 'KV not bound' }), { status: 400, headers: { 'Content-Type': 'application/json', ...corsHeaders } });
      }
      const date = url.searchParams.get('date') || undefined;
      const limit = parseInt(url.searchParams.get('limit') || '50', 10);
      const cursor = url.searchParams.get('cursor') || undefined;
      const result = await queryAuditLogs(env.GATEWAY_KV, { date, limit, cursor });
      return new Response(JSON.stringify(result), {
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
        case 'initialize':
          response = {
            jsonrpc: '2.0',
            result: {
              protocolVersion: '2025-03-26',
              capabilities: {
                tools: {},
                logging: {},
              },
              serverInfo: {
                name: 'mcp-gateway',
                version: '1.0.0',
              },
            },
            id: body.id,
          };
          break;
        case 'tools/list':
          response = handleToolsList();
          break;
        case 'tools/call': {
          // ─── Rate limit: only check for tool calls ───
          const toolName = body.params?.name || '';
          if (toolName && env.GATEWAY_KV) {
            const rl = await checkRateLimit(env.GATEWAY_KV, auth.key || 'anonymous', toolName);
            if (!rl.allowed) {
              response = {
                jsonrpc: '2.0',
                error: {
                  code: -32029,
                  message: rl.error || 'Rate limit exceeded',
                  data: { remainingMinute: rl.remainingMinute, remainingDay: rl.remainingDay, resetMinute: rl.resetMinute },
                },
                id: body.id,
              };
              break;
            }
          }
          // ─── Execute tool —──
          const startMs = Date.now();
          response = await handleToolsCall(body, env);
          const durationMs = Date.now() - startMs;
          // ─── Audit log (fire-and-forget, don't block response) ───
          if (toolName && env.GATEWAY_KV && auth.key) {
            const safeArgs: Record<string, any> = {};
            if (body.params?.arguments) {
              for (const [k, v] of Object.entries(body.params.arguments)) {
                if (['code', 'name', 'strategy', 'days', 'capital'].includes(k)) {
                  safeArgs[k] = v;
                }
              }
            }
            // Write audit log entry directly to KV
            const ts = new Date().toISOString();
            const dateKey = ts.slice(0, 10).replace(/-/g, '');
            const kvKey = 'audit:' + dateKey + ':' + Date.now() + ':' + Math.floor(Math.random() * 10000);
            const logEntry = JSON.stringify({
              timestamp: ts,
              apiKey: auth.key.slice(0, 8) + '...',
              tool: toolName,
              args: safeArgs,
              status: response.error ? 'error' : 'ok',
              durationMs,
              errorMessage: response.error?.message || null,
            });
            // Blocking write for reliability
            await env.GATEWAY_KV.put(kvKey, logEntry, { expirationTtl: 604800 });

            // ─── Usage tracking (background, but guaranteed via waitUntil) ───
            ctx.waitUntil(recordUsage(env.GATEWAY_KV, auth.key, toolName));
          }
          break;
        }
        default:
          response = {
            jsonrpc: '2.0',
            error: { code: -32601, message: `Method not found: ${body.method}` },
            id: body.id || null,
          };
      }

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

      writer.write(encoder.encode(`event: endpoint\ndata: ${JSON.stringify({ protocol: 'mcp', version: '1.0.0', tools: TOOLS.length })}\n\n`));

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
