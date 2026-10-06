# -*- coding: utf-8 -*-
"""从 entries.exchange 构建词形还原索引。

ECDICT 只在每个词条上记录"它自己的各种变形"，没有反向索引。
这里把它翻转成 变形 -> 原形 的表，用于 ran -> run、studies -> study 这类查询。

输出: 词典旁边的 inflection.sqlite  (表 forms(form PRIMARY KEY, word))
      词典在 %APPDATA%\\选中即查\\data 或程序目录的 data\\ 下, 索引写在它旁边。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import paths  # noqa: E402


def find_source_db():
    """词典在哪就用哪份: 先用户数据目录, 再程序目录。"""
    for folder in (paths.data_root() / "data", ROOT / "data"):
        candidate = folder / "ecdict.sqlite"
        if candidate.exists():
            return candidate
    return paths.data_root() / "data" / "ecdict.sqlite"


# 索引跟着词典走: 词典在哪, 索引就写在它旁边。
SOURCE_DB = find_source_db()
INDEX_DB = SOURCE_DB.parent / "inflection.sqlite"

# 这些码代表"该词条的其他书写形式"，都当作别名收进来
ALIAS_CODES = ("p", "d", "i", "3", "r", "t", "s", "0")


def parse_exchange(exchange):
    """把 p:ran/i:running/3:runs 解析成 [ran, running, runs]。"""
    if not exchange:
        return []
    forms = []
    for part in exchange.split("/"):
        if ":" not in part:
            continue
        code, _, value = part.partition(":")
        if code not in ALIAS_CODES:
            continue
        value = value.strip()
        if value and value.isascii():
            forms.append(value.lower())
    return forms


def rank_of(frq, bnc):
    """词频排名，数值越小越常见；0/空 表示没有数据，排到最后。"""
    values = [v for v in (frq, bnc) if v and v > 0]
    return min(values) if values else 10 ** 9


def main():
    if not SOURCE_DB.exists():
        print("找不到词库: %s" % SOURCE_DB)
        print("先运行: python scripts/fetch_dict.py")
        return 1

    started = time.time()
    print("读取词库 ...")
    src = sqlite3.connect("file:%s?mode=ro" % SOURCE_DB.as_posix(), uri=True)
    try:
        rows = src.execute("select word, frq, bnc, exchange from entries").fetchall()
    finally:
        src.close()
    print("  词条 %s 条，用时 %.1fs" % (format(len(rows), ","), time.time() - started))

    print("翻转索引 ...")
    # 词频高的先写入，后面用 setdefault 就自然保留最常见的那个解释
    rows.sort(key=lambda r: rank_of(r[1], r[2]))
    forms = {}
    for word, _frq, _bnc, exchange in rows:
        word = (word or "").strip()
        if not word:
            continue
        lower = word.lower()
        for form in parse_exchange(exchange):
            if form == lower:
                continue
            forms.setdefault(form, word)
    print("  唯一变形 %s 个，用时 %.1fs" % (format(len(forms), ","), time.time() - started))

    print("写入 ...")
    if INDEX_DB.exists():
        INDEX_DB.unlink()
    out = sqlite3.connect(INDEX_DB)
    try:
        out.execute("pragma journal_mode = off")
        out.execute("pragma synchronous = off")
        out.execute("create table forms(form text primary key, word text not null)")
        out.execute("create table index_meta(schema_version integer, built_at text)")
        out.executemany("insert into forms(form, word) values(?, ?)", forms.items())
        out.execute("insert into index_meta values(1, datetime('now'))")
        out.commit()
    finally:
        out.close()

    size_mb = INDEX_DB.stat().st_size / 1048576
    print("完成: %s  (%.1f MB)" % (INDEX_DB, size_mb))
    print("总用时 %.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
