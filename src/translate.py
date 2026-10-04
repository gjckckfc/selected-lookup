# -*- coding: utf-8 -*-
"""整句翻译: 只发原文, 只收译文。

设计约束（按需求定的）:
  - 只用标准库 urllib, 不引入第三方依赖, 内存增量几乎为零
  - 走 OpenAI 兼容协议, 一个接口通吃 DeepSeek / 通义 / 硅基流动 / Kimi / 智谱
  - 系统提示词锁死"只输出译文"; temperature = 0
  - 尝试关掉推理模型的思考模式(enable_thinking), 服务商不认就自动去掉重试
  - 结果本地缓存, 同一句只翻一次, 反复选中同一段是零成本
  - 只发原文, 不带词典释义（实测带词典是 7.6 倍 token）
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request

TARGET_LANGUAGE = "简体中文"

# 目前只接 DeepSeek: 便宜, 而且翻译是个很基础的功能, 不值得为它引入更贵的服务。
# 以后要加别家, 在这里加一张 "服务商 -> 地址" 的表, 让用户选即可。
PROVIDER_NAME = "DeepSeek"
PROVIDER_BASE = "https://api.deepseek.com/v1"

SYSTEM_PROMPT = (
    "你是一个翻译引擎。把用户给出的英文翻译成%s。"
    "只输出译文本身：不要解释、不要复述原文、不要加引号或代码块、不要寒暄。"
    "专业术语要用准确的中文译法，例如 aggregate demand 译为「总需求」。"
) % TARGET_LANGUAGE

MAX_INPUT_CHARS = 400        # 超过就截断, 防止一次误选烧掉一大笔
REQUEST_TIMEOUT = 20
FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
PREFIX_RE = re.compile(r"^\s*(翻译|译文|中文翻译)\s*[:：]\s*")


def clean_output(text):
    """把模型可能多给的东西去掉。"""
    if not text:
        return ""
    text = FENCE_RE.sub("", text).strip()
    text = PREFIX_RE.sub("", text).strip()
    return text.strip().strip('"').strip("“”").strip()


class Translator:
    def __init__(self, cache_path=None, logger=None):
        self.log = logger or (lambda message: None)
        self.base_url = PROVIDER_BASE
        self.api_key = ""
        self.model = ""
        self._cache = None
        self._lock = None
        if cache_path is not None:
            try:
                self._cache = sqlite3.connect(str(cache_path), check_same_thread=False)
                self._cache.execute(
                    "create table if not exists cache("
                    "key text primary key, source text, target text, created text)")
                self._cache.commit()
            except sqlite3.Error as exc:
                self.log("翻译缓存打开失败: %s" % exc)
                self._cache = None

    # ------------------------------------------------------------------

    def configure(self, api_key="", model=""):
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()

    @property
    def available(self):
        return bool(self.base_url and self.api_key and self.model)

    def endpoint(self):
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    # ------------------------------------------------------------------
    # 缓存

    def _cache_key(self, text):
        raw = "%s\x00%s\x00%s" % (self.model, TARGET_LANGUAGE, text)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def cache_get(self, text):
        if self._cache is None:
            return None
        try:
            row = self._cache.execute(
                "select target from cache where key = ?", (self._cache_key(text),)).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    def cache_put(self, text, target):
        if self._cache is None or not target:
            return
        try:
            self._cache.execute(
                "insert or replace into cache(key, source, target, created) "
                "values(?, ?, ?, datetime('now'))",
                (self._cache_key(text), text, target))
            self._cache.commit()
        except sqlite3.Error as exc:
            self.log("翻译缓存写入失败: %s" % exc)

    def cache_count(self):
        if self._cache is None:
            return 0
        try:
            return self._cache.execute("select count(*) from cache").fetchone()[0]
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------

    def _post(self, body):
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint(), data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.api_key,
                "User-Agent": "lookup-plugin/1.0",
            })
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def translate(self, text):
        """同步翻译。返回译文, 失败返回 None。"""
        if not self.available:
            return None
        text = text.strip()
        if not text:
            return None
        if len(text) > MAX_INPUT_CHARS:
            text = text[:MAX_INPUT_CHARS]

        cached = self.cache_get(text)
        if cached:
            self.log("翻译命中缓存")
            return cached

        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max(96, min(len(text), 800)),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        started = time.perf_counter()
        try:
            try:
                # 先试着关掉推理模型的思考模式: 那些思考 token 也是要计费的
                data = self._post(dict(payload, enable_thinking=False))
            except urllib.error.HTTPError as exc:
                if exc.code != 400:
                    raise
                # 服务商不认这个字段, 去掉再来一次
                self.log("服务商不接受 enable_thinking, 已回落")
                data = self._post(payload)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            self.log("翻译失败 HTTP %s %s" % (exc.code, detail))
            return None
        except Exception as exc:
            self.log("翻译失败: %s" % exc)
            return None

        cost = (time.perf_counter() - started) * 1000
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.log("翻译返回结构异常: %s" % str(data)[:200])
            return None
        target = clean_output(content)
        if not target:
            return None
        self.log("翻译完成 %.0fms  %d 字 -> %d 字" % (cost, len(text), len(target)))
        self.cache_put(text, target)
        return target

    def test(self):
        """测试连接。返回 (是否成功, 说明)。"""
        if not self.available:
            return False, "接口地址、密钥、模型名都要填"
        started = time.perf_counter()
        try:
            result = self.translate("The demand curve slopes downward.")
        except Exception as exc:
            return False, str(exc)
        cost = (time.perf_counter() - started) * 1000
        if result is None:
            return False, "连接失败，具体原因见 logs/app.log"
        return True, "成功（%.0f ms）：%s" % (cost, result[:60])

    def close(self):
        if self._cache is not None:
            try:
                self._cache.close()
            except sqlite3.Error:
                pass
            self._cache = None
