#!/usr/bin/env python3
"""Narrative 概念归一化引擎 — 纯代码，零 LLM 成本

将东财原始概念标签映射为 A 股交易叙事（核心主线）。
灵感来自 easy-stock (https://github.com/jundizhou/easy-stock) narrative 模块，但针对 stock-mcp-server 场景重新设计。

核心功能：
1. 概念归一化: 200+ 东财概念标签 → 20 个核心叙事
2. 噪音过滤: 忽略融资融券/MSCI/指数成分等无效标签
3. 派生概念: 多标签组合 → 高级叙事（如 算力+云计算 → 算力租赁）
4. 证据评分: 概念交叉越强 → 叙事可信度越高
5. 广度折扣: 宽泛概念打折，具体概念加分
"""
from __future__ import annotations

from typing import Optional


# ─── 核心叙事规则 ──────────────────────────────────────────────
# 每条规则：叙事名称 + 匹配关键词（大小写不敏感）
# 关键词越具体越好，宽泛的放 breadth_discount 里打折
_NARRATIVE_RULES: list[dict] = [
    {
        "name": "AI应用",
        "keywords": [
            "AI应用", "AI智能体", "多模态AI", "AIGC", "CHATGPT",
            "DEEPSEEK", "KIMI", "SORA", "智谱AI", "大模型",
            "AI语料", "生成式AI", "文心一言", "豆包", "人工智能",
        ],
    },
    {
        "name": "AI算力",
        "keywords": [
            "算力概念", "东数西算", "液冷服务器", "AI服务器",
            "AI芯片", "华为昇腾", "英伟达概念", "GPU",
        ],
    },
    {
        "name": "光通信/CPO",
        "keywords": ["CPO", "光通信模块", "光模块", "硅光"],
    },
    {
        "name": "半导体芯片",
        "keywords": [
            "半导体概念", "国产芯片", "第三代半导体",
            "存储芯片", "先进封装", "光刻机", "EDA",
        ],
    },
    {
        "name": "机器人",
        "keywords": ["机器人概念", "人形机器人", "工业机器人", "机器视觉", "减速器"],
    },
    {
        "name": "华为生态",
        "keywords": ["华为概念", "鸿蒙概念", "华为鲲鹏", "欧拉", "盘古"],
    },
    {
        "name": "低空经济",
        "keywords": ["低空经济", "飞行汽车", "无人机", "eVTOL"],
    },
    {
        "name": "商业航天",
        "keywords": ["商业航天", "卫星互联网", "航天航空", "北斗"],
    },
    {
        "name": "创新药",
        "keywords": ["创新药", "减肥药", "AI制药", "CRO", "GLP-1"],
    },
    {
        "name": "固态电池/储能",
        "keywords": ["固态电池", "锂电池概念", "钠离子电池", "储能概念", "抽水蓄能"],
    },
    {
        "name": "新能源车",
        "keywords": ["新能源车", "新能源汽车", "充电桩", "换电", "整车"],
    },
    {
        "name": "数据要素",
        "keywords": ["数据要素", "数据确权", "数据安全", "大数据"],
    },
    {
        "name": "信创",
        "keywords": ["信创", "国产软件", "操作系统", "数据库", "中间件"],
    },
    {
        "name": "教育",
        "keywords": ["在线教育", "职业教育", "智慧教育", "教育信息化"],
    },
    {
        "name": "消费/白酒",
        "keywords": ["白酒", "消费", "免税", "新零售", "预制菜"],
    },
    {
        "name": "军工",
        "keywords": ["军工", "国防军工", "航母", "导弹", "军民融合"],
    },
    {
        "name": "房地产",
        "keywords": ["房地产", "物业管理", "装修装饰", "建材"],
    },
    {
        "name": "金融",
        "keywords": ["券商", "银行", "保险", "数字货币", "跨境支付"],
    },
    {
        "name": "传媒/短剧",
        "keywords": ["传媒", "短剧", "网络游戏", "虚拟数字人", "影视"],
    },
    {
        "name": "碳中和/环保",
        "keywords": ["碳中和", "碳交易", "环保", "绿色电力", "风电", "光伏"],
    },
]

# ─── 噪音标签（直接忽略，不计入任何叙事）─────────────────────────
_IGNORED_LABELS: set[str] = {
    "融资融券", "深股通", "沪股通", "转融券标的", "MSCI中国",
    "富时罗素", "标普道琼斯A股", "QFII重仓", "基金重仓", "机构重仓",
    "昨日涨停", "昨日连板", "创业板综", "上证180", "沪深300",
    "中证500", "中证1000", "深证100R", "深成500", "标准普尔",
    "A股", "B股", "H股", "北交所", "科创板", "深市A股", "沪市A股",
    "全息手机", "打板", "预盈预增", "预亏预减", "业绩报告",
}

# ─── 结构性标签（地域/改革类，广度折扣 0.3）─────────────────────────
_STRUCTURAL_LABELS: set[str] = {
    "长江三角", "深圳特区", "上海自贸", "粤港澳大湾区", "成渝特区",
    "海峡西岸", "央国企改革", "国企改革", "地方国企", "央企改革",
    "一带一路", "REITs概念", "B转H",
}

# ─── 广度折扣因子 ──────────────────────────────────────────────
# 越宽泛的概念折扣越大（0~1），1.0 = 无折扣
_BREADTH_DISCOUNT: dict[str, float] = {
    "AI应用": 0.5,          # 极宽泛，几乎所有科技股都沾边
    "人工智能": 0.5,        # 同上
    "华为生态": 0.65,      # 较宽泛
    "5G": 0.6,
    "新能源车": 0.7,
    "新能源": 0.5,
    "军工": 0.65,
    "房地产": 0.7,
    "金融": 0.55,
    "消费": 0.6,
    "传媒": 0.6,
    "环保": 0.6,
}

# ─── 派生概念规则 ──────────────────────────────────────────────
# 当标签集合同时包含 A 和 B 时，额外产生叙事 C
_DERIVED_RULES: list[dict] = [
    {
        "result": "算力租赁",
        "requires": ["算力概念"],
        "also_require_one": ["云计算", "数据中心"],
    },
    {
        "result": "AI应用",
        "requires": ["人工智能"],
        "also_require_one": [
            "网络游戏", "影视", "短剧", "传媒", "虚拟数字人",
            "在线教育", "智慧教育", "办公", "互联网服务", "数字营销",
            "元宇宙", "虚拟现实",
        ],
    },
]


def _normalize_label(raw: str) -> str:
    """去除常见后缀/前缀，返回标准化标签"""
    label = raw.strip()
    if label.endswith("板块"):
        label = label[:-2]
    if label.endswith("概念"):
        label = label[:-2]
    return label


def is_ignored(label: str) -> bool:
    """判断标签是否应被忽略"""
    normalized = _normalize_label(label)
    return normalized in _IGNORED_LABELS


def is_structural(name: str) -> bool:
    """判断叙事是否属于结构性/地域性标签"""
    return name in _STRUCTURAL_LABELS


def canonical_name(raw_label: str) -> Optional[str]:
    """将原始东财标签映射到核心叙事名称

    Args:
        raw_label: 东财原始概念标签

    Returns:
        核心叙事名称，无法匹配返回 None
    """
    normalized = _normalize_label(raw_label).upper()
    for rule in _NARRATIVE_RULES:
        for kw in rule["keywords"]:
            if kw.upper() in normalized or normalized in kw.upper():
                return rule["name"]
    return None


def breadth_discount(name: str) -> float:
    """返回叙事的广度折扣因子（0~1）

    越宽泛的概念折扣越大，用于加权计算叙事热度。
    """
    return _BREADTH_DISCOUNT.get(name, 1.0)


def evidence_score(name: str, matched_raw_labels: list[str]) -> float:
    """计算叙事的证据得分

    多标签交叉 = 更强的因果证据。
    例如：同时有 "算力概念" + "云计算" → 算力租赁的证据更强

    Returns:
        0~150 的证据分
    """
    n = len(matched_raw_labels)
    if n == 0:
        return 0
    # 基础分: 匹配标签数
    base = min(n * 30, 100)
    # 多标签加成: >=3 个不同标签 → 额外 +30
    if n >= 3:
        base += 30
    # 具体标签加成: 如果原始标签本身是"精确匹配"
    for raw in matched_raw_labels:
        norm = _normalize_label(raw)
        if norm == name:
            base += 20  # 精确命中核心叙事名
            break
    return min(base, 150)


def normalize_concepts(raw_concepts: list[str]) -> dict[str, dict]:
    """将东财原始概念标签列表归一化为叙事映射

    Args:
        raw_concepts: 东财返回的原始概念标签列表
            例: ["AI智能体", "大模型", "算力概念", "融资融券", "沪深300"]

    Returns:
        叙事映射 { 叙事名: { score, labels, discount, breadth_discounted } }
        例: {
            "AI应用": {"score": 100, "labels": ["AI智能体", "大模型"],
                       "discount": 1.0, "breadth_discounted": 100},
            "AI算力": {"score": 30, "labels": ["算力概念"],
                       "discount": 1.0, "breadth_discounted": 30},
        }
    """
    result: dict[str, dict] = {}

    # 1. 过滤噪音标签，收集有效标签
    valid_labels: list[str] = []
    for raw in (raw_concepts or []):
        if not raw or is_ignored(raw):
            continue
        valid_labels.append(raw)

    # 2. 标签 → 叙事映射
    narrative_labels: dict[str, list[str]] = {}
    for raw in valid_labels:
        name = canonical_name(raw)
        if name is None:
            continue
        if name not in narrative_labels:
            narrative_labels[name] = []
        narrative_labels[name].append(raw)

    # 3. 派生概念
    # 规则关键词和标签都归一化后再比较，避免 "算力概念" vs "算力" 不匹配
    upper_labels = {_normalize_label(l).upper() for l in valid_labels}
    for rule in _DERIVED_RULES:
        norm_requires = {_normalize_label(r).upper() for r in rule["requires"]}
        norm_also = {_normalize_label(a).upper() for a in rule["also_require_one"]}
        requires_met = norm_requires.issubset(upper_labels)
        also_met = bool(norm_also & upper_labels)
        if requires_met and also_met:
            result_name = rule["result"]
            if result_name not in narrative_labels:
                narrative_labels[result_name] = []
            # 加入触发标签作为证据
            for r in rule["requires"]:
                for raw in valid_labels:
                    if _normalize_label(raw).upper() == r.upper():
                        if raw not in narrative_labels[result_name]:
                            narrative_labels[result_name].append(raw)

    # 4. 计算得分
    for name, labels in narrative_labels.items():
        score = evidence_score(name, labels)
        discount = breadth_discount(name)
        result[name] = {
            "score": score,
            "labels": labels,
            "count": len(labels),
            "discount": discount,
            "breadth_discounted": round(score * discount, 1),
        }

    return result


def rank_narratives(raw_concepts: list[str], min_score: float = 20) -> list[dict]:
    """归一化并按得分排序返回叙事列表

    Args:
        raw_concepts: 东财原始概念标签
        min_score: 最低广度折扣后得分

    Returns:
        排序后的叙事列表，每项 { name, score, labels, breadth_discounted }
    """
    mapped = normalize_concepts(raw_concepts)
    ranked = []
    for name, info in mapped.items():
        if info["breadth_discounted"] >= min_score:
            ranked.append({
                "name": name,
                "score": info["score"],
                "labels": info["labels"],
                "count": info["count"],
                "discount": info["discount"],
                "breadth_discounted": info["breadth_discounted"],
            })
    ranked.sort(key=lambda x: x["breadth_discounted"], reverse=True)
    return ranked


def enhance_stock_boards(boards: dict) -> dict:
    """增强 get_stock_boards 返回值，追加归一化叙事

    Args:
        boards: get_stock_boards() 返回的原始数据

    Returns:
        增强后的数据，追加 "narratives" 字段
    """
    concepts = boards.get("concepts") or []
    concept_names = [c.get("name", "") for c in concepts if c.get("name")]
    narratives = rank_narratives(concept_names)
    boards["narratives"] = narratives
    boards["narrative_count"] = len(narratives)
    return boards


def cross_stock_narratives(stocks: list[dict]) -> dict:
    """跨股票叙事分析 — 找出组合中共同关注的叙事

    Args:
        stocks: [{"code": "600519", "concepts": ["白酒", ...]}, ...]

    Returns:
        {
            "shared_narratives": [{"name": ..., "stocks": [...], "avg_score": ...}],
            "unique_narratives": [{"name": ..., "code": ...}],
        }
    """
    # 收集每只股票的叙事
    stock_narratives: dict[str, dict[str, dict]] = {}
    for stock in stocks:
        code = stock.get("code", "")
        concepts = stock.get("concepts") or []
        if isinstance(concepts[0] if concepts else None, dict):
            names = [c.get("name", "") for c in concepts if c.get("name")]
        else:
            names = [str(c) for c in concepts]
        stock_narratives[code] = {
            n["name"]: n for n in rank_narratives(names, min_score=10)
        }

    # 统计每个叙事出现在几只股票中
    narrative_stocks: dict[str, list[tuple[str, float]]] = {}
    for code, nars in stock_narratives.items():
        for name, info in nars.items():
            if name not in narrative_stocks:
                narrative_stocks[name] = []
            narrative_stocks[name].append((code, info["breadth_discounted"]))

    shared = []
    unique = []
    for name, stock_list in narrative_stocks.items():
        avg_score = round(sum(s for _, s in stock_list) / len(stock_list), 1)
        entry = {
            "name": name,
            "stocks": [code for code, _ in stock_list],
            "stock_count": len(stock_list),
            "avg_score": avg_score,
        }
        if len(stock_list) > 1:
            shared.append(entry)
        else:
            unique.append({"name": name, "code": stock_list[0][0]})

    shared.sort(key=lambda x: x["avg_score"], reverse=True)
    return {"shared_narratives": shared, "unique_narratives": unique}


# ─── 便捷函数：从东财 API 获取并归一化 ────────────────────────
def boards_with_narratives(code: str) -> dict:
    """获取个股板块并归一化叙事

    Args:
        code: 股票代码

    Returns:
        get_stock_boards 结果 + narratives 字段
    """
    try:
        from data_sources.em_market import get_stock_boards
        boards = get_stock_boards(code)
        return enhance_stock_boards(boards)
    except Exception as e:
        return {"code": code, "error": str(e), "narratives": []}
