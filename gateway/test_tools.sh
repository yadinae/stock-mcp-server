#!/bin/bash
set -euo pipefail
# Test deployed MCP Gateway tools
HOST="https://mcp-gateway.yadinae.workers.dev"
KEY="${MCP_GATEWAY_KEY:-stock-gw-test-key-2026}"

call() {
  local method="$1"
  local params="$2"
  local id="$3"
  curl -s "$HOST/mcp" -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KEY" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"$method\",\"params\":$params,\"id\":$id}"
}

echo "=== 1. Health ==="
curl -s "$HOST/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Tools:', d['tools'], 'Cache:', d['cache'])"

echo ""
echo "=== 2. Realtime Quote (A股) ==="
call "tools/call" '{"name":"get_realtime_quote","arguments":{"code":"600519"}}' 1 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'{d.get(\"name\")} @ {d.get(\"price\")} ({d.get(\"change_pct\")}%)')"

echo ""
echo "=== 3. Kline ==="
call "tools/call" '{"name":"get_kline","arguments":{"code":"600519","days":5}}' 2 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'{len(d.get(\"records\",[]))} records')"

echo ""
echo "=== 4. Stock Context ==="
call "tools/call" '{"name":"get_stock_context","arguments":{"code":"AAPL"}}' 3 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'{d.get(\"name\")} - realtime: {bool(d.get(\"realtime\"))}, kline records: {len(d.get(\"kline\",{}).get(\"records\",[]))}')"

echo ""
echo "=== 5. Technical Analysis ==="
call "tools/call" '{"name":"get_technical_analysis","arguments":{"code":"600519"}}' 4 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'Score: {d.get(\"score\")} Advice: {d.get(\"advice\")} Trend: {d.get(\"trend\",{}).get(\"status\")} MACD: {d.get(\"macd\",{}).get(\"signal\")} RSI: {d.get(\"rsi\",{}).get(\"value\")} Candles: {len(d.get(\"candle_patterns\",[]))} Ichimoku: {d.get(\"ichimoku\",{}).get(\"trend\")}')"

echo ""
echo "=== 6. ST Risk ==="
call "tools/call" '{"name":"check_st_risk","arguments":{"code":"600519"}}' 5 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'Level: {d.get(\"max_level\")} ({d.get(\"level_name\")}) Signals: {d.get(\"signal_count\")}')"

echo ""
echo "=== 7. News ==="
call "tools/call" '{"name":"search_stock_news","arguments":{"code":"600519","name":"贵州茅台"}}' 6 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'{d.get(\"count\")} news items')"

echo ""
echo "=== 8. Backtest (MA Crossover) ==="
call "tools/call" '{"name":"check_backtest","arguments":{"code":"600519","strategy":"ma_crossover","days":180,"capital":100000}}' 7 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); m=d.get('metrics',{}); print(f'Return: {m.get(\"total_return_pct\")}% DD: {m.get(\"max_drawdown_pct\")}% Sharpe: {m.get(\"sharpe_ratio\")} Win: {m.get(\"win_rate_pct\")}% PF: {m.get(\"profit_factor\")} Trades: {d.get(\"trade_count\")}')"

echo ""
echo "=== 9. Backtest (Combined) ==="
call "tools/call" '{"name":"check_backtest","arguments":{"code":"600519","strategy":"combined","days":180,"capital":100000}}' 8 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); m=d.get('metrics',{}); print(f'Return: {m.get(\"total_return_pct\")}% DD: {m.get(\"max_drawdown_pct\")}% Sharpe: {m.get(\"sharpe_ratio\")} Win: {m.get(\"win_rate_pct\")}% PF: {m.get(\"profit_factor\")} Trades: {d.get(\"trade_count\")}')"

echo ""
echo "=== 10. Batch Stocks ==="
call "tools/call" '{"name":"analyze_stocks","arguments":{"stock_list":"600519,000001,AAPL,MSFT"}}' 9 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'{d.get(\"count\")} stocks'); [print(f'  {s.get(\"code\")}: {s.get(\"name\",\"\")} @ {s.get(\"price\",\"\")} ({s.get(\"change_pct\",\"\")}%)') for s in d.get('stocks',[])]"

echo ""
echo "=== 11. Data Source Health ==="
call "tools/call" '{"name":"get_data_source_health","arguments":{}}' 10 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); [print(f'  {s[\"name\"]}: {s[\"status\"]} ({s[\"success_rate\"]}% success)') for s in d.get('sources',[])]"

echo ""
echo "=== 12. Cache Stats ==="
call "tools/call" '{"name":"get_cache_stats","arguments":{}}' 11 | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'Hits: {d.get(\"hits\")} Misses: {d.get(\"misses\")} Ratio: {d.get(\"ratio\")} Size: {d.get(\"size\")}')"

echo ""
echo "=== ✅ All tools tested ==="
