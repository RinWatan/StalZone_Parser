# -*- coding: utf-8 -*-
"""Локальный учёт выкупа. Файл учёт.xlsx рядом с программой, строки не удаляются."""
import threading
import uuid
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import stalzone_agent as agent

HEADERS = ["Дата", "Предмет", "Редкость", "Точка", "Куплено", "Штук", "Продано", "После 5%", "Плюс", "Своя", "id"]
_LOCK = threading.Lock()
_MONEY = {"Куплено", "Продано", "После 5%", "Плюс"}


def book_path():
    return agent.DIR / "учёт.xlsx"


def _today():
    return datetime.now(agent.MSK).date()


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return _today()


def _as_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return agent.parse_money(value)
    return int(round(float(value)))


def _money(sell, buy):
    if sell is None:
        return None, None
    net = int(sell) * 95 // 100
    return net, net - int(buy or 0)


def _hand_flag(value):
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"1", "да", "true"}


def _as_count(value):
    if value is None or str(value).strip() == "":
        return None
    return _as_int(value)


def _header_map(ws):
    found = {}
    for cell in next(ws.iter_rows(min_row=1, max_row=1)):
        if cell.value:
            found[str(cell.value).strip()] = cell.column - 1
    return found


def _at(cells, headers, title):
    index = headers.get(title)
    if index is None or index >= len(cells):
        return None
    return cells[index].value


def _mark(value):
    text = str(value or "").strip()
    return "" if text in {"—", "-"} else text


def _read(cells, headers):
    sell_raw = _at(cells, headers, "Продано")
    sell = _as_int(sell_raw)
    if sell == 0 and (sell_raw is None or str(sell_raw).strip() == ""):
        sell = None
    buy = _as_int(_at(cells, headers, "Куплено")) or 0
    net, gain = _money(sell, buy)
    ident = _at(cells, headers, "id")
    return {
        "date": _as_date(_at(cells, headers, "Дата")),
        "name": str(_at(cells, headers, "Предмет") or "").strip(),
        "qlt": _mark(_at(cells, headers, "Редкость")),
        "ptn": _mark(_at(cells, headers, "Точка")),
        "buy": buy,
        "qty": _as_count(_at(cells, headers, "Штук")),
        "sell": sell,
        "net": net,
        "gain": gain,
        "hand": _hand_flag(_at(cells, headers, "Своя")),
        "id": str(ident).strip() if ident else "",
    }


def _load_locked():
    path = book_path()
    if not path.exists():
        return []
    try:
        wb = load_workbook(path)
    except OSError as error:
        raise RuntimeError("Не открыть учёт.xlsx. Закрой его в Excel") from error
    ws = wb.active
    headers = _header_map(ws)
    name_at = headers.get("Предмет", 1)
    rows = []
    dirty = any(title not in headers for title in ("Штук", "Своя", "Редкость", "Точка"))
    for cells in ws.iter_rows(min_row=2):
        if name_at >= len(cells) or cells[name_at].value is None or str(cells[name_at].value).strip() == "":
            continue
        item = _read(cells, headers)
        if not item["id"]:
            item["id"] = uuid.uuid4().hex[:12]
            dirty = True
        stored_net = _as_int(_at(cells, headers, "После 5%"))
        stored_gain = _as_int(_at(cells, headers, "Плюс"))
        if item["net"] != stored_net or item["gain"] != stored_gain:
            dirty = True
        rows.append(item)
    if dirty:
        _write_locked(rows)
    return rows


def _write_locked(rows):
    path = book_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Выкуп"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="173226")
    for col, title in enumerate(HEADERS, start=1):
        cell = ws.cell(1, col, title)
        cell.font = head
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
    for index, row in enumerate(rows, start=2):
        net, gain = _money(row.get("sell"), row.get("buy") or 0)
        row["net"] = net
        row["gain"] = gain
        values = [
            row["date"], row["name"], row.get("qlt") or "", row.get("ptn") or "",
            int(row["buy"] or 0), row.get("qty"),
            row["sell"], net, gain, 1 if row.get("hand") else 0, row["id"],
        ]
        for col, value in enumerate(values, start=1):
            title = HEADERS[col - 1]
            cell = ws.cell(index, col, value)
            if title == "Дата":
                cell.number_format = "DD.MM.YYYY"
            elif title in _MONEY or title == "Штук":
                if value is not None:
                    cell.number_format = "#,##0"
            if title == "Плюс" and isinstance(value, int):
                cell.font = Font(color="1F7A4D" if value >= 0 else "A33B3B")
    widths = (14, 42, 18, 12, 16, 12, 16, 16, 16, 10, 14)
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.column_dimensions["J"].hidden = True
    ws.column_dimensions["K"].hidden = True
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{max(1, len(rows) + 1)}"
    tmp = path.with_suffix(".tmp.xlsx")
    try:
        wb.save(tmp)
        tmp.replace(path)
    except OSError as error:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Закрой учёт.xlsx в Excel и повтори") from error


def load():
    with _LOCK:
        return _load_locked()


def add(name, buy, sell, qty=None, hand=False, qlt="", ptn=""):
    title = str(name or "").strip()
    if not title:
        raise ValueError("Нет названия")
    bought = int(buy or 0)
    sold = int(sell or 0) or None
    count = None if qty in (None, "") else int(qty)
    quality = _mark(qlt)
    point = _mark(ptn)
    own = bool(hand)
    with _LOCK:
        rows = _load_locked()
        today = _today()
        if not own:
            for row in rows:
                if row["date"] == today and row["name"] == title and row["buy"] == bought and row.get("qlt") == quality and row.get("ptn") == point:
                    return False
        rows.append({
            "date": today,
            "name": title,
            "qlt": quality,
            "ptn": point,
            "buy": bought,
            "qty": count,
            "sell": sold,
            "hand": own,
            "id": uuid.uuid4().hex[:12],
        })
        _write_locked(rows)
        return True


def _change(row_id, field, value):
    ident = str(row_id or "").strip()
    with _LOCK:
        rows = _load_locked()
        found = False
        for row in rows:
            if row["id"] != ident:
                continue
            found = True
            row[field] = value
            break
        if not found:
            raise ValueError("Строки нет в учёте")
        _write_locked(rows)


def set_mark(row_id, qlt, ptn):
    ident = str(row_id or "").strip()
    with _LOCK:
        rows = _load_locked()
        found = False
        for row in rows:
            if row["id"] != ident:
                continue
            found = True
            row["qlt"] = _mark(qlt)
            row["ptn"] = _mark(ptn)
            break
        if not found:
            raise ValueError("Строки нет в учёте")
        _write_locked(rows)


def set_sell(row_id, sell):
    _change(row_id, "sell", None if sell is None else int(sell))


def _own(rows, ident):
    for row in rows:
        if row["id"] == ident:
            if not row.get("hand"):
                raise ValueError("Эту строку принёс выкуп")
            return row
    raise ValueError("Строки нет в учёте")


def set_name(row_id, name):
    title = str(name or "").strip()
    if not title:
        raise ValueError("Нет названия")
    ident = str(row_id or "").strip()
    with _LOCK:
        rows = _load_locked()
        _own(rows, ident)["name"] = title
        _write_locked(rows)


def set_buy(row_id, buy):
    ident = str(row_id or "").strip()
    with _LOCK:
        rows = _load_locked()
        _own(rows, ident)["buy"] = int(buy or 0)
        _write_locked(rows)


def set_qty(row_id, qty):
    ident = str(row_id or "").strip()
    new = None if qty is None else int(qty)
    with _LOCK:
        rows = _load_locked()
        found = False
        for row in rows:
            if row["id"] != ident:
                continue
            found = True
            old = row.get("qty")
            if not row.get("hand") and old and new and int(old) > 0 and new != int(old):
                row["buy"] = int(round(int(row["buy"] or 0) * new / int(old)))
                if row.get("sell") is not None:
                    row["sell"] = int(round(int(row["sell"]) * new / int(old)))
            row["qty"] = new
            break
        if not found:
            raise ValueError("Строки нет в учёте")
        _write_locked(rows)


def remove(row_id):
    ident = str(row_id or "").strip()
    with _LOCK:
        rows = _load_locked()
        kept = [row for row in rows if row["id"] != ident]
        if len(kept) == len(rows):
            raise ValueError("Строки нет в учёте")
        _write_locked(kept)


def snapshot():
    today = _today()
    gain = 0
    today_gain = 0
    out = []
    for row in load():
        is_today = row["date"] == today
        if row["sell"] is not None and row["gain"] is not None:
            gain += row["gain"]
            if is_today:
                today_gain += row["gain"]
        out.append({
            "id": row["id"],
            "date": row["date"].isoformat(),
            "date_ru": row["date"].strftime("%d.%m.%Y"),
            "name": row["name"],
            "qlt": row.get("qlt") or "",
            "ptn": row.get("ptn") or "",
            "buy": row["buy"],
            "qty": row.get("qty"),
            "sell": row["sell"],
            "net": row["net"],
            "gain": row["gain"],
            "hand": bool(row.get("hand")),
            "today": is_today,
        })
    return {
        "ok": True,
        "path": str(book_path()),
        "rows": out,
        "gain": gain,
        "today_gain": today_gain,
    }
