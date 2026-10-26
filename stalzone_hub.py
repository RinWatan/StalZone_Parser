# -*- coding: utf-8 -*-
"""Хранилище для своих. Запускается на одном ПК, остальные подключаются по адресу.

Рядом лежит hub.json: {"port": 8791, "token": ""}. Токен пустой — хватает адреса.
У ребят файл hub.url, первая строка http://IP:8791, вторая строка токен, если он задан.
Свою базу им копировать не нужно.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import stalzone_agent as agent
import stalzone_market as market


def folder():
    return agent.DIR


def load_config():
    path = folder() / "hub.json"
    data = {"port": 8791, "token": ""}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise SystemExit("hub.json записан не как JSON") from exc
        if isinstance(raw, dict):
            data.update(raw)
    data["port"] = int(data.get("port") or 8791)
    data["token"] = str(data.get("token") or "").strip()
    return data


def catalog_rows():
    path = folder() / "catalog.json"
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            rows = []
        if isinstance(rows, list) and rows:
            return rows
    db = folder() / "items.db"
    if not db.exists():
        return []
    conn_path = db
    import sqlite3
    conn = sqlite3.connect(conn_path)
    conn.row_factory = sqlite3.Row
    try:
        found = conn.execute(
            "SELECT id, name, category, color, icon, status, tradable FROM items WHERE tradable = 1"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "cat": row["category"],
            "color": row["color"] or "DEFAULT",
            "icon": row["icon"] or "",
            "status": row["status"] or "",
            "tradable": 1,
        }
        for row in found
    ]


def make_handler(store, token):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not self._allowed():
                self._send(403, {"ok": False, "reason": "Нет доступа к хранилищу"})
                return
            path = self.path.split("?", 1)[0]
            if path == "/v1/health":
                board = store.board()
                self._send(200, {"ok": True, "ts": None if not board else board["ts"]})
                return
            if path == "/v1/catalog":
                self._send(200, {"ok": True, "items": catalog_rows()})
                return
            if path == "/v1/deals":
                self._send(200, {"ok": True, **agent.board_for_team(store)})
                return
            self._send(404, {"ok": False, "reason": "Нет такого адреса"})

        def log_message(self, fmt, *args):
            return

        def _allowed(self):
            if not token:
                return True
            return (self.headers.get("X-Hub-Token") or "").strip() == token

        def _send(self, code, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def serve(port, store, token):
    httpd = ThreadingHTTPServer(("0.0.0.0", int(port)), make_handler(store, token))
    httpd.serve_forever()


def main():
    cfg = load_config()
    store = market.open_store(folder() / "market.db")
    print(f"Хранилище слушает порт {cfg['port']}.")
    print("Ребятам в hub.url достаточно строки http://IP-этого-ПК:" + str(cfg["port"]))
    print("Базу копировать им не нужно. Сначала на этом ПК сделай один прогон.")
    serve(cfg["port"], store, cfg["token"])


if __name__ == "__main__":
    main()
