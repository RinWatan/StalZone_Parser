# -*- coding: utf-8 -*-
"""Общий снимок аукциона. Пишется у того, кто сканирует. Остальные читают его по сети."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SELL_TTL = 2 * 3600
BOUGHT_TTL = 45 * 60
_LOCK = threading.Lock()
_STORES = {}


def open_store(path):
    path = Path(path)
    key = str(path.resolve()) if path.parent.exists() else str(path)
    with _LOCK:
        store = _STORES.get(key)
        if store is None:
            store = MarketStore(path)
            _STORES[key] = store
        return store


class MarketStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sells (
                    sid TEXT PRIMARY KEY,
                    sell REAL NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS board (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    ts REAL NOT NULL,
                    scanned INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    rows TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bought (
                    key TEXT PRIMARY KEY,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coverage (
                    slug TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    who TEXT NOT NULL DEFAULT ''
                );
                """
            )

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def put_sells(self, rows, now=None):
        moment = time.time() if now is None else float(now)
        payload = [(str(sid), float(sell), float(ts or moment)) for sid, sell, ts in rows if sell]
        if not payload:
            return
        with self.lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO sells (sid, sell, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(sid) DO UPDATE SET sell=excluded.sell, ts=excluded.ts",
                payload,
            )

    def sell(self, sid, now=None, ttl=SELL_TTL):
        moment = time.time() if now is None else float(now)
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT sell, ts FROM sells WHERE sid = ?", (str(sid),)).fetchone()
        if not row or moment - float(row["ts"]) > ttl:
            return None
        return float(row["sell"])

    def save_board(self, rows, scanned, total, now=None):
        moment = time.time() if now is None else float(now)
        raw = json.dumps(list(rows or []), ensure_ascii=False, default=_jsonable)
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO board (id, ts, scanned, total, rows) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, scanned=excluded.scanned, "
                "total=excluded.total, rows=excluded.rows",
                (moment, int(scanned or 0), int(total or 0), raw),
            )

    def board(self):
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT ts, scanned, total, rows FROM board WHERE id = 1").fetchone()
            if not row:
                return None
            try:
                rows = json.loads(row["rows"])
            except ValueError:
                rows = []
            if not isinstance(rows, list):
                rows = []
            return {
                "ts": float(row["ts"]),
                "scanned": int(row["scanned"]),
                "total": int(row["total"]),
                "rows": self._without_bought(rows, conn),
            }

    def _without_bought(self, rows, conn):
        now = time.time()
        blocked = {
            row["key"]
            for row in conn.execute("SELECT key, ts FROM bought").fetchall()
            if now - float(row["ts"]) < BOUGHT_TTL
        }
        return [row for row in rows if offer_key(row) not in blocked]

    def bury(self, keys, now=None):
        moment = time.time() if now is None else float(now)
        payload = [(str(key), moment) for key in keys if key]
        if not payload:
            return
        with self.lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO bought (key, ts) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET ts=excluded.ts",
                payload,
            )
            board = conn.execute("SELECT rows FROM board WHERE id = 1").fetchone()
            if not board:
                return
            try:
                rows = json.loads(board["rows"])
            except ValueError:
                return
            blocked = {key for key, _ts in payload}
            kept = [row for row in rows if offer_key(row) not in blocked]
            conn.execute("UPDATE board SET rows = ?, ts = ? WHERE id = 1", (json.dumps(kept, ensure_ascii=False), moment))

    def merge_scan(self, deals, checked, who="", now=None):
        """Чужой прогон дописывает находки. По проверенным предметам старые лоты заменяются."""
        moment = time.time() if now is None else float(now)
        checked = {str(slug) for slug in checked or [] if slug}
        with self.lock, self._connect() as conn:
            current = conn.execute("SELECT ts, scanned, total, rows FROM board WHERE id = 1").fetchone()
            rows = []
            scanned = 0
            total = 0
            if current:
                scanned = int(current["scanned"] or 0)
                total = int(current["total"] or 0)
                try:
                    rows = json.loads(current["rows"])
                except ValueError:
                    rows = []
            if checked:
                rows = [row for row in rows if str(row.get("slug") or "") not in checked]
            blocked = {
                row["key"]
                for row in conn.execute("SELECT key, ts FROM bought").fetchall()
                if moment - float(row["ts"]) < BOUGHT_TTL
            }
            fresh = {}
            loose = []
            for row in rows:
                key = offer_key(row)
                if key and key not in blocked:
                    fresh[key] = row
                elif not key:
                    loose.append(row)
            for row in deals or []:
                if not isinstance(row, dict) or not row.get("slug"):
                    continue
                key = offer_key(row)
                if not key or key in blocked:
                    continue
                item = dict(row)
                item["seen"] = moment
                item["who"] = who or item.get("who") or ""
                fresh[key] = item
            conn.execute(
                "INSERT INTO board (id, ts, scanned, total, rows) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, scanned=excluded.scanned, "
                "total=excluded.total, rows=excluded.rows",
                (moment, scanned + len(checked), total, json.dumps([*loose, *fresh.values()], ensure_ascii=False, default=_jsonable)),
            )
            if checked:
                conn.executemany(
                    "INSERT INTO coverage (slug, ts, who) VALUES (?, ?, ?) "
                    "ON CONFLICT(slug) DO UPDATE SET ts=excluded.ts, who=excluded.who",
                    [(slug, moment, who or "") for slug in checked],
                )

    def claim_slice(self, items, limit=80, who="", now=None, stale=180):
        """Следующая дыра сетки: давно не смотрели, арты раньше остальных."""
        moment = time.time() if now is None else float(now)
        with self.lock, self._connect() as conn:
            covered = {row["slug"]: float(row["ts"]) for row in conn.execute("SELECT slug, ts FROM coverage")}
            ranked = []
            seen = set()
            for item in items or []:
                if isinstance(item, str):
                    slug, cat = item, ""
                else:
                    slug = str(item.get("id") or item.get("slug") or "")
                    cat = item.get("cat") or ""
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                ts = covered.get(slug)
                if ts is not None and moment - ts < stale:
                    continue
                ranked.append((0 if cat == "artefact" else 1, ts or 0, slug))
            ranked.sort()
            chosen = [slug for _cat, _ts, slug in ranked[: max(1, int(limit or 80))]]
            if chosen:
                conn.executemany(
                    "INSERT INTO coverage (slug, ts, who) VALUES (?, ?, ?) "
                    "ON CONFLICT(slug) DO UPDATE SET ts=excluded.ts, who=excluded.who",
                    [(slug, moment, who or "") for slug in chosen],
                )
            return chosen


def offer_key(row):
    slug = str((row or {}).get("slug") or "")
    if not slug:
        return ""
    return f"{slug}|{int((row or {}).get('amount') or 0)}|{int((row or {}).get('buyout') or 0)}"


def _jsonable(value):
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)
