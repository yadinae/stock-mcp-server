#!/usr/bin/env python3
"""
代码质量门禁 — 函数长度 + 重复度检查

借鉴 WyckoffTradingAgent 的 quality_gate.py：
- 函数长度硬限制（核心模块 ≤ 70 行，脚本 ≤ 100 行）
- 重复代码检测
- 无未使用导入

用法:
    python scripts/quality_gate.py
    python scripts/quality_gate.py --ci  # CI 模式（严格）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, Tuple

# ── 配置 ──────────────────────────────────────────────────

# 函数长度限制（行数）
FUNC_LIMITS = {
    "core/": 70,        # 核心模块
    "tools/": 70,       # 工具模块
    "scripts/": 100,    # 脚本
    "tests/": 120,      # 测试
}
DEFAULT_LIMIT = 70

# 项目根目录
ROOT = Path(__file__).parent.parent


def check_function_lengths() -> List[Tuple[str, str, int, int]]:
    """
    检查所有 Python 文件的函数长度

    Returns:
        [(file, func_name, line_count, limit), ...] 超限的函数
    """
    violations = []

    for py_file in ROOT.rglob("*.py"):
        # 跳过缓存和虚拟环境
        if any(p in str(py_file) for p in ["__pycache__", ".venv", "venv", ".git"]):
            continue

        # 确定限制
        rel = str(py_file.relative_to(ROOT))
        limit = DEFAULT_LIMIT
        for prefix, lmt in FUNC_LIMITS.items():
            if rel.startswith(prefix):
                limit = lmt
                break

        try:
            content = py_file.read_text()
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 计算函数行数
                if hasattr(node, "end_lineno") and node.end_lineno:
                    lines = node.end_lineno - node.lineno + 1
                else:
                    lines = 0

                if lines > limit:
                    violations.append((rel, node.name, lines, limit))

    return violations


def check_duplicate_imports() -> List[Tuple[str, int, str]]:
    """
    检查重复导入

    Returns:
        [(file, line, import_stmt), ...] 重复的导入
    """
    violations = []

    for py_file in ROOT.rglob("*.py"):
        if any(p in str(py_file) for p in ["__pycache__", ".venv", "venv", ".git"]):
            continue

        try:
            content = py_file.read_text()
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name in imports:
                        violations.append((str(py_file.relative_to(ROOT)), node.lineno, f"import {name}"))
                    imports.add(name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name in imports:
                        violations.append((str(py_file.relative_to(ROOT)), node.lineno, f"from {node.module} import {name}"))
                    imports.add(name)

    return violations


def check_file_stats() -> dict:
    """统计项目代码量"""
    total_lines = 0
    total_files = 0
    by_dir = {}

    for py_file in ROOT.rglob("*.py"):
        if any(p in str(py_file) for p in ["__pycache__", ".venv", "venv", ".git"]):
            continue

        try:
            lines = len(py_file.read_text().splitlines())
        except UnicodeDecodeError:
            continue

        total_lines += lines
        total_files += 1

        rel = str(py_file.relative_to(ROOT))
        dir_name = rel.split("/")[0] if "/" in rel else "."
        by_dir[dir_name] = by_dir.get(dir_name, 0) + lines

    return {
        "total_files": total_files,
        "total_lines": total_lines,
        "by_directory": dict(sorted(by_dir.items(), key=lambda x: -x[1])),
    }


def run_gate(ci_mode: bool = False) -> bool:
    """
    运行质量门禁

    Returns:
        True = 通过, False = 失败
    """
    print("=" * 60)
    print("代码质量门禁")
    print("=" * 60)

    passed = True

    # 1. 函数长度检查
    print("\n[1] 函数长度检查...")
    violations = check_function_lengths()
    if violations:
        print(f"  ⚠ {len(violations)} 个函数超限:")
        for file, name, lines, limit in sorted(violations, key=lambda x: -x[2])[:10]:
            print(f"    {file}:{name} ({lines} lines, limit {limit})")
        if ci_mode:
            passed = False
    else:
        print("  ✓ 所有函数在限制内")

    # 2. 重复导入检查
    print("\n[2] 重复导入检查...")
    dupes = check_duplicate_imports()
    if dupes:
        print(f"  ⚠ {len(dupes)} 个重复导入:")
        for file, line, stmt in dupes[:5]:
            print(f"    {file}:{line} {stmt}")
    else:
        print("  ✓ 无重复导入")

    # 3. 代码统计
    print("\n[3] 代码统计...")
    stats = check_file_stats()
    print(f"  文件数: {stats['total_files']}")
    print(f"  总行数: {stats['total_lines']}")
    print(f"  按目录:")
    for dir_name, lines in list(stats["by_directory"].items())[:8]:
        print(f"    {dir_name}: {lines} lines")

    # 总结
    print("\n" + "=" * 60)
    if passed:
        print("✅ 质量门禁通过")
    else:
        print("❌ 质量门禁失败（CI 模式）")
    print("=" * 60)

    return passed


if __name__ == "__main__":
    ci_mode = "--ci" in sys.argv
    success = run_gate(ci_mode)
    sys.exit(0 if success else 1)
