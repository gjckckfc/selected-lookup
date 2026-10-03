# -*- coding: utf-8 -*-
"""ECDICT 查询层。

查询顺序（先精确、后兜底）:
  1. 整串精确命中        aggregate demand -> [经] 总需求
  2. 词形还原兜底        ran -> run
  3. 逐词拆解            fiscal multiplier -> fiscal + multiplier

只读打开词库，不写任何文件。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# 逐词拆解时跳过这些功能词, 免得弹出结果里全是 "the / of / is"
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "that", "this", "these",
    "those", "it", "its", "as", "by", "with", "from", "which", "who", "whom",
    "whose", "if", "then", "than", "so", "such", "not", "no", "do", "does",
    "did", "has", "have", "had", "will", "would", "shall", "should", "can",
    "could", "may", "might", "must", "there", "here", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "only", "own", "same", "too", "very", "just", "we", "you", "they",
    "he", "she", "his", "her", "their", "our", "your", "my", "me", "him",
    "them", "us", "one", "two", "up", "out", "about", "into", "over", "after",
}

# entries.tag 里的缩写
TAG_NAMES = {
    "zk": "中考",
    "gk": "高考",
    "cet4": "四级",
    "cet6": "六级",
    "ky": "考研",
    "toefl": "托福",
    "ielts": "雅思",
    "gre": "GRE",
    "tem4": "专四",
    "tem8": "专八",
}


def _ro_uri(path: Path) -> str:
    return "file:%s?mode=ro" % path.as_posix().replace("?", "%3f").replace("#", "%23")


def _lines(text):
    """ECDICT 里的换行是字面量 \\n，统一还原成真换行。"""
    if not text:
        return []
    return [ln.strip() for ln in text.replace("\\n", "\n").splitlines() if ln.strip()]


@dataclass
class Entry:
    word: str
    phonetic: str = ""
    translation: list = field(default_factory=list)
    definition: list = field(default_factory=list)
    pos: str = ""
    tags: list = field(default_factory=list)
    collins: int = 0
    oxford: bool = False
    bnc: int = 0
    frq: int = 0
    exchange: str = ""

    @property
    def is_common(self) -> bool:
        return self.collins >= 3 or self.oxford


@dataclass
class Result:
    kind: str                      # word | phrase | breakdown | miss
    query: str
    entry: Entry | None = None
    matched_form: str = ""         # 通过词形还原命中时，用户实际选中的形式
    parts: list = field(default_factory=list)


class Dictionary:
    def __init__(self, db_path, index_path=None):
        self.db_path = Path(db_path)
        self.index_path = Path(index_path) if index_path else None
        if not self.db_path.exists():
            raise FileNotFoundError("找不到词库: %s" % self.db_path)
        self.conn = sqlite3.connect(_ro_uri(self.db_path), uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.index = None
        if self.index_path and self.index_path.exists():
            self.index = sqlite3.connect(_ro_uri(self.index_path), uri=True, check_same_thread=False)
            self.index.row_factory = sqlite3.Row

    # ---------- 基础查询 ----------

    def _entry_by_word(self, word):
        row = self.conn.execute("select * from entries where word = ?", (word,)).fetchone()
        return self._to_entry(row) if row else None

    def _to_entry(self, row):
        return Entry(
            word=row["word"],
            phonetic=row["phonetic"] or "",
            translation=_lines(row["translation"]),
            definition=_lines(row["definition"]),
            pos=row["pos"] or "",
            tags=[TAG_NAMES.get(t, t) for t in (row["tag"] or "").split()],
            collins=row["collins"] or 0,
            oxford=bool(row["oxford"]),
            bnc=row["bnc"] or 0,
            frq=row["frq"] or 0,
            exchange=row["exchange"] or "",
        )

    def _lemma_of(self, form):
        if not self.index:
            return None
        row = self.index.execute("select word from forms where form = ?", (form,)).fetchone()
        return row["word"] if row else None

    # ---------- 对外接口 ----------

    def lookup(self, text):
        text = (text or "").strip()
        if not text:
            return Result(kind="miss", query=text)
        collapsed = " ".join(text.split())
        lower = collapsed.lower()

        # 1) 整串精确命中（含短语）
        entry = self._entry_by_word(lower)
        if entry:
            kind = "phrase" if " " in collapsed else "word"
            return Result(kind=kind, query=collapsed, entry=entry)

        tokens = TOKEN_RE.findall(collapsed)
        if not tokens:
            return Result(kind="miss", query=collapsed)

        # 2) 单个词 -> 词形还原
        if len(tokens) == 1:
            lemma = self._lemma_of(tokens[0].lower())
            if lemma:
                entry = self._entry_by_word(lemma)
                if entry:
                    return Result(kind="word", query=collapsed, entry=entry,
                                  matched_form=tokens[0])
            return Result(kind="miss", query=collapsed)

        # 3) 多词短语：逐词拆解（最多 6 个词，去重）
        content_words = [t for t in tokens if t.lower() not in STOPWORDS]
        if not content_words:
            content_words = tokens
        content_words = content_words[:6]

        seen = set()
        parts = []
        for token in content_words:
            low = token.lower()
            if low in seen:
                continue
            seen.add(low)
            part = self._entry_by_word(low)
            matched = ""
            if not part:
                lemma = self._lemma_of(low)
                if lemma:
                    part = self._entry_by_word(lemma)
                    matched = low
            if part:
                parts.append((part, matched, low))

        if parts:
            return Result(kind="breakdown", query=collapsed, parts=parts)
        return Result(kind="miss", query=collapsed)

    def stats(self):
        row = self.conn.execute("select entry_count from dictionary_meta").fetchone()
        forms = 0
        if self.index:
            forms = self.index.execute("select count(*) as n from forms").fetchone()["n"]
        return {"entries": row["entry_count"] if row else 0, "forms": forms}

    def close(self):
        self.conn.close()
        if self.index:
            self.index.close()
