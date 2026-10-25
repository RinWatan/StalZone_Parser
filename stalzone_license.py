# -*- coding: utf-8 -*-
"""Ключи подписки.

Обычный ключ открывает один человек, когда сам его вставит.
С этого момента срок идёт без паузы: выход из подписки дни не возвращает.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import sys
import time
import uuid
from pathlib import Path

_SECRET = b"stalzone-seat-v1-7c4e9a1b"
DAY = 86400
# Сюда ставится страница оплаты. Пока пусто, кнопка скажет, что ссылки ещё нет.
BUY_URL = ""


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text):
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(body):
    return _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())


def _root(root):
    if root is not None:
        return Path(root)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        folder = Path(base) / "STALZONE"
    else:
        folder = Path.home() / ".stalzone"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _read(path, fallback):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return data


def machine_id(root=None):
    folder = _root(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "machine.id"
    if path.exists():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    fresh = uuid.uuid4().hex
    path.write_text(fresh, encoding="utf-8")
    return fresh


def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.4)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "0.0.0.0"
    finally:
        sock.close()


def issue(days=30, role="user", label=""):
    role = "owner" if role == "owner" else "user"
    payload = {
        "v": 1,
        "id": secrets.token_hex(6),
        "role": role,
        "days": None if role == "owner" else max(1, int(days)),
        "label": label or ("владелец" if role == "owner" else ""),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return body + "." + _sign(body)


def issue_owner():
    return issue(role="owner", label="владелец")


def decode(key):
    parts = str(key or "").strip().split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Ключ не подходит")
    if not hmac.compare_digest(_sign(parts[0]), parts[1]):
        raise ValueError("Ключ не подходит")
    payload = json.loads(_unb64(parts[0]).decode())
    if payload.get("v") != 1 or not payload.get("id"):
        raise ValueError("Ключ не подходит")
    if payload.get("role") not in ("user", "owner"):
        raise ValueError("Ключ не подходит")
    return payload


def _seat_path(root):
    return _root(root) / "license.json"


def _book_path(root):
    return _root(root) / "license_registry.json"


def _view(seat, now):
    if not seat:
        return {"ok": True, "active": False, "reason": "Нет ключа"}
    expires = seat.get("expires")
    if expires and now >= float(expires):
        return {
            "ok": True, "active": False, "reason": "Срок ключа кончился",
            "role": seat.get("role") or "user", "key_id": seat.get("key_id") or "",
            "ip": seat.get("ip") or "", "machine": seat.get("machine") or "",
        }
    left = None
    if expires:
        left = max(0, int((float(expires) - now + DAY - 1) // DAY))
    role = seat.get("role") or "user"
    return {
        "ok": True,
        "active": True,
        "role": role,
        "label": seat.get("label") or ("владелец" if role == "owner" else ""),
        "key_id": seat.get("key_id") or "",
        "days_left": left,
        "expires": expires,
        "ip": seat.get("ip") or "",
        "host": seat.get("host") or "",
        "machine": seat.get("machine") or "",
    }


def status(root=None, now=None):
    seat = _read(_seat_path(root), None)
    if not isinstance(seat, dict):
        seat = None
    current = machine_id(root)
    if seat and seat.get("machine") != current:
        return {"ok": True, "active": False, "reason": "Ключ привязан к другому ПК"}
    return _view(seat, time.time() if now is None else now)


def activate(key, root=None, machine=None, ip=None, host=None, now=None):
    try:
        payload = decode(key)
    except Exception as error:
        return {"ok": False, "active": False, "reason": str(error) or "Ключ не подходит"}
    folder = _root(root)
    folder.mkdir(parents=True, exist_ok=True)
    pc = machine or machine_id(folder)
    (folder / "machine.id").write_text(pc, encoding="utf-8")
    address = ip if ip is not None else local_ip()
    name = host if host is not None else socket.gethostname()
    moment = time.time() if now is None else float(now)
    book = _read(_book_path(folder), [])
    if not isinstance(book, list):
        book = []
    if payload["role"] != "owner":
        for row in book:
            if row.get("key_id") == payload["id"] and row.get("machine") not in (None, "", pc):
                return {"ok": False, "active": False, "reason": "Этот ключ уже привязан к другому ПК"}
    previous = next((row for row in book if row.get("key_id") == payload["id"] and row.get("machine") == pc), None)
    if previous and previous.get("expires") not in (None, "") and moment >= float(previous["expires"]):
        return {"ok": False, "active": False, "reason": "Срок ключа кончился"}
    if previous and previous.get("expires") not in (None, ""):
        expires = float(previous["expires"])
        started = float(previous.get("activated") or expires)
    elif previous:
        started = float(previous.get("activated") or moment)
        days = payload.get("days")
        expires = None if payload["role"] == "owner" or days in (None, "") else started + int(days) * DAY
    else:
        started = moment
        days = payload.get("days")
        expires = None if payload["role"] == "owner" or days in (None, "") else started + int(days) * DAY
    seat = {
        "key_id": payload["id"],
        "role": payload["role"],
        "label": payload.get("label") or "",
        "machine": pc,
        "ip": address,
        "host": name,
        "activated": started,
        "expires": expires,
        "seen": moment,
    }
    _seat_path(folder).write_text(json.dumps(seat, ensure_ascii=False), encoding="utf-8")
    kept = [row for row in book if not (row.get("key_id") == payload["id"] and row.get("machine") == pc)]
    kept.append(seat)
    _book_path(folder).write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    return _view(seat, moment)


def drop(root=None):
    path = _seat_path(root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return status(root)


def main():
    parser = argparse.ArgumentParser(description="Выпустить ключ STALZONE")
    parser.add_argument("kind", nargs="?", default="30", help="Число дней или owner")
    args = parser.parse_args()
    if str(args.kind).lower() in ("owner", "владелец"):
        print(issue_owner())
        return
    print(issue(int(args.kind)))


if __name__ == "__main__":
    main()
