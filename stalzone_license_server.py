# -*- coding: utf-8 -*-
"""Сервер ключей STALZONE и пульт в Telegram.

Запуск на своём ПК: python stalzone_license_server.py
Рядом лежит license_server.json с токеном бота. В гит его не класть.
Первое личное сообщение боту закрепляет владельца.
"""
import json
import sqlite3
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def folder():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find_license_module():
    here = folder()
    for candidate in [here, *here.parents]:
        if (candidate / "stalzone_license.py").exists():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            return
    raise SystemExit(
        "Рядом с сервером нет stalzone_license.py. "
        "Запускай python stalzone_license_server.py из папки, где лежит весь проект, "
        "а не из отдельной папки Сервер."
    )


_find_license_module()
import stalzone_license as lic


def load_config():
    path = folder() / "license_server.json"
    if not path.exists():
        raise SystemExit(
            "Рядом с сервером нет license_server.json.\n"
            "Создай его в этой же папке, с кавычками:\n"
            '{\n  "token": "токен из BotFather",\n  "port": 8787\n}'
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise SystemExit(
            "license_server.json записан не как JSON. Кавычки и двоеточия обязательны:\n"
            '{\n  "token": "токен из BotFather",\n  "port": 8787\n}'
        )
    if not isinstance(data, dict) or not str(data.get("token") or "").strip():
        raise SystemExit('В license_server.json нет поля "token".')
    data["token"] = str(data["token"]).strip()
    try:
        data["port"] = int(data.get("port") or 8787)
    except (TypeError, ValueError):
        raise SystemExit('Поле "port" должно быть числом, например 8787.')
    return data


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        with self.lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS keys (
                        id TEXT PRIMARY KEY,
                        token TEXT NOT NULL,
                        role TEXT NOT NULL,
                        label TEXT,
                        days INTEGER,
                        created REAL,
                        activated REAL,
                        expires REAL,
                        machine TEXT,
                        ip TEXT,
                        revoked INTEGER DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS meta (
                        k TEXT PRIMARY KEY,
                        v TEXT
                    );
                    """
                )

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def owner(self):
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT v FROM meta WHERE k = 'owner'").fetchone()
        return int(row["v"]) if row and row["v"] else None

    def claim_owner(self, chat_id):
        with self.lock, self._connect() as conn:
            current = conn.execute("SELECT v FROM meta WHERE k = 'owner'").fetchone()
            if current and current["v"]:
                return int(current["v"]) == int(chat_id)
            conn.execute("INSERT INTO meta (k, v) VALUES ('owner', ?)", (str(chat_id),))
        return True

    def issue(self, days=None, role="user", now=None):
        moment = time.time() if now is None else float(now)
        if role == "owner":
            token = lic.issue_owner()
            days_value = None
            label = "владелец"
        else:
            days_value = max(1, int(days or 30))
            token = lic.issue(days_value)
            label = ""
        payload = lic.decode(token)
        with self.lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO keys (id, token, role, label, days, created, revoked)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (payload["id"], token, payload["role"], label, days_value, moment),
            )
        return token, payload["id"], days_value

    def revoke(self, key_id):
        with self.lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE keys SET revoked = 1 WHERE id = ?",
                (str(key_id or "").strip(),),
            )
            return cur.rowcount > 0

    def rows(self):
        with self.lock, self._connect() as conn:
            found = conn.execute("SELECT * FROM keys ORDER BY created DESC").fetchall()
        return [dict(row) for row in found]

    def activate(self, key, machine, ip="", now=None):
        moment = time.time() if now is None else float(now)
        try:
            payload = lic.decode(key)
        except Exception:
            return {"ok": False, "active": False, "reason": "Ключ не подходит"}
        with self.lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM keys WHERE id = ?", (payload["id"],)).fetchone()
                if row is None or row["token"] != str(key).strip():
                    return {"ok": False, "active": False, "reason": "Ключ не подходит"}
                data = dict(row)
                if data["revoked"]:
                    return {"ok": False, "active": False, "reason": "Ключ отозван"}
                if data["role"] != "owner" and data["machine"] and data["machine"] != machine:
                    return {"ok": False, "active": False, "reason": "Этот ключ уже привязан к другому ПК"}
                if data["role"] != "owner" and data["expires"] and moment >= float(data["expires"]):
                    return {"ok": False, "active": False, "reason": "Срок ключа кончился"}
                activated = data["activated"]
                expires = data["expires"]
                bound = data["machine"] or ""
                if data["role"] == "owner":
                    activated = activated or moment
                    expires = None
                    bound = machine
                elif not activated:
                    activated = moment
                    expires = moment + int(data["days"] or payload.get("days") or 30) * lic.DAY
                    bound = machine
                if not bound:
                    bound = machine
                conn.execute(
                    """UPDATE keys
                       SET activated = ?, expires = ?, machine = ?, ip = ?
                       WHERE id = ?""",
                    (activated, expires, bound if data["role"] != "owner" else (data["machine"] or machine), ip or "", payload["id"]),
                )
                conn.commit()
            finally:
                conn.close()
        seat = {
            "key_id": payload["id"],
            "role": data["role"],
            "label": data["label"] or "",
            "machine": bound,
            "activated": activated,
            "expires": expires,
            "ip": ip or "",
        }
        view = lic._view(seat, moment)
        view["lease"] = lic.pack_lease(seat)
        return view


def describe(row, now):
    if row["revoked"]:
        state = "отозван"
    elif row["role"] == "owner":
        state = "владелец · безлимит"
    elif not row["activated"]:
        state = f"ждёт вход · {int(row['days'] or 0)} дн."
    elif row["expires"] and now >= float(row["expires"]):
        state = "срок кончился"
    else:
        left = max(0, int((float(row["expires"]) - now + lic.DAY - 1) // lic.DAY))
        state = f"вошёл · ещё {left} дн."
    return f"{row['id']} · {state}"


def answer(store, chat_id, text, now=None):
    moment = time.time() if now is None else float(now)
    if not store.claim_owner(chat_id):
        return "Это пульт владельца."
    parts = str(text or "").strip().split()
    if not parts:
        return help_text()
    cmd = parts[0].split("@", 1)[0].lower()
    if cmd in ("/start", "/help", "/помощь"):
        return help_text()
    if cmd in ("/key", "/ключ"):
        days = 30
        if len(parts) > 1:
            try:
                days = max(1, int(parts[1]))
            except ValueError:
                return "Напиши так: /ключ 30"
        token, key_id, days_value = store.issue(days, now=moment)
        return f"Ключ на {days_value} дн.\nСрок пойдёт с первого входа и не встанет на паузу.\n{token}\n\nНомер: {key_id}"
    if cmd in ("/owner", "/владелец"):
        token, key_id, _days = store.issue(role="owner", now=moment)
        return f"Ключ владельца, без срока.\n{token}\n\nНомер: {key_id}"
    if cmd in ("/list", "/список"):
        rows = store.rows()
        if not rows:
            return "Ключей ещё нет."
        return "\n".join(describe(row, moment) for row in rows[:30])
    if cmd in ("/revoke", "/отмена"):
        if len(parts) < 2:
            return "Напиши так: /отмена номер"
        if store.revoke(parts[1]):
            return "Ключ закрыт."
        return "Такого номера нет."
    return help_text()


def help_text():
    return "\n".join([
        "STALZONE",
        "/ключ 30 — обычный ключ, срок с первого входа",
        "/владелец — безлимит",
        "/список — что сейчас с ключами",
        "/отмена номер — закрыть ключ",
    ])


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.split("?", 1)[0] != "/v1/activate":
                self._send(404, {"ok": False, "active": False, "reason": "Нет такого адреса"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode() or "{}")
            except Exception:
                self._send(200, {"ok": False, "active": False, "reason": "Ключ не подходит"})
                return
            result = store.activate(payload.get("key"), str(payload.get("machine") or ""), str(payload.get("ip") or ""))
            self._send(200, result)

        def _send(self, code, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            return

    return Handler


def serve(store, port):
    server = ThreadingHTTPServer(("0.0.0.0", int(port)), make_handler(store))
    server.serve_forever()


def telegram(token, method, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode())


def poll(token, store):
    try:
        telegram(token, "deleteWebhook", {"drop_pending_updates": False})
    except Exception:
        pass
    offset = None
    while True:
        try:
            payload = {"timeout": 25}
            if offset is not None:
                payload["offset"] = offset
            data = telegram(token, "getUpdates", payload)
            for update in data.get("result") or []:
                offset = int(update["update_id"]) + 1
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                if chat.get("type") != "private" or "text" not in message:
                    continue
                text = answer(store, chat.get("id"), message.get("text") or "")
                telegram(token, "sendMessage", {"chat_id": chat["id"], "text": text})
        except Exception:
            time.sleep(3)


def main():
    cfg = load_config()
    store = Store(folder() / "license_server.db")
    threading.Thread(target=serve, args=(store, cfg["port"]), daemon=True).start()
    print(f"Сервер ключей слушает порт {cfg['port']}.")
    print("Открой бота в личке и нажми Start. Первое сообщение закрепляет владельца.")
    poll(cfg["token"], store)


if __name__ == "__main__":
    main()
