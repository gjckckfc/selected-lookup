# -*- coding: utf-8 -*-
"""生词本: 把查过的内容自动沉淀成本地 Markdown。

只写项目内的 vocabulary/ 目录, 不联网, 不花 token。

布局:
    vocabulary/
      README.md              格式说明(给人和 AI 看)
      raw/2026-10-05.md      原稿: 按天一个文件, 选中即自动追加

收录规则:
  - 单词 / 短语 -> 整条词条(音标、词性、释义、变形、标签)
  - 句子 / 段落 -> 原文 + 译文(开了整句翻译才有) + 逐词释义
  - 同一个标题只写一次, 再遇到只更新 last_seen / lookups
  - 三条防脏门槛: 没有可用内容不写; 不含英文字母(纯中文)不写; 超长截断

写入只从主线程调用(app 的结果队列保证), 这里再加一把锁兜底。
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

MAX_SOURCE_CHARS = 400      # 原文/来源句上限
MAX_TITLE_CHARS = 48        # 句子类条目的标题上限
MAX_GLOSS_PARTS = 6         # 逐词释义最多几条
MAX_GLOSS_CHARS = 36        # 每条逐词释义上限

ASCII_RE = re.compile(r"[A-Za-z]")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+([a-z_]+):\s*(.*)$")

EXCHANGE_NAMES = {
    "p": "过去式", "d": "过去分词", "i": "现在分词",
    "3": "三单", "r": "比较级", "t": "最高级", "s": "复数",
}


def _collapse(text, limit=None):
    """把多行/多空格压成一行; 超过 limit 就截断并留省略号。"""
    text = " ".join((text or "").split())
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return text


def _stamp():
    return time.strftime("%Y-%m-%d %H:%M")


def _forms_note(exchange):
    """跟浮窗一样的变形说明: 复数 inflations / 过去式 went。"""
    bits = []
    for part in (exchange or "").split("/"):
        code, _, value = part.partition(":")
        if code in EXCHANGE_NAMES and value:
            bits.append("%s %s" % (EXCHANGE_NAMES[code], value))
    return "  ".join(bits[:4])


class Notebook:
    def __init__(self, root, logger=None, enabled=True):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.log = logger or (lambda message: None)
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._index = None          # {标题小写: 所在文件}

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------

    @property
    def folder(self):
        return self.root

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def ensure_folder(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return self.root

    def refresh(self):
        """外部增删过文件后调用, 让索引重建。"""
        self._index = None

    def record(self, result, translation=None, count=True):
        """把一次查询沉淀进当天的原稿。返回是否写入了内容。"""
        if not self.enabled:
            return False
        entry = self._compose(result, translation)
        if entry is None:
            return False
        try:
            with self._lock:
                self._write(entry, count=count)
        except OSError as exc:
            self.log("生词本写入失败: %s" % exc)
            return False
        return True

    def stats(self):
        files = 0
        entries = 0
        if self.raw_dir.exists():
            for path in sorted(self.raw_dir.glob("*.md")):
                files += 1
                for line in self._read(path).split("\n"):
                    if HEADING_RE.match(line):
                        entries += 1
        return {"files": files, "entries": entries}

    # ------------------------------------------------------------------
    # 组装条目
    # ------------------------------------------------------------------

    def _compose(self, result, translation):
        query = _collapse(getattr(result, "query", ""))
        if not ASCII_RE.search(query):
            return None                      # 纯中文/纯符号, 不收
        now = _stamp()
        entry = getattr(result, "entry", None)
        kind = getattr(result, "kind", "miss")

        if kind in ("word", "phrase") and entry is not None:
            fields = [("type", kind)]
            if entry.phonetic:
                fields.append(("phonetic", "/%s/" % entry.phonetic.strip("/")))
            if entry.pos:
                fields.append(("pos", entry.pos))
            body = (entry.translation or entry.definition)[:3]
            if body:
                fields.append(("meaning", " ｜ ".join(body)))
            note = _forms_note(entry.exchange)
            if note:
                fields.append(("forms", note))
            marks = []
            if entry.tags:
                marks.append("、".join(entry.tags))
            if entry.collins:
                marks.append("柯林斯 %d 星" % entry.collins)
            if entry.oxford:
                marks.append("牛津核心")
            if marks:
                fields.append(("tags", " · ".join(marks)))
            matched = getattr(result, "matched_form", "")
            if matched and matched.lower() != entry.word.lower():
                fields.append(("seen_as", matched))
            title = entry.word
        else:
            parts = list(getattr(result, "parts", []) or [])
            if not translation and not parts:
                return None                  # 查不到又没有译文, 没什么可留的
            fields = [("type", "sentence")]
            if translation:
                fields.append(("translation", _collapse(translation)))
            gloss = []
            # 生词本按原文顺序记(不跟浮窗的排序设置走): raw 是事实层,
            # 同一句话不管什么时候查、设置怎么改, 记下来的样子都一样。
            for part in parts[:MAX_GLOSS_PARTS]:
                lines = part.entry.translation or part.entry.definition
                if not lines:
                    continue
                gloss.append("%s %s" % (part.token,
                                        _collapse(lines[0], MAX_GLOSS_CHARS)))
            if gloss:
                fields.append(("gloss", "; ".join(gloss)))
            source = _collapse(query, MAX_SOURCE_CHARS)
            title = _collapse(query, MAX_TITLE_CHARS)
            if source and source != title:
                fields.append(("source", source))

        return {
            "title": title,
            "fields": fields,
            "first_seen": now,
            "last_seen": now,
            "lookups": 1,
        }

    @staticmethod
    def _render_block(entry):
        lines = ["## %s" % entry["title"]]
        for name, value in entry["fields"]:
            lines.append("- %s: %s" % (name, value))
        lines.append("- first_seen: %s" % entry["first_seen"])
        lines.append("- last_seen: %s" % entry["last_seen"])
        lines.append("- lookups: %d" % entry["lookups"])
        return lines

    # ------------------------------------------------------------------
    # 落盘
    # ------------------------------------------------------------------

    def _write(self, entry, count):
        key = entry["title"].strip().lower()
        self._ensure_index()
        path = self._index.get(key)
        if path is not None and path.exists():
            lines = self._read(path).split("\n")
            if self._merge_block(lines, entry, count):
                self._write_text(path, "\n".join(lines))
                return

        # 新条目(或索引失效): 追加到当天文件
        path = self._today_path()
        text = self._read(path)
        if not text:
            text = self._daily_header()
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + "\n".join(self._render_block(entry)) + "\n"
        self._write_text(path, text)
        self._index[key] = path

    def _merge_block(self, lines, entry, count):
        """在已有文件里就地更新条目。返回 False 表示没找到那块。"""
        target = entry["title"].strip().lower()
        start = None
        for index, line in enumerate(lines):
            match = HEADING_RE.match(line)
            if match and match.group(1).strip().lower() == target:
                start = index
                break
        if start is None:
            return False

        end = len(lines)
        for index in range(start + 1, len(lines)):
            if HEADING_RE.match(lines[index]):
                end = index
                break

        found = {}
        for index in range(start + 1, end):
            match = FIELD_RE.match(lines[index])
            if match:
                found.setdefault(match.group(1), index)

        if "last_seen" in found:
            lines[found["last_seen"]] = "- last_seen: %s" % entry["last_seen"]
        if "lookups" in found:
            match = FIELD_RE.match(lines[found["lookups"]])
            try:
                old = int(match.group(2))
            except (AttributeError, ValueError):
                old = 0
            lines[found["lookups"]] = "- lookups: %d" % (old + (1 if count else 0))

        # 补齐新字段(比如译文后到), 插在统计行之前
        additions = ["- %s: %s" % (name, value) for name, value in entry["fields"]
                     if name not in found]
        anchors = [found[name] for name in ("first_seen", "last_seen", "lookups")
                   if name in found]
        if additions:
            anchor = min(anchors) if anchors else end
            lines[anchor:anchor] = additions
        return True

    # ------------------------------------------------------------------
    # 文件
    # ------------------------------------------------------------------

    def _ensure_index(self):
        if self._index is not None:
            return
        index = {}
        if self.raw_dir.exists():
            # 早的文件先入索引: 同一个词保留它第一次出现的那天
            for path in sorted(self.raw_dir.glob("*.md")):
                for line in self._read(path).split("\n"):
                    match = HEADING_RE.match(line)
                    if match:
                        index.setdefault(match.group(1).strip().lower(), path)
        self._index = index

    def _today_path(self):
        return self.raw_dir / (time.strftime("%Y-%m-%d") + ".md")

    @staticmethod
    def _daily_header():
        return ("# %s\n\n<!-- vocabulary · raw · auto-collected by 选中即查 -->\n"
                % time.strftime("%Y-%m-%d"))

    @staticmethod
    def _read(path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _write_text(path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
