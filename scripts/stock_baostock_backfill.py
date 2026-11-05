#!/usr/bin/env python3
"""后台增量回填 baostock 缓存 — 小批慢速，稳步补全市场 K 线
每次调用只回填一批（默认 300 只），供 cron 每日增量跑，避免 baostock 连接过载。
"""
import sys, time
sys.path.insert(0, '/home/agentuser/stock-mcp-server')
from data_sources.baostock_source import get_all_a_symbols, backfill_batch


def main(batch_size=300):
    print(f"[{time.strftime('%H:%M:%S')}] Loading symbol list...", flush=True)
    symbols = get_all_a_symbols()
    if not symbols:
        print("ERROR: no symbols")
        return
    print(f"Total A-shares: {len(symbols)}", flush=True)

    # 分批回填，仅本批
    start = time.time()
    total_success = 0
    total_rows = 0
    for i in range(0, min(len(symbols), batch_size), 100):
        batch = symbols[i:i+100]
        print(f"[{time.strftime('%H:%M:%S')}] refund batch {i+1}-{i+len(batch)}...", flush=True)
        try:
            result = backfill_batch(batch, start_date="2024-01-01")
            if "error" in result:
                print(f"  error: {result['error']}", flush=True)
            else:
                total_success += result.get("success", 0)
                total_rows += result.get("total_rows", 0)
                print(f"  ok: {result.get('success')} succ, {result.get('skipped')} skip, "
                      f"{result.get('failed')} fail, {result.get('total_rows')} rows", flush=True)
        except Exception as e:
            print(f"  batch ex: {e}", flush=True)
        time.sleep(2)

    print(f"[{time.strftime('%H:%M:%S')}] BATCH DONE {time.time()-start:.0f}s: "
          f"{total_success} succ, {total_rows} rows", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=300)
    args = ap.parse_args()
    main(args.batch)