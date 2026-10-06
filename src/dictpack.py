# -*- coding: utf-8 -*-
"""词典包: 下载、校验、解包、建索引。一处实现, 两个入口。

入口:
  - scripts/fetch_dict.py / scripts/build_index.py: 命令行版（开发时用）
  - src/setup_wizard.py: 第一次运行时的图形向导（给普通用户用）

以前这套逻辑只写在 fetch_dict.py 里, 向导要用就得抄一份; 抽出来是为了不让
两份实现慢慢跑偏 —— 校验值、镜像地址这种一旦对不上, 结果就是"下到半个坏词典"。
"""
from __future__ import annotations

import hashlib
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

import paths

ARCHIVE_NAME = "ecdict-ecdict-bc015ed2-focus13-v2.zip"
ARCHIVE_SHA256 = "1e745ea698878772226a7df584129409dd4b27cb7ea26b4259bc770e7533352f"
ARCHIVE_SIZE = 54_594_964
DB_NAME = "ecdict.sqlite"
DB_SIZE = 131_756_032
DB_SOURCE_SHA256 = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"

MIRRORS = (
    "https://hf-mirror.com/datasets/iamzhangship/fluency-ecdict-offline/resolve/main/"
    + ARCHIVE_NAME,
    "https://huggingface.co/datasets/iamzhangship/fluency-ecdict-offline/resolve/main/"
    + ARCHIVE_NAME,
)

# 词形索引里这些码代表"该词条的其他书写形式", 都当别名收进来
ALIAS_CODES = ("p", "d", "i", "3", "r", "t", "s", "0")

CHUNK = 1024 * 256


class Cancelled(Exception):
    """用户按了取消。"""


def data_dir():
    """词典装哪儿: 用户数据目录, 不是程序目录（打包后那儿是只读的）。"""
    return paths.data_root() / "data"


def _tick(callback, stage, done, total):
    if callback:
        callback(stage, done, total)


def sha256_of(path, stage="verify", on_progress=None, should_stop=None):
    """算文件哈希。中途也回报进度, 不然 52 MB 校验会像卡住。"""
    digest = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if should_stop and should_stop():
                raise Cancelled()
            digest.update(chunk)
            done += len(chunk)
            _tick(on_progress, stage, done, total)
    return digest.hexdigest()


def verify_db(db_path):
    """确认这份库就是我们要的那一份。返回 (通过?, 说明)。"""
    db_path = Path(db_path)
    try:
        size = db_path.stat().st_size
    except OSError as exc:
        return False, "读不到文件：%s" % exc
    if size != DB_SIZE:
        return False, "数据库大小不符：%d != %d" % (size, DB_SIZE)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True)
        try:
            row = conn.execute(
                "select source_sha256, entry_count from dictionary_meta").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, "打不开数据库：%s" % exc
    if not row:
        return False, "读不到 dictionary_meta"
    if row[0] != DB_SOURCE_SHA256:
        return False, "来源校验值不符"
    return True, "词条 %s 条，来源校验值一致" % format(row[1], ",")


def find_existing_db(project_root):
    """新家和程序目录都找一遍, 有能用的就直接用。"""
    for folder in (data_dir(), Path(project_root) / "data"):
        candidate = folder / DB_NAME
        if candidate.exists() and candidate.stat().st_size == DB_SIZE:
            ok, _ = verify_db(candidate)
            if ok:
                return candidate
    return None


def download(url, target, on_progress=None, should_stop=None):
    """先下到 .part 再改名: 中途断了不会留下一个"看起来是完整的"文件。"""
    target = Path(target)
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with tmp.open("wb") as out:
                while True:
                    if should_stop and should_stop():
                        raise Cancelled()
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    _tick(on_progress, "download", done, total)
        if should_stop and should_stop():
            raise Cancelled()
        tmp.replace(target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return target


def _archive_ready(archive, on_progress=None, should_stop=None):
    """本地这个下载包还能不能用（大小 + 哈希都对）。"""
    archive = Path(archive)
    if not archive.exists() or archive.stat().st_size != ARCHIVE_SIZE:
        return False
    return sha256_of(archive, on_progress=on_progress,
                     should_stop=should_stop) == ARCHIVE_SHA256


def ensure_dictionary(project_root, on_progress=None, should_stop=None):
    """确保词典可用。返回 (ecdict.sqlite 路径, 说明)。

    已经有的直接用；没有就下载 -> 校验 -> 解包 -> 再校验一遍。
    出错抛异常（RuntimeError / Cancelled），说明写在异常信息里。

    on_progress(stage, done, total) 的 stage 取值:
        check / download / verify / unzip
    """
    target_dir = data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / ARCHIVE_NAME
    db_path = target_dir / DB_NAME

    _tick(on_progress, "check", 0, 1)
    existing = find_existing_db(project_root)
    if existing:
        _tick(on_progress, "check", 1, 1)
        return existing, "已有词典，直接用"

    # 老位置留着的下载包就复用, 省一次 52 MB
    if not archive.exists():
        for folder in (target_dir, Path(project_root) / "data"):
            candidate = folder / ARCHIVE_NAME
            if candidate.exists() and candidate.stat().st_size == ARCHIVE_SIZE:
                archive = candidate
                break

    if not _archive_ready(archive, on_progress, should_stop):
        archive = target_dir / ARCHIVE_NAME
        last_error = None
        for url in MIRRORS:
            try:
                download(url, archive, on_progress, should_stop)
                got = sha256_of(archive, on_progress=on_progress,
                                should_stop=should_stop)
                if got != ARCHIVE_SHA256:
                    raise ValueError("下载包的 SHA-256 对不上")
                last_error = None
                break
            except Cancelled:
                raise
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise RuntimeError("下载失败：%s" % last_error)

    _tick(on_progress, "unzip", 0, 1)
    with zipfile.ZipFile(archive) as bundle:
        name = DB_NAME
        if name not in bundle.namelist():
            candidates = [n for n in bundle.namelist() if n.endswith(".sqlite")]
            if not candidates:
                raise RuntimeError("压缩包里没有 .sqlite 文件")
            name = candidates[0]
        with bundle.open(name) as src, db_path.open("wb") as dst:
            while True:
                if should_stop and should_stop():
                    raise Cancelled()
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
    _tick(on_progress, "unzip", 1, 1)

    ok, note = verify_db(db_path)
    if not ok:
        try:
            db_path.unlink()
        except OSError:
            pass
        raise RuntimeError("解出来的词典不对：%s" % note)
    return db_path, note


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


def build_index(source_db, on_progress=None, should_stop=None):
    """从 entries.exchange 翻出"变形 -> 原形"的索引, 写在词典旁边。

    返回 (索引路径, 变形条数)。
    """
    source_db = Path(source_db)
    index_db = source_db.parent / "inflection.sqlite"

    _tick(on_progress, "index", 0, 0)
    src = sqlite3.connect("file:%s?mode=ro" % source_db.as_posix(), uri=True)
    try:
        rows = src.execute("select word, frq, bnc, exchange from entries").fetchall()
    finally:
        src.close()
    if should_stop and should_stop():
        raise Cancelled()

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
    if should_stop and should_stop():
        raise Cancelled()

    if index_db.exists():
        index_db.unlink()
    out = sqlite3.connect(index_db)
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
    _tick(on_progress, "index", 1, 1)
    return index_db, len(forms)
