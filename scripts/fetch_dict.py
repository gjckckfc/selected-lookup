# -*- coding: utf-8 -*-
"""下载并校验 ECDICT 词典包。

用法:
    python scripts/fetch_dict.py

校验通过后会在 data/ 下解出 ecdict.sqlite。
已存在且校验通过时不会重复下载。
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

ARCHIVE_NAME = "ecdict-ecdict-bc015ed2-focus13-v2.zip"
ARCHIVE_SHA256 = "1e745ea698878772226a7df584129409dd4b27cb7ea26b4259bc770e7533352f"
ARCHIVE_SIZE = 54_594_964
DB_NAME = "ecdict.sqlite"
DB_SIZE = 131_756_032
DB_SOURCE_SHA256 = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"

MIRRORS = (
    "https://hf-mirror.com/datasets/iamzhangship/fluency-ecdict-offline/resolve/main/" + ARCHIVE_NAME,
    "https://huggingface.co/datasets/iamzhangship/fluency-ecdict-offline/resolve/main/" + ARCHIVE_NAME,
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with tmp.open("wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print("\r  下载中 %3d%%  %6.1f / %.1f MB" % (pct, done / 1048576, total / 1048576), end="")
        print()
    tmp.replace(target)


def verify_db(db_path: Path) -> bool:
    """确认解出来的库是我们预期的那一份。"""
    import sqlite3

    if db_path.stat().st_size != DB_SIZE:
        print("  ! 数据库大小不符: %d != %d" % (db_path.stat().st_size, DB_SIZE))
        return False
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True)
    try:
        row = conn.execute("select source_sha256, entry_count from dictionary_meta").fetchone()
    finally:
        conn.close()
    if not row:
        print("  ! 读不到 dictionary_meta")
        return False
    if row[0] != DB_SOURCE_SHA256:
        print("  ! 来源校验值不符: %s" % row[0])
        return False
    print("  OK  词条数 %s，来源校验值一致" % format(row[1], ","))
    return True


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATA_DIR / ARCHIVE_NAME
    db_path = DATA_DIR / DB_NAME

    if db_path.exists() and verify_db(db_path):
        print("词典已就绪: %s" % db_path)
        print("下一步: python scripts/build_index.py")
        return 0

    if archive.exists() and archive.stat().st_size == ARCHIVE_SIZE and sha256_of(archive) == ARCHIVE_SHA256:
        print("归档已在本地且校验通过，跳过下载。")
    else:
        last_error = None
        for url in MIRRORS:
            try:
                print("下载: %s" % url)
                download(url, archive)
                if archive.stat().st_size != ARCHIVE_SIZE:
                    raise ValueError("大小不符: %d != %d" % (archive.stat().st_size, ARCHIVE_SIZE))
                if sha256_of(archive) != ARCHIVE_SHA256:
                    raise ValueError("SHA-256 不符")
                print("  OK  大小与 SHA-256 均一致")
                break
            except Exception as exc:
                last_error = exc
                print("  ! 该镜像失败: %s" % exc)
        else:
            print("所有镜像都失败了，最后一个错误: %s" % last_error)
            return 1

    print("解包 ...")
    with zipfile.ZipFile(archive) as bundle:
        name = DB_NAME
        if name not in bundle.namelist():
            candidates = [n for n in bundle.namelist() if n.endswith(".sqlite")]
            if not candidates:
                print("压缩包里没有 .sqlite 文件")
                return 1
            name = candidates[0]
        with bundle.open(name) as src, db_path.open("wb") as dst:
            dst.write(src.read())

    if not verify_db(db_path):
        return 1
    print("完成: %s" % db_path)
    print("下一步: python scripts/build_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
