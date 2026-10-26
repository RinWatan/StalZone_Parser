# -*- coding: utf-8 -*-
"""Общий снимок аукциона. Пишется у того, кто сканирует. Остальные читают его по сети."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SELL_TTL = 2 * 3600
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
        return {
            "ts": float(row["ts"]),
            "scanned": int(row["scanned"]),
            "total": int(row["total"]),
            "rows": rows if isinstance(rows, list) else [],
        }


def _jsonable(value):
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)
