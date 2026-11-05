#!/bin/bash
# run_funnel 主逻辑（由 funnel_postmarket.sh wrapper 调用，经 post_handler 判定）
# 输出：人类可读摘要（执行报告 + 候选一行一只），不再裸 tail JSON
cd /home/agentuser/stock-mcp-server || exit 1
OUT=$(timeout 500 /home/agentuser/stock-mcp-venv/bin/python scripts/run_funnel.py 2>/dev/null)
RC=$?
if [ $RC -ne 0 ]; then
  echo "漏斗扫描失败 (exit=$RC)"
  timeout 500 /home/agentuser/stock-mcp-venv/bin/python scripts/run_funnel.py 2>&1 | tail -5
  exit 1
fi
# 执行报告（Pipeline 执行报告…信号统计 段）
echo "$OUT" | sed -n '/Pipeline 执行报告/,/^$/p'
# 候选：从 JSON 提取为一行一只（heredoc 会占用 stdin，不能与管道同用 → 写临时文件）
TMP=$(mktemp /tmp/funnel_fmt.XXXXXX)
echo "$OUT" > "$TMP"
/home/agentuser/stock-mcp-venv/bin/python - "$TMP" <<'EOF'
import sys, json, re
out = open(sys.argv[1]).read()
idx = out.find("候选列表")
seg = out[idx:] if idx >= 0 else out
m = re.search(r"\[\s*\{.*\}\s*\]", seg, re.S)
if not m:
    print("（本轮漏斗无候选）"); sys.exit(0)
for c in json.loads(m.group(0)):
    ch = "+".join(c.get("channels", []))
    print(f"  {c.get('name')}({c.get('code')}) 现价{c.get('price')} 涨跌{c.get('change_pct')}% "
          f"评分{c.get('funnel_score')} 通道[{ch}]")
EOF
rm -f "$TMP"
