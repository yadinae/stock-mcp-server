#!/usr/bin/env python3
"""
Autoresearch CLI — Prompt 自动优化入口

用法:
    python3 scripts/autoresearch.py status     # 查看各 prompt 角色评分
    python3 scripts/autoresearch.py analyze    # 分析最差角色的改进方向
    python3 scripts/autoresearch.py optimize   # 执行一个优化循环（生成改进建议）
    python3 scripts/autoresearch.py optimize --auto  # 自动应用改进
"""
import sys
import json
from pathlib import Path

# 确保项目根目录在 path
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.handlers.prompt_store import PromptStore
from tools.handlers.autoresearch import AutoresearchEngine


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    store = PromptStore()
    engine = AutoresearchEngine(store)

    if cmd == "status":
        print(engine.report())
        # 也输出 JSON 版本
        stats = store.get_stats()
        print("\n## JSON 数据")
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif cmd == "analyze":
        worst = store.get_worst_role()
        if not worst:
            print("无评分数据")
            return 1
        analysis = engine.analyze_performance(worst)
        print(json.dumps(analysis, ensure_ascii=False, indent=2, default=str))

    elif cmd == "optimize":
        auto = "--auto" in sys.argv
        result = engine.run_cycle(auto_apply=auto)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif cmd == "record":
        # 手动记录一次评分（测试用）
        if len(sys.argv) < 5:
            print("用法: autoresearch.py record <role> <score> [stock]")
            return 1
        role = sys.argv[2]
        score = float(sys.argv[3])
        stock = sys.argv[4] if len(sys.argv) > 4 else ""
        store.record_score(role, score, stock=stock)
        print(f"✅ 记录: {role} = {score} (stock={stock})")

    elif cmd == "test-store":
        # 测试 PromptStore 功能
        print("=== PromptStore 功能测试 ===")
        for role in ["bull_researcher", "bear_researcher", "cross_examination", "moderator"]:
            store.init_prompt(role)
            prompt = store.get_prompt(role)
            print(f"  {role}: v{store._data['prompts'][role]['current_version']}, {len(prompt)} chars")

        # 记录测试评分
        store.record_score("bull_researcher", 75.0, stock="600519")
        store.record_score("bull_researcher", 82.0, stock="000001")
        store.record_score("bear_researcher", 68.0, stock="600519")
        print(f"\n  最差角色: {store.get_worst_role()}")
        print(f"  统计: {json.dumps(store.get_stats(), ensure_ascii=False)}")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
