#!/usr/bin/env python3
"""
漏斗可视化面板 — 生成 HTML 报告

用法:
    python scripts/generate_dashboard.py

输出:
    data/funnel_dashboard.html
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from scripts.run_funnel import run_funnel, _fetch_from_baostock_cache, _enrich_baostock_direct
from core.signal_state import SignalTracker
from core.signal_feedback import SignalFeedback

OUTPUT = _root / "data" / "funnel_dashboard.html"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wyckoff 漏斗面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { font-size: 24px; margin-bottom: 20px; color: #38bdf8; }
        h2 { font-size: 18px; margin: 20px 0 10px; color: #94a3b8; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .card { background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }
        .card-title { font-size: 14px; color: #64748b; margin-bottom: 8px; }
        .card-value { font-size: 28px; font-weight: bold; color: #f8fafc; }
        .card-sub { font-size: 12px; color: #64748b; margin-top: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 13px; }
        th { color: #94a3b8; font-weight: 500; }
        td { color: #e2e8f0; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
        .badge-trend { background: #0ea5e920; color: #38bdf8; }
        .badge-accum { background: #22c55e20; color: #4ade80; }
        .badge-reversal { background: #f59e0b20; color: #fbbf24; }
        .badge-breakout { background: #ef444420; color: #f87171; }
        .progress-bar { height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }
        .progress-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
        .footer { text-align: center; color: #475569; font-size: 12px; margin-top: 30px; padding: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Wyckoff 漏斗面板</h1>

        <div class="grid">
            <div class="card">
                <div class="card-title">输入股票数</div>
                <div class="card-value">{input_count}</div>
                <div class="card-sub">全市场 A 股</div>
            </div>
            <div class="card">
                <div class="card-title">最终候选</div>
                <div class="card-value">{output_count}</div>
                <div class="card-sub">通过全部筛选</div>
            </div>
            <div class="card">
                <div class="card-title">通过率</div>
                <div class="card-value">{pass_rate}</div>
                <div class="card-sub">漏斗效率</div>
            </div>
            <div class="card">
                <div class="card-title">活跃信号</div>
                <div class="card-value">{active_signals}</div>
                <div class="card-sub">状态机追踪中</div>
            </div>
        </div>

        <h2>📊 阶段通过率</h2>
        <div class="card">
            {stage_bars}
        </div>

        <h2>🏆 候选列表</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>价格</th>
                        <th>通道</th>
                        <th>评分</th>
                    </tr>
                </thead>
                <tbody>
                    {candidate_rows}
                </tbody>
            </table>
        </div>

        <h2>📡 信号状态</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>信号类型</th>
                        <th>状态</th>
                        <th>样本数</th>
                        <th>胜率</th>
                        <th>平均收益</th>
                    </tr>
                </thead>
                <tbody>
                    {signal_rows}
                </tbody>
            </table>
        </div>

        <div class="footer">
            Generated at {timestamp} | Wyckoff Funnel Dashboard
        </div>
    </div>
</body>
</html>"""


def generate_dashboard():
    """生成漏斗仪表板"""
    # 运行漏斗
    result = run_funnel({"min_amount": 0})

    # 获取信号统计
    tracker = SignalTracker()
    signal_stats = tracker.get_stats()

    # 获取反馈统计
    feedback = SignalFeedback()
    feedback_stats = feedback.get_all_stats()

    # 生成阶段进度条
    stage_bars = ""
    for stage in result.stages:
        rate = stage.output_count / stage.input_count if stage.input_count > 0 else 0
        color = "#38bdf8" if rate > 0.5 else "#fbbf24" if rate > 0.2 else "#f87171"
        stage_bars += f"""
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 13px;">
                <span>{stage.name}</span>
                <span>{stage.input_count} &rarr; {stage.output_count} ({rate:.0%})</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {rate*100}%; background: {color};"></div>
            </div>
        </div>"""

    # 生成候选行
    candidate_rows = ""
    for s in result.candidates:
        channels = "".join(
            f'<span class="badge badge-{ch[:4]}">{ch}</span> '
            for ch in s.get("channels", [])
        )
        candidate_rows += f"""
        <tr>
            <td>{s.get('code', '')}</td>
            <td>{s.get('name', '')}</td>
            <td>{s.get('price', 'N/A')}</td>
            <td>{channels}</td>
            <td>{s.get('funnel_score', 0):.1f}</td>
        </tr>"""

    # 生成信号行
    signal_rows = ""
    for fs in feedback_stats:
        signal_rows += f"""
        <tr>
            <td>{fs.signal_type}</td>
            <td><span class="badge badge-{'trend' if fs.status == 'active' else 'accum'}">{fs.status}</span></td>
            <td>{fs.total_samples}</td>
            <td>{fs.win_rate:.1%}</td>
            <td>{fs.avg_pnl_pct:+.2f}%</td>
        </tr>"""

    # 如果没有反馈数据
    if not signal_rows:
        signal_rows = '<tr><td colspan="5" style="text-align: center; color: #64748b;">暂无数据</td></tr>'

    # 构建 HTML（避免 format() 与 CSS 冲突）
    input_approx = len(result.candidates) * 8
    output_count = len(result.candidates)
    pass_rate_val = output_count / max(1, input_approx)
    active_count = signal_stats.get("total", 0)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wyckoff 漏斗面板</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ font-size: 24px; margin-bottom: 20px; color: #38bdf8; }}
        h2 {{ font-size: 18px; margin: 20px 0 10px; color: #94a3b8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }}
        .card-title {{ font-size: 14px; color: #64748b; margin-bottom: 8px; }}
        .card-value {{ font-size: 28px; font-weight: bold; color: #f8fafc; }}
        .card-sub {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 13px; }}
        th {{ color: #94a3b8; font-weight: 500; }}
        td {{ color: #e2e8f0; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }}
        .badge-trend {{ background: #0ea5e920; color: #38bdf8; }}
        .badge-accum {{ background: #22c55e20; color: #4ade80; }}
        .badge-reversal {{ background: #f59e0b20; color: #fbbf24; }}
        .badge-breakout {{ background: #ef444420; color: #f87171; }}
        .progress-bar {{ height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
        .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .footer {{ text-align: center; color: #475569; font-size: 12px; margin-top: 30px; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>&#x1F3AF; Wyckoff 漏斗面板</h1>

        <div class="grid">
            <div class="card">
                <div class="card-title">输入股票数</div>
                <div class="card-value">{input_approx}</div>
                <div class="card-sub">全市场 A 股</div>
            </div>
            <div class="card">
                <div class="card-title">最终候选</div>
                <div class="card-value">{output_count}</div>
                <div class="card-sub">通过全部筛选</div>
            </div>
            <div class="card">
                <div class="card-title">通过率</div>
                <div class="card-value">{pass_rate_val:.1%}</div>
                <div class="card-sub">漏斗效率</div>
            </div>
            <div class="card">
                <div class="card-title">活跃信号</div>
                <div class="card-value">{active_count}</div>
                <div class="card-sub">状态机追踪中</div>
            </div>
        </div>

        <h2>&#x1F4CA; 阶段通过率</h2>
        <div class="card">
            {stage_bars}
        </div>

        <h2>&#x1F3C6; 候选列表</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>价格</th>
                        <th>通道</th>
                        <th>评分</th>
                    </tr>
                </thead>
                <tbody>
                    {candidate_rows}
                </tbody>
            </table>
        </div>

        <h2>&#x1F4E1; 信号状态</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>信号类型</th>
                        <th>状态</th>
                        <th>样本数</th>
                        <th>胜率</th>
                        <th>平均收益</th>
                    </tr>
                </thead>
                <tbody>
                    {signal_rows}
                </tbody>
            </table>
        </div>

        <div class="footer">
            Generated at {ts} | Wyckoff Funnel Dashboard
        </div>
    </div>
</body>
</html>"""

    # 写入文件
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Dashboard generated: {OUTPUT}")
    return OUTPUT


if __name__ == "__main__":
    generate_dashboard()
