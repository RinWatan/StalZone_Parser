# -*- coding: utf-8 -*-
"""Локальная база предметов: id, иконка и можно ли выставлять на аукцион."""
import sqlite3
import threading
import time

ICON_BASE = "https://raw.githubusercontent.com/EXBO-Studio/stalzone-database/main/ru"
# Именные с момента получения и квестовые на аукцион не выставляются.
UNTRADABLE_STATUS = {"PERSONAL_ON_GET"}
_LOCK = threading.Lock()


def icon_url(path):
    path = str(path or "")
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return ICON_BASE + path


def classify(item):
    """0 — купить и продать нельзя. 1 — предмет может быть на аукционе."""
    status = str(item.get("status") or "")
    if item.get("color") == "QUEST_ITEM" or status in UNTRADABLE_STATUS:
        return 0, "status"
    return 1, ""


def _connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            color TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            tradable INTEGER NOT NULL DEFAULT 1,
            reason TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS items_tradable ON items(tradable);
        """
    )
    return conn


def sync_items(path, items):
    """Дописывает новые предметы и обновляет известные. Выученный запрет аукциона не затирается."""
    rows = [item for item in items or [] if item.get("id")]
    if not rows:
        return {"added": 0, "total": 0}
    now = time.time()
    with _LOCK:
        conn = _connect(path)
        try:
            before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            conn.executemany(
                """
                INSERT INTO items (id, name, category, color, icon, status, tradable, reason, updated_at)
                VALUES (:id, :name, :category, :color, :icon, :status, :tradable, :reason, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    color=excluded.color,
                    icon=CASE WHEN excluded.icon != '' THEN excluded.icon ELSE items.icon END,
                    status=CASE WHEN excluded.status != '' THEN excluded.status ELSE items.status END,
                    tradable=CASE
                        WHEN excluded.tradable = 0 AND excluded.reason = 'status' THEN 0
                        WHEN items.tradable = 0 AND items.reason = 'auction' THEN 0
                        WHEN excluded.reason = 'status' THEN excluded.tradable
                        ELSE items.tradable
                    END,
                    reason=CASE
                        WHEN excluded.tradable = 0 AND excluded.reason = 'status' THEN 'status'
                        WHEN items.tradable = 0 AND items.reason = 'auction' THEN items.reason
                        WHEN excluded.reason = 'status' THEN excluded.reason
                        ELSE items.reason
                    END,
                    updated_at=excluded.updated_at
                """,
                [_bind(item, now) for item in rows],
            )
            conn.commit()
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            return {"added": max(0, total - before), "total": total}
        finally:
            conn.close()


def mark_untradable(path, item_id, reason="auction"):
    item_id = str(item_id or "")
    if not item_id:
        return
    now = time.time()
    with _LOCK:
        conn = _connect(path)
        try:
            conn.execute(
                """
                INSERT INTO items (id, name, category, color, icon, status, tradable, reason, updated_at)
                VALUES (?, ?, '', 'DEFAULT', '', '', 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    tradable=0,
                    reason=excluded.reason,
                    updated_at=excluded.updated_at
                """,
                (item_id, item_id, reason, now),
            )
            conn.commit()
        finally:
            conn.close()


def untradable_ids(path):
    if not path.exists():
        return set()
    with _LOCK:
        conn = _connect(path)
        try:
            rows = conn.execute("SELECT id FROM items WHERE tradable = 0").fetchall()
            return {row["id"] for row in rows}
        finally:
            conn.close()


def get_item(path, item_id):
    if not path.exists():
        return None
    with _LOCK:
        conn = _connect(path)
        try:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (str(item_id),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def _bind(item, now):
    tradable, reason = classify(item)
    stored = item.get("tradable")
    if stored in (0, 1, True, False) and item.get("reason"):
        tradable = int(bool(stored))
        reason = str(item.get("reason") or reason)
    return {
        "id": str(item["id"]),
        "name": str(item.get("name") or item["id"]),
        "category": str(item.get("cat") or item.get("category") or ""),
        "color": str(item.get("color") or "DEFAULT"),
        "icon": str(item.get("icon") or ""),
        "status": str(item.get("status") or ""),
        "tradable": int(tradable),
        "reason": reason,
        "updated_at": now,
    }
