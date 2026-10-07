# -*- coding: utf-8 -*-
"""词条难度打分: 浮窗里逐词释义"生词优先"排序时用。

判据全部来自 ECDICT 自带的字段, 纯本地、零依赖、不联网:
  collins  柯林斯星级(1-5), 越高越常用
  oxford   牛津核心词表, 命中就是基础词
  tags     考纲标签(中考/高考/四级/六级/考研/托福/雅思/GRE/专四/专八)
  bnc/frq  词频序号, 越小越常用; 0 表示没有这个数据

分数 0.0(最基础) ~ 5.0(最生僻), 越大越难。缺哪项证据就把它的权重让给别的项,
所以只有标签没有词频的词也能排, 只是分得更粗。

**判断不了的情况不硬猜**: 变形词(planned/governments)自己不常有词频数据,
要不要拿词形还原后的词来补, 由 dictionary 层决定(它才拿得到词形索引)。
"""
from __future__ import annotations

FREQ_BUCKETS = ((1000, 0.0), (3000, 1.0), (8000, 2.0),
                (15000, 3.0), (25000, 4.0))
FREQ_RARE = 5.0

# 考纲标签 -> 难度档: 按"学生什么时候学过它"排
TAG_LEVELS = {
    "中考": 0.0, "高考": 0.0,
    "四级": 1.0,
    "六级": 3.0, "考研": 3.0, "专四": 3.0,
    "托福": 4.0, "雅思": 4.0, "GRE": 4.0, "专八": 4.0,
}

WEIGHT_FREQ = 0.5
WEIGHT_COLLINS = 0.3
WEIGHT_TAG = 0.2

# 一点证据都没有时按"一般"处理, 不硬说它是生词
UNKNOWN = 2.0

# 显示顺序: 生词优先(默认) / 原文顺序 / 基础词优先
ORDERS = ("hard", "text", "easy")
DEFAULT_ORDER = "hard"


def has_freq_evidence(entry):
    """有没有"词频/星级"这类硬证据。

    考纲标签不算: 它是打在词条上的, 变形词(governments)也常带着, 单独用它排序不准。
    """
    return bool(entry.oxford or entry.collins or entry.bnc or entry.frq)


def _freq_level(entry):
    ranks = [rank for rank in (entry.bnc, entry.frq) if rank > 0]
    if not ranks:
        return None
    rank = min(ranks)
    for limit, level in FREQ_BUCKETS:
        if rank <= limit:
            return level
    return FREQ_RARE


def _collins_level(entry):
    if entry.oxford or entry.collins >= 4:
        return 0.0
    if entry.collins == 3:
        return 1.0
    if entry.collins == 2:
        return 3.0
    if entry.collins == 1:
        return 4.0
    return None


def _tag_level(entry):
    """取最容易的那个标签: 高考词就算还挂着 GRE 标签, 它也是基础词。"""
    levels = [TAG_LEVELS[tag] for tag in entry.tags if tag in TAG_LEVELS]
    return min(levels) if levels else None


def score(entry):
    """一个词条有多难: 0.0(最基础) ~ 5.0(最生僻)。"""
    evidence = ((_freq_level(entry), WEIGHT_FREQ),
                (_collins_level(entry), WEIGHT_COLLINS),
                (_tag_level(entry), WEIGHT_TAG))
    total = 0.0
    weight = 0.0
    for level, weigh in evidence:
        if level is None:
            continue
        total += level * weigh
        weight += weigh
    if not weight:
        return UNKNOWN
    return total / weight


def order(parts, mode=DEFAULT_ORDER):
    """把逐词释义排成显示顺序; 分数相同的保持原文顺序(sorted 是稳定的)。"""
    if mode == "text":
        return list(parts)
    return sorted(parts, key=lambda part: part.score, reverse=(mode != "easy"))
