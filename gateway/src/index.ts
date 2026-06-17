/**
 * MCP Gateway — Full 12-tool implementation on Cloudflare Workers
 * ==============================================================
 *
 * Migrated from stock-mcp-server (Python) to TypeScript.
 * All tools run inline via fetch() — zero Python dependencies.
 */

import { Env, JsonRpcRequest, JsonRpcResponse, McpTool, McpResourceTemplate } from './types';
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

// ───── MCP Resource Definitions ─────
// Stock resources use URIs: stock://{code}/{type}
// Types: quote, kline, technical, financials, news, context

const RESOURCE_TEMPLATES: McpResourceTemplate[] = [
  {
    uriTemplate: 'stock://{code}/quote',
    name: '股票实时行情',
    description: '获取单只股票的实时行情数据（价格、涨跌幅、成交量等）',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://{code}/kline',
    name: '股票K线数据',
    description: '获取股票最近60个交易日的日K线数据（开/高/低/收/量）',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://{code}/technical',
    name: '股票技术分析',
    description: '获取股票技术分析指标（MA/MACD/RSI/布林带/趋势评分）',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://{code}/financials',
    name: '股票财务数据',
    description: '获取股票最新财务报表核心数据（营收/利润/EPS/FCF/负债）',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://{code}/news',
    name: '股票相关新闻',
    description: '获取股票近期的相关新闻',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://{code}/context',
    name: '股票综合概览',
    description: '一次调用获取股票的实时行情 + K线 + 技术分析综合数据',
    mimeType: 'application/json',
  },
  {
    uriTemplate: 'stock://list/hot',
    name: '热门股票列表',
    description: '获取当前热门股票列表（示例数据）',
    mimeType: 'application/json',
  },
];

/** Resolve a stock:// URI to its data */
async function resolveResource(uri: string, env: Env): Promise<{ content: any; mimeType: string } | null> {
  // Parse stock://{code}/{type}
  const match = uri.match(/^stock:\/\/([^/]+)\/(\w+)$/);
  if (!match) return null;
  const code = match[1];
  const type = match[2];

  // Handle special URIs
  if (code === 'list' && type === 'hot') {
    return {
      content: { stocks: ['600519', '000001', '300750', 'AAPL', 'HK00700'], note: '示例热门列表，可通过 get_realtime_quote 工具查询各代码' },
      mimeType: 'application/json',
    };
  }

  const ct = codeType(code);
  if (ct === 'unknown') {
    return { content: { error: `无法识别股票代码: ${code}` }, mimeType: 'application/json' };
  }

  try {
    switch (type) {
      case 'quote': {
        let quote: any;
        if (ct === 'a') quote = await tencent.getRealtimeQuote(code);
        else quote = await yahoo.getRealtimeQuote(code);
        return { content: quote, mimeType: 'application/json' };
      }
      case 'kline': {
        let kline: any;
        if (ct === 'a') kline = await tencent.getKline(code, 60);
        else kline = await yahoo.getKline(code, 60);
        return { content: kline, mimeType: 'application/json' };
      }
      case 'technical': {
        let records: any[];
        if (ct === 'a') {
          const kline = await tencent.getKline(code, 90);
          records = kline.records || [];
        } else {
          const kline = await yahoo.getKline(code, 90);
          records = kline.records || [];
        }
        const result = await analyzeTechnical(records, code);
        return { content: result, mimeType: 'application/json' };
      }
      case 'financials': {
        const fin = await fetchFinancials(code);
        return { content: fin, mimeType: 'application/json' };
      }
      case 'news': {
        const news = await searchNews(code, '');
        return { content: news, mimeType: 'application/json' };
      }
      case 'context': {
        let quote: any, kline: any;
        if (ct === 'a') {
          [quote, kline] = await Promise.all([tencent.getRealtimeQuote(code), tencent.getKline(code, 60)]);
        } else {
          [quote, kline] = await Promise.all([yahoo.getRealtimeQuote(code), yahoo.getKline(code, 60)]);
        }
        let technical: any = { error: '无K线数据' };
        const records = kline.records || [];
        if (records.length > 0) {
          technical = await analyzeTechnical(records, code);
        }
        return {
          content: { code, name: quote.name || code, quote, kline, technical },
          mimeType: 'application/json',
        };
      }
      default:
        return { content: { error: `未知资源类型: ${type}，可用类型: quote, kline, technical, financials, news, context` }, mimeType: 'application/json' };
    }
  } catch (err: any) {
    return { content: { error: err.message || '获取资源失败' }, mimeType: 'application/json' };
  }
}

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

    // ─── Admin: Dashboard UI ───
    if (url.pathname === '/dashboard' && method === 'GET') {
      const dashboardHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Gateway 管理面板</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 24px; margin-bottom: 8px; color: #f8fafc; }
  .subtitle { color: #94a3b8; margin-bottom: 24px; font-size: 14px; }
  .card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 16px; border: 1px solid #334155; }
  .card h2 { font-size: 16px; color: #f1f5f9; margin-bottom: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 16px; }
  .stat { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
  .stat .label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat .value { font-size: 28px; font-weight: 700; color: #f8fafc; margin-top: 4px; }
  .stat .value.green { color: #22c55e; }
  .stat .value.yellow { color: #eab308; }
  .stat .value.red { color: #ef4444; }
  .stat .sub { font-size: 12px; color: #64748b; margin-top: 4px; }
  .section { margin-bottom: 24px; }
  label { display: block; font-size: 14px; color: #94a3b8; margin-bottom: 6px; }
  input, select { width: 100%; padding: 10px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 14px; margin-bottom: 12px; }
  input:focus, select:focus { outline: none; border-color: #3b82f6; }
  button { background: #3b82f6; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; }
  button:hover { background: #2563eb; }
  button.secondary { background: #334155; }
  button.secondary:hover { background: #475569; }
  button.danger { background: #ef4444; }
  button.danger:hover { background: #dc2626; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 10px 8px; color: #94a3b8; font-weight: 600; border-bottom: 1px solid #334155; }
  td { padding: 8px; border-bottom: 1px solid #1e293b; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge.ok { background: #166534; color: #86efac; }
  .badge.err { background: #7f1d1d; color: #fca5a5; }
  .badge.free { background: #1e3a5f; color: #93c5fd; }
  .badge.paid { background: #713f12; color: #fde68a; }
  .tabs { display: flex; gap: 4px; margin-bottom: 16px; }
  .tab { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; color: #94a3b8; background: transparent; border: 1px solid transparent; }
  .tab.active { background: #334155; color: #f8fafc; border-color: #475569; }
  .tab:hover { color: #e2e8f0; }
  .panel { display: none; }
  .panel.active { display: block; }
  .code { font-family: 'SF Mono', Monaco, monospace; font-size: 12px; background: #0f172a; padding: 12px; border-radius: 8px; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #166534; color: #86efac; padding: 12px 20px; border-radius: 8px; font-size: 14px; opacity: 0; transition: opacity 0.3s; }
  .toast.error { background: #7f1d1d; color: #fca5a5; }
  .toast.show { opacity: 1; }
  .flex-row { display: flex; gap: 8px; align-items: center; }
  .key-display { font-family: monospace; background: #0f172a; padding: 8px 12px; border-radius: 6px; word-break: break-all; margin: 8px 0; font-size: 13px; }
  .mt-2 { margin-top: 12px; }
  .mb-2 { margin-bottom: 12px; }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: #0f172a; }
  ::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
</style>
</head>
<body>
<div class="container">
  <div class="flex-row" style="justify-content:space-between;">
    <div>
      <h1>🔧 MCP Gateway 管理面板</h1>
      <div class="subtitle">stock-mcp-server · Cloudflare Workers</div>
    </div>
    <div id="statusBadge" style="font-size:12px;padding:6px 12px;border-radius:6px;background:#1e293b;border:1px solid #334155;">⏳ 加载中...</div>
  </div>

  <div class="card" style="margin-top:16px;">
    <h2>🔑 API 凭证</h2>
    <div class="flex-row">
      <input type="text" id="apiKey" placeholder="输入 API Key..." style="margin-bottom:0;flex:1;font-family:monospace;font-size:13px;">
      <button id="loadBtn" onclick="saveAndLoad()">加载</button>
      <button class="secondary" onclick="clearKey()" style="white-space:nowrap;">清除</button>
    </div>
    <div id="accessStatus" style="margin-top:8px;padding:8px;background:#0f172a;border-radius:6px;font-size:13px;display:flex;align-items:center;gap:8px;">
      <span id="statusDot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#eab308;"></span>
      <span id="statusText">输入 API Key 加载数据</span>
    </div>
  </div>

  <!-- Stats -->
  <div class="grid" id="statsGrid">
    <div class="stat"><div class="label">工具数</div><div class="value" id="toolCount">-</div></div>
    <div class="stat"><div class="label">资源模板</div><div class="value" id="resourceCount">-</div></div>
    <div class="stat"><div class="label">今日调用</div><div class="value" id="todayCalls">-</div></div>
    <div class="stat"><div class="label">本月费用</div><div class="value" id="monthCost">-</div><div class="sub" id="monthCallsSub"></div></div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" onclick="switchTab('tools')" id="tabTools">🔧 工具列表</div>
    <div class="tab" onclick="switchTab('usage')" id="tabUsage">📊 用量详情</div>
    <div class="tab" onclick="switchTab('logs')" id="tabLogs">📋 审计日志</div>
    <div class="tab" onclick="switchTab('keys')" id="tabKeys">🔑 Key 管理</div>
  </div>

  <div id="panelTools" class="panel active"></div>
  <div id="panelUsage" class="panel">
    <div class="card"><h2>📈 用量趋势</h2><div id="usageChart" class="code" style="max-height:300px;">输入 API Key 后加载</div></div>
    <div class="card"><h2>🏆 工具热度排行</h2><div id="toolRanking" class="code" style="max-height:300px;">输入 API Key 后加载</div></div>
  </div>
  <div id="panelLogs" class="panel">
    <div class="card">
      <div class="flex-row" style="justify-content:space-between;">
        <h2>📋 审计日志</h2>
        <div class="flex-row">
          <label for="logDays" style="margin:0;font-size:12px;">天数</label>
          <select id="logDays" style="width:80px;margin:0;" onchange="loadLogs()">
            <option value="1">今天</option>
            <option value="3" selected>3天</option>
            <option value="7">7天</option>
          </select>
        </div>
      </div>
      <div id="logList" class="code" style="max-height:500px;">输入 API Key 后加载</div>
    </div>
  </div>
  <div id="panelKeys" class="panel">
    <div class="card">
      <h2>新建 API Key</h2>
      <input type="text" id="newKeyName" placeholder="Key 名称（如: my-app）">
      <button onclick="createKey()">生成新 Key</button>
      <div id="keyResult" class="key-display mt-2" style="display:none;"></div>
    </div>
    <div class="card">
      <h2>已创建的 Key</h2>
      <div class="code" style="max-height:300px;" id="keyList">功能预览：API Key 创建后存储在 KV，支持按名称/配额管理。当前使用 GATEWAY_API_KEY 环境变量认证。</div>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
const BASE = window.location.origin;
let apiKey = localStorage.getItem('mcp_gateway_key') || '';

function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (isError ? 'error show' : 'show');
  setTimeout(() => t.className = 'toast', 3000);
}

async function apiFetch(path) {
  const headers = {};
  // Try Access first (if page is behind Access or Service Token)
  // Fall back to Bearer token
  if (apiKey) {
    headers['Authorization'] = 'Bearer ' + apiKey;
  }
  const r = await fetch(BASE + path, { headers, credentials: 'same-origin' });
  if (r.status === 401) {
    const cur = document.getElementById('statusText');
    if (cur) cur.textContent = '❌ 未认证 - 请输入 API Key 或通过 Cloudflare Access 访问';
    showToast('需要认证', true);
  }
  if (r.status === 302) {
    // Access redirect - try without Bearer (might be protected by Access)
    if (apiKey) {
      const r2 = await fetch(BASE + path, { credentials: 'same-origin' });
      if (r2.status === 302) {
        showToast('此页面需 Cloudflare Access 登录 - 请打开浏览器访问', true);
        return null;
      }
      return r2.json();
    }
    showToast('需要 Cloudflare Access 登录', true);
    return null;
  }
  return r.json();
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const el = document.getElementById('tab' + name.charAt(0).toUpperCase() + name.slice(1));
  if (el) el.classList.add('active');
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById('panel' + name.charAt(0).toUpperCase() + name.slice(1));
  if (panel) panel.classList.add('active');
}

function saveAndLoad() {
  const input = document.getElementById('apiKey');
  apiKey = input ? input.value.trim() : '';
  if (apiKey) localStorage.setItem('mcp_gateway_key', apiKey);
  loadAll();
}

function clearKey() {
  localStorage.removeItem('mcp_gateway_key');
  apiKey = '';
  const input = document.getElementById('apiKey');
  if (input) input.value = '';
  showToast('Key 已清除');
}

// Auto-load if key saved
document.addEventListener('DOMContentLoaded', () => {
  if (apiKey) {
    document.getElementById('apiKey').value = apiKey;
    loadAll();
  } else {
    // Try without key (might be behind Access)
    loadAll();
  }
});

async function loadAll() {
  try {
    document.getElementById('statusBadge').textContent = '⏳ 加载中...';
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    if (statusDot) statusDot.style.background = '#eab308';
    if (statusText) statusText.textContent = '⏳ 加载数据...';
    await Promise.all([loadHealth(), loadUsage(), loadLogs()]);
    document.getElementById('statusBadge').textContent = '✅ 已连接';
    document.getElementById('statusBadge').style.borderColor = '#166534';
    if (statusDot) statusDot.style.background = '#22c55e';
    if (statusText) statusText.textContent = apiKey ? '✅ Bearer Token' : '✅ 已连接 (Access)';
  } catch(e) {
    document.getElementById('statusBadge').textContent = '❌ 连接失败';
    document.getElementById('statusBadge').style.borderColor = '#7f1d1d';
    showToast('加载失败: ' + e.message, true);
  }
}

async function loadHealth() {
  const h = await apiFetch('/health');
  document.getElementById('toolCount').textContent = h.tools || '-';
  document.getElementById('resourceCount').textContent = '7';
  document.getElementById('todayCalls').textContent = '-';
  // Tools list
  let toolsHtml = '<div class="card"><h2>🔧 可用工具 (' + (h.tools || 0) + ')</h2><div class="code" style="max-height:400px;">';
  if (h.tool_names) toolsHtml += h.tool_names.map(n => '<span class="badge ok">' + n + '</span> ').join('');
  toolsHtml += '</div></div>';
  document.getElementById('panelTools').innerHTML = toolsHtml;
}

async function loadUsage() {
  try {
    const u = await apiFetch('/usage?days=7');
    document.getElementById('todayCalls').textContent = u.realtime?.currentDay || '-';
    if (u.currentMonth) {
      document.getElementById('monthCost').textContent = '$' + (u.currentMonth.cost || 0).toFixed(2);
      document.getElementById('monthCallsSub').textContent = u.currentMonth.calls + ' 次调用';
    } else {
      document.getElementById('monthCost').textContent = u.recent?.totalCalls + '次调用' || '-';
    }
    // Usage chart
    const daily = u.recent?.daily || [];
    let chartHtml = '';
    if (daily.length > 0) {
      chartHtml += '<table><tr><th>日期</th><th>调用次数</th><th>费用</th></tr>';
      daily.slice().reverse().forEach(d => {
        chartHtml += '<tr><td>' + d.date + '</td><td>' + (d.calls||0) + '</td><td>$' + (d.cost||0).toFixed(2) + '</td></tr>';
      });
      chartHtml += '</table>';
    } else {
      chartHtml += '暂无数据（最近 7 天无调用记录）';
    }
    document.getElementById('usageChart').innerHTML = chartHtml;

    // Tool ranking from health endpoint
    const h = await apiFetch('/health');
    let rankHtml = '<table><tr><th>工具名</th><th>备注</th></tr>';
    (h.tool_names || []).forEach(n => {
      rankHtml += '<tr><td>' + n + '</td><td><span class="badge free">免费</span></td></tr>';
    });
    rankHtml += '</table>';
    document.getElementById('toolRanking').innerHTML = rankHtml;
  } catch(e) {
    document.getElementById('usageChart').innerHTML = '加载失败: ' + e.message;
  }
}

async function loadLogs() {
  try {
    const days = document.getElementById('logDays').value;
    const logs = await apiFetch('/logs?limit=100&days=' + days);
    let html = '';
    const entries = logs.entries || logs.logs || [];
    if (entries.length === 0) {
      html = '暂无日志记录';
    } else {
      html += '<table><tr><th>时间</th><th>工具</th><th>代码</th><th>状态</th><th>耗时</th></tr>';
      entries.slice(0, 100).forEach(e => {
        const ts = e.timestamp || e.time || '-';
        const tool = e.tool || e.name || '-';
        const code = (e.args && e.args.code) || '-';
        const status = e.status || e.error ? 'error' : 'ok';
        html += '<tr><td>' + (ts.length > 16 ? ts.slice(0, 16) : ts) + '</td><td>' + tool + '</td><td>' + code + '</td><td><span class="badge ' + (status === 'ok' ? 'ok' : 'err') + '">' + status + '</span></td><td>' + (e.durationMs || '-') + 'ms</td></tr>';
      });
      html += '</table>';
    }
    document.getElementById('logList').innerHTML = html;
  } catch(e) {
    document.getElementById('logList').innerHTML = '加载失败: ' + e.message;
  }
}

async function createKey() {
  const name = document.getElementById('newKeyName').value.trim();
  if (!name) { showToast('请输入 Key 名称', true); return; }
  showToast('API Key 管理功能需对接 edge-key 发卡系统（P2 待办）', false);
  document.getElementById('keyResult').style.display = 'block';
  document.getElementById('keyResult').textContent = '即将支持：通过 edge-key 自动生成 API Key 并记录到 KV。当前请使用 GATEWAY_API_KEY 环境变量。';
}

// Load key from URL params
const params = new URLSearchParams(window.location.search);
if (params.get('key')) {
  document.getElementById('apiKey').value = params.get('key');
  loadAll();
}
</script>
</body>
</html>`;
      return new Response(dashboardHtml, {
        headers: { 'Content-Type': 'text/html; charset=utf-8', ...corsHeaders },
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

    // ─── MCP Protocol Endpoint (primary, behind Access if configured) ───
    if ((url.pathname === '/mcp' || url.pathname === '/v1') && method === 'POST') {
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
                resources: {},
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
        case 'resources/list':
          response = {
            jsonrpc: '2.0',
            result: {
              resourceTemplates: RESOURCE_TEMPLATES,
              resources: [
                {
                  uri: 'stock://list/hot',
                  name: '热门股票列表',
                  description: '获取当前热门股票列表',
                  mimeType: 'application/json',
                },
              ],
            },
            id: body.id,
          };
          break;
        case 'resources/read':
          try {
            const uri = body.params?.uri || '';
            if (!uri) {
              response = {
                jsonrpc: '2.0',
                error: { code: -32602, message: 'Missing resource URI' },
                id: body.id,
              };
              break;
            }
            const resolved = await resolveResource(uri, env);
            if (!resolved) {
              response = {
                jsonrpc: '2.0',
                error: { code: -32602, message: `Unknown resource URI: ${uri}. Use stock://{code}/{type} where type=quote|kline|technical|financials|news|context` },
                id: body.id,
              };
              break;
            }
            response = {
              jsonrpc: '2.0',
              result: {
                contents: [
                  {
                    uri,
                    mimeType: resolved.mimeType,
                    text: typeof resolved.content === 'string' ? resolved.content : JSON.stringify(resolved.content, null, 2),
                  },
                ],
              },
              id: body.id,
            };
          } catch (err: any) {
            response = {
              jsonrpc: '2.0',
              error: { code: -32603, message: err.message || 'Failed to read resource' },
              id: body.id,
            };
          }
          break;
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
