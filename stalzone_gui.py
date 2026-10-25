# -*- coding: utf-8 -*-
"""Окно агента. Расчёты те же, интерфейс на системном браузере Windows."""
import json
import sys
import threading
import time
import traceback
from pathlib import Path

import stalzone_agent as agent
import stalzone_db
import stalzone_ledger as book
import stalzone_license as lic
import stalzone_lunar as lunar
import stalzone_pda as pda

SECTIONS = [
    ("Общий", None),
    ("Выкуп", "buys"),
    ("Фарм", "farm"),
    ("Арсенал", "arsenal"),
    ("Убежище купить", "shelter_buy"),
    ("Убежище продать", "shelter_sell"),
    ("Расходники", "consumables"),
    ("Арты", "arts"),
    ("Протоартефакты", "protos"),
]
TABLES = {
    "buys": ["Предмет", "Редкость", "Точка", "Лоты", "Купить за", "Выставить пачку", "После 5%", "Плюс", "Рентабельность", "В час", "Плюс в час", "Если купить сейчас"],
    "farm": ["Предмет", "Продают", "Продавать от", "Пачка", "Решение"],
    "arsenal": ["Предмет", "Продают", "Продавать от", "Решение"],
    "shelter_buy": ["Предмет", "Продают", "Выкуп", "Решение"],
    "shelter_sell": ["Предмет", "Продают", "Продавать от", "Решение"],
    "consumables": ["Предмет", "Продают", "Выкуп", "Фарм"],
    "arts": ["Арт", "Редкость", "Точка", "Сделок", "Покупали", "Продавали", "Профит", "Решение"],
    "protos": ["Редкость", "Сделок", "Выкуп", "Фарм", "Цена", "Продают", "Профит"],
}


def money(n):
    return agent.rub(n)


def _tag(act):
    text = act or ""
    if "ВЫКУП" in text and "НЕ" not in text:
        return "buy"
    if text.startswith("СЛИТ"):
        return "sell"
    if text.startswith("ДЕРЖ"):
        return "hold"
    return "skip"


def _side(rows):
    out = []
    for r in rows:
        if r.get("err"):
            out.append({"cells": [r["name"], "—", r["err"], "—"], "tag": "skip"})
            continue
        why = r.get("why") or ""
        buy = r.get("buy") or ""
        note = f"{buy} · {why}" if why else buy
        out.append({"cells": [r["name"], money(r.get("med", 0)), note, r.get("farm") or ""], "tag": _tag(buy)})
    return out


def _sell(rows, pack=False):
    out = []
    for r in rows:
        if r.get("err"):
            cells = [r["name"], "—", r["err"], "—", "—"] if pack else [r["name"], "—", r["err"], "—"]
            out.append({"cells": cells, "tag": "skip"})
            continue
        price = money(r.get("ask", r.get("med", 0)))
        note = r.get("farm") or ""
        if r.get("why"):
            note = f"{note}: {r['why']}"
        if pack:
            cells = [r["name"], money(r.get("med", 0)), price, r.get("pack") or "—", note]
        else:
            cells = [r["name"], money(r.get("med", 0)), price, note]
        out.append({"cells": cells, "tag": _tag(r.get("farm"))})
    return out


def rows_from(data):
    tables = {}
    if "buys" in data:
        buys = []
        for r in data.get("buys") or []:
            tag = f"q{r['qlt_i']}" if r.get("qlt_i") is not None else "buy"
            copies = int(r.get("copies") or 1)
            amount = int(r.get("amount") or 1)
            spent = int(r.get("spend") or 0) or int(r.get("buyout") or 0) * copies
            asked = int(round(float(r.get("med") or 0) * amount * copies))
            label = r["name"]
            buys.append({
                "cells": [
                    r["name"], r.get("qlt") or "—", r.get("ptn") or "—",
                    f"{r['copies']} x {r['amount']}", money(r["buyout"]),
                    money(r["med"] * r["amount"]), money(r["med"] * r["amount"] * agent.COMM),
                    money(r["gain"]), f"{(r.get('roi') or 0) * 100:.0f}%",
                    f"{r.get('per_h', 0):.1f}", money(r.get("hour_gain") or 0),
                    r.get("plan") or "ВЫКУПИТЬ",
                ],
                "tag": tag,
                "deal": {
                    "name": label,
                    "buy": spent,
                    "sell": asked,
                    "qty": copies * amount,
                    "qlt": r.get("qlt") or "",
                    "ptn": r.get("ptn") or "",
                },
            })
        tables["buys"] = buys
    if "farm" in data:
        tables["farm"] = _sell(data.get("farm") or [], pack=True)
    if "arsenal" in data:
        tables["arsenal"] = _sell(data.get("arsenal") or [])
    if "shelter_buy" in data:
        mats = []
        for r in data.get("shelter_buy") or []:
            if r.get("err"):
                mats.append({"cells": [r["name"], "—", r["err"], "—"], "tag": "skip"})
            else:
                mats.append({"cells": [r["name"], money(r.get("med", 0)), r.get("why") or "", r.get("buy") or ""], "tag": _tag(r.get("buy"))})
        tables["shelter_buy"] = mats
    if "shelter_sell" in data:
        tables["shelter_sell"] = _sell(data.get("shelter_sell") or [])
    if "consumables" in data:
        tables["consumables"] = _side(data.get("consumables") or [])
    if "arts" in data:
        arts = []
        for r in data.get("arts") or []:
            if r.get("err"):
                arts.append({"cells": [r["name"], "—", "—", "—", "—", "—", "—", r["err"]], "tag": "skip"})
            else:
                tag = f"q{r['qlt_i']}" if r.get("qlt_i") is not None else "skip"
                arts.append({
                    "cells": [r["name"], r.get("qlt") or "—", r.get("ptn") or "—", r["n"], money(r["cheap"]), money(r["med"]), money(r["net"]), r.get("liq") or "БРАТЬ"],
                    "tag": tag,
                })
        tables["arts"] = arts
    if "protos" in data:
        protos = []
        for r in data.get("protos") or []:
            if r.get("err"):
                protos.append({"cells": [r.get("qlt") or r["name"], "—", r["err"], "—", "—", "—", "—"], "tag": "skip"})
            else:
                decision = r.get("buy") or ""
                protos.append({
                    "cells": [r.get("qlt", ""), r.get("n", ""), decision, r.get("farm", ""), money(r.get("cheap", 0)), money(r.get("med", 0)), money(r.get("net", 0))],
                    "tag": _tag(decision if decision == "ВЫКУПИТЬ" else r.get("farm")),
                })
        tables["protos"] = protos
    return tables


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.logs = ["Ждёт. Вкладка «Аукцион» — поиск по каталогу, лоты и история."]
        self.status = "ожидание"
        self.busy = False
        self.tables = {}
        self.rev = 0
        self.worker = None
        self.watch = []
        self.auction = []
        self.fav = set(self._read_json("auction_fav.json"))
        self.recent = self._read_json("auction_recent.json")
        self.lot_data = None
        self._stats_lock = threading.Lock()
        self._item_lock = threading.Lock()
        self._item_generation = 0
        self.open_slug = None
        self._wiki = {}
        self._hud = None
        self._compact = []
        self._launch_lock = threading.Lock()
        self._search_lock = threading.Lock()
        self._catalog_busy = False
        self._catalog_payload = None

    def wiki_map(self, slug):
        slug = str(slug or "").strip()
        names = {
            "south-zone": "Южная Зона",
            "north-zone": "Северная Зона",
            "wild-north": "Дикий Север",
            "lyubech": "Любеч-3",
            "labyrinth": "Лабиринт",
            "graveyard": "Могильник",
        }
        if slug not in names:
            return {"error": "нет такой карты"}
        cached = self._wiki.get(slug)
        if cached:
            cached = dict(cached)
            cached["mine"] = self._marks_of(slug)
            return cached
        try:
            import httpx
            page = httpx.get(
                "https://stalzone.wiki/maps/" + slug,
                timeout=40,
                headers={"User-Agent": "STALZONE"},
            ).text
            game = self._wiki_game(page)
            pack = self._wiki_pack(game)
            pack["slug"] = slug
            pack["title"] = names[slug]
            self._wiki[slug] = pack
            pack = dict(pack)
            pack["mine"] = self._marks_of(slug)
            marks = sum(len(t["markers"]) for g in pack["groups"] for t in g["types"])
            self.note(f"Карта {names[slug]}: {marks} меток")
            return pack
        except Exception as error:
            self.note("Карта не загрузилась: " + str(error))
            return {"error": str(error)}

    def _wiki_game(self, html):
        import re
        blobs = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
        for blob in sorted(blobs, key=len, reverse=True):
            try:
                text = json.loads('"' + blob + '"')
            except Exception:
                continue
            start = text.find('{"map":')
            if start < 0:
                continue
            depth = 0
            for index, char in enumerate(text[start:], start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start:index + 1])["map"]
        raise ValueError("на странице нет карты")

    def _wiki_text(self, value):
        if isinstance(value, dict):
            return str(value.get("ru") or value.get("en") or "")
        return str(value or "")

    def _wiki_pack(self, game):
        settings = game.get("settings") or {}
        groups = []
        for group in game.get("marker_groups") or []:
            types = []
            for kind in group.get("marker_types") or []:
                look = kind.get("settings") or {}
                marks = []
                for mark in kind.get("markers") or []:
                    point = mark.get("coordinates") or {}
                    if point.get("lat") is None or point.get("lng") is None:
                        continue
                    marks.append({
                        "lat": point["lat"],
                        "lng": point["lng"],
                        "text": self._wiki_text(mark.get("description")),
                    })
                if marks:
                    types.append({
                        "title": self._wiki_text(kind.get("name")) or kind.get("slug") or "Метка",
                        "color": look.get("color") or "#e0b15a",
                        "image": look.get("image") or "",
                        "markers": marks,
                    })
            if types:
                groups.append({"title": self._wiki_text(group.get("name")) or "Метки", "types": types})
        areas = []
        for group in game.get("area_groups") or []:
            for kind in group.get("area_types") or []:
                look = kind.get("settings") or {}
                polygons = []
                for area in kind.get("areas") or []:
                    points = area.get("coordinates") or []
                    if len(points) >= 3:
                        polygons.append(points)
                if polygons:
                    areas.append({
                        "title": self._wiki_text(kind.get("name")) or "Зона",
                        "fill": look.get("fill") or "#ff5050",
                        "border": look.get("border") or "#ff5050",
                        "polygons": polygons,
                    })
        return {
            "settings": {
                "tiles": settings.get("tiles") or "",
                "minZoom": settings.get("minZoom") or 2,
                "maxZoom": settings.get("maxZoom") or 4,
                "defaultZoom": settings.get("defaultZoom") or 3,
                "width": settings.get("width") or 2048,
                "height": settings.get("height") or 2048,
            },
            "groups": groups,
            "areas": areas,
        }

    def _marks_of(self, slug):
        return [mark for mark in self._load_marks() if mark.get("slug") == slug]

    def _load_marks(self):
        path = agent.DIR / "wiki_marks.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def pda_status(self):
        root = pda.map_root(agent.DIR)
        maps = pda.list_maps(root)
        if not maps:
            return {"ok": False, "dir": str(root), "maps": [], "error": "Клиент не найден. Проверены Steam, лаунчер EXBO и запущенная игра. Свой путь запиши в map_dir.txt"}
        return {
            "ok": True,
            "dir": str(root),
            "maps": [{"slug": item["slug"], "title": item["title"], "count": item["count"]} for item in maps],
        }

    def pda_map(self, slug):
        root = pda.map_root(agent.DIR)
        found = {item["slug"]: item for item in pda.list_maps(root)}
        item = found.get(str(slug or ""))
        if not item:
            return {"error": "Нет такой карты в папке ПДА"}
        try:
            pack = pda.prepare(item["dir"], agent.DIR / "pda_cache" / item["slug"])
        except Exception as error:
            self.note("ПДА: " + str(error))
            return {"error": str(error)}
        pack.update({
            "local": True,
            "slug": item["slug"],
            "title": item["title"],
            "count": len(pack["tiles"]),
            "mine": self._marks_of(item["slug"]),
            "areas": [],
            "groups": [],
        })
        self.note(f"Карта {item['title']}: {pack['count']} кусков с диска")
        return pack

    def _map_slugs(self):
        names = {"south-zone", "north-zone", "wild-north", "lyubech", "labyrinth", "graveyard"}
        try:
            names.update(item["slug"] for item in pda.list_maps(pda.map_root(agent.DIR)))
        except Exception:
            pass
        return names

    def add_mark(self, slug, lat, lng, title):
        slug = str(slug or "").strip()
        if not slug or len(slug) > 48 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in slug):
            return []
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            return self._marks_of(slug)
        title = str(title or "").strip()[:80] or "Метка"
        rows = self._load_marks()
        rows.append({
            "id": str(int(time.time() * 1000)),
            "slug": slug,
            "lat": lat,
            "lng": lng,
            "title": title,
        })
        self._write_json("wiki_marks.json", rows)
        self.note("Метка: " + title)
        return self._marks_of(slug)

    def delete_mark(self, slug, mark_id):
        mark_id = str(mark_id or "")
        rows = [mark for mark in self._load_marks() if str(mark.get("id")) != mark_id]
        self._write_json("wiki_marks.json", rows)
        return self._marks_of(str(slug or ""))

    def lunar_catalog(self):
        try:
            return lunar.catalog()
        except Exception as error:
            self.note("Карты Лунара: " + str(error))
            return []

    def lunar_map(self, slug):
        slug = str(slug or "").strip()
        try:
            pack = lunar.load(agent.DIR, slug)
        except Exception as error:
            self.note("Карта не загрузилась: " + str(error))
            return {"error": str(error)}
        pack["mine"] = self._marks_of(slug)
        self.note(f"Карта {pack['title']}: {len(pack['markers'])} меток")
        return pack

    def _read_json(self, name):
        path = agent.DIR / name
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_json(self, name, data):
        (agent.DIR / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def note(self, msg):
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-80:]
            self.status = str(msg)[:240]

    def _show(self, data):
        if "buys" in data:
            seen = []
            for r in data.get("buys") or []:
                slug = r.get("slug")
                if slug and slug not in seen:
                    seen.append(slug)
            if seen:
                self.watch = seen
        fresh = rows_from(data)
        with self.lock:
            self.tables.update(fresh)
            if 'buys' in data:
                deals = list(data.get('buys') or [])
                self._compact = [{
                    'name': r['name'],
                    'price': r.get('plan') or money(r['buyout']),
                    'gain': money(r['gain']),
                    'gain_n': float(r.get('gain') or 0),
                    'hour': money(r.get('hour_gain') or 0),
                    'hour_n': float(r.get('hour_gain') or 0),
                    'copies': r['copies'],
                } for r in deals]
            self.rev += 1

    def hud_action(self, action):
        return self._hud.command(action) if self._hud else {'ok': False}

    def boot(self):
        saved = "5000000"
        path = agent.DIR / "flip_budget.txt"
        if path.exists():
            saved = path.read_text(encoding="utf-8").strip() or saved
        return {
            "budget": saved,
            "sections": [name for name, _key in SECTIONS],
            "cats": [{"key": key, "title": title} for key, title in agent.AUCTION_CATS],
            "qlt": ["Все", *agent.QLT],
            "columns": TABLES,
            "icons": stalzone_db.appearance(agent.DIR / "items.db"),
            "license": lic.status(),
        }

    def poll(self):
        with self.lock:
            catalog = self._catalog_payload
            self._catalog_payload = None
            return {
                "status": self.status,
                "busy": self.busy,
                "logs": list(self.logs),
                "tables": self.tables,
                "rev": self.rev,
                "compact": list(self._compact),
                "catalog": catalog,
                "hud": self._hud.snapshot() if self._hud else {},
                "license": lic.status(),
            }

    def _budget(self, text):
        try:
            value = agent.parse_money(text)
        except Exception:
            value = 5_000_000
        try:
            (agent.DIR / "flip_budget.txt").write_text(str(value), encoding="utf-8")
        except Exception:
            pass
        return value

    def _set_busy(self, on):
        with self.lock:
            self.busy = on

    def start_run(self, auto, minutes, budget, section):
        with self._launch_lock:
            return self._start_run(auto, minutes, budget, section)

    def license_activate(self, key):
        result = lic.activate(key)
        if result.get("active"):
            who = "владелец, безлимит" if result.get("role") == "owner" else f"{result.get('days_left')} дн."
            self.note("Подписка открыта: " + who)
        else:
            self.note(result.get("reason") or "Ключ не подошёл")
        return result

    def license_drop(self):
        agent.HALT.set()
        result = lic.drop()
        self.note("Подписка отключена")
        return result

    def license_buy(self):
        url = (lic.BUY_URL or "").strip()
        if not url:
            return {"ok": False, "reason": "Ссылка на покупку ещё не задана"}
        import webbrowser
        webbrowser.open(url)
        return {"ok": True}

    def _start_run(self, auto, minutes, budget, section):
        seat = lic.status()
        if not seat.get("active"):
            self.note(seat.get("reason") or "Нужен ключ подписки")
            return {"ok": False, "error": seat.get("reason") or "Нужен ключ подписки"}
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "Уже идёт"}
        try:
            mins = max(1, int(minutes))
        except (TypeError, ValueError):
            mins = 30
        only = dict(SECTIONS).get(section or "Общий")
        if only != "buys":
            mins = max(5, mins)
        agent.HALT.clear()
        self._set_busy(True)
        title = section or "Общий"
        self.note(("Автопрогон: " if auto else "Прогон: ") + title)
        money_budget = self._budget(budget)
        self.worker = threading.Thread(target=self._job, args=(bool(auto), mins, only, money_budget), daemon=True)
        self.worker.start()
        return {"ok": True}

    def stop_run(self):
        agent.HALT.set()
        self.note("Стоп")
        return {"ok": True}

    def game_search(self, name):
        name = " ".join(str(name or "").split())
        if len(name) < 2 or name.startswith("Прогон найдёт"):
            return {"ok": False}
        if not self._search_lock.acquire(blocking=False):
            return {"ok": False, "error": "Уже ввожу в поиск"}
        threading.Thread(target=self._game_search, args=(name,), daemon=True).start()
        return {"ok": True}

    def _game_search(self, name):
        try:
            self.note("Вбиваю в аукцион: " + name)
            if self._hud:
                self._hud.command("passive")
            time.sleep(0.45)
            from stalzone_game_search import search_item
            error = search_item(agent.DIR / "screen_slots.json", name)
            self.note(error or ("В поиске: " + name))
        except Exception as error:
            self.note("Поиск в игре не сработал: " + str(error))
        finally:
            self._search_lock.release()

    def start_live(self, budget):
        with self._launch_lock:
            return self._start_live(budget)

    def _start_live(self, budget):
        seat = lic.status()
        if not seat.get("active"):
            self.note(seat.get("reason") or "Нужен ключ подписки")
            return {"ok": False, "error": seat.get("reason") or "Нужен ключ подписки"}
        items = [i for i in self.auction if i["id"] in self.fav][:25]
        if not items and self.watch:
            by_id = {i["id"]: i for i in self.auction}
            items = [by_id[slug] for slug in self.watch if slug in by_id][:25]
        if not items:
            self.note("Онлайн следит за избранным или за текущим выкупом. Отметь предметы или дождись первого прогона.")
            return {"ok": False}
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "Уже идёт"}
        self.note(f"Онлайн, предметов {len(items)}")
        agent.HALT.clear()
        self._set_busy(True)
        self.worker = threading.Thread(target=self._live_job, args=(items, self._budget(budget)), daemon=True)
        self.worker.start()
        return {"ok": True}

    def _live_job(self, items, budget):
        try:
            while not agent.HALT.is_set():
                deals = []
                for it in items:
                    if agent.HALT.is_set():
                        break
                    try:
                        agent.drop_market(it["id"])
                        book = agent.market_book(it["id"], 1)
                        single = it.get("cat") not in ("other", "misc", "supply", "bullet", "medicine")
                        deals.extend(agent._as_buys(agent.find_flips(book, it["id"], it["name"], allow_single=single or it.get("cat") == "artefact")))
                    except Exception as e:
                        self.note(f"{it['name']}: {e}")
                    shown = agent.fit_budget(deals, budget)
                    self._show({"buys": shown})
                    self.note(f"Онлайн: {it['name']}, в таблице {len(shown)}")
                for _ in range(3):
                    if agent.HALT.is_set():
                        break
                    time.sleep(1)
            self.note("Онлайн остановлен")
        finally:
            self._set_busy(False)

    def _job(self, auto, mins, only, budget):
        try:
            while not agent.HALT.is_set():
                self.note("Читаю цены")
                try:
                    def on_update(deals, done, total):
                        self._show({"buys": list(deals)})
                        self.note(f"Выкуп {done}/{total}, в таблице {len(deals)}")
                    data = agent.run_once(status=self.note, only=only, budget=budget, on_update=on_update if only == "buys" else None, favs=sorted(self.fav))
                except Exception as e:
                    self.note(f"Ошибка: {e}")
                    data = {}
                if agent.HALT.is_set():
                    self.note("Прогон остановлен")
                    break
                self._show(data or {})
                n = len((data or {}).get("buys") or [])
                self.note("Готово" if only else f"Готово. Выкупать позиций: {n}")
                if not auto:
                    break
                self.note(f"Дальше цены выкупа обновляются сразу, полный круг через {mins} мин")
                deadline = time.time() + mins * 60
                while time.time() < deadline and not agent.HALT.is_set():
                    slugs = list(self.watch)
                    if slugs and only == "buys":
                        fresh = self._refresh(slugs, budget)
                        self._show({"buys": fresh})
                        spent = sum(r["spend"] for r in fresh)
                        self.note(f"Сейчас: {len(fresh)} лотов, вложено {agent.rub(spent)}")
                    for _ in range(12):
                        if agent.HALT.is_set() or time.time() >= deadline:
                            break
                        time.sleep(1)
                if agent.HALT.is_set():
                    self.note("Автопрогон остановлен")
                    break
        finally:
            self._set_busy(False)

    def _refresh(self, slugs, budget):
        by_id = {i["id"]: i for i in self.auction}
        stack_cats = {"other", "misc", "supply", "bullet", "medicine"}
        deals = []
        for slug in slugs:
            if agent.HALT.is_set():
                break
            info = by_id.get(slug) or {"id": slug, "name": slug, "cat": ""}
            try:
                agent.drop_market(slug)
                book = agent.market_book(slug, 1)
                single = info.get("cat") not in stack_cats
                deals.extend(agent._as_buys(agent.find_flips(book, slug, info.get("name") or slug, allow_single=single)))
            except Exception as e:
                self.note(f"{info.get('name') or slug}: {e}")
        return agent.fit_budget(deals, budget)

    def load_catalog(self):
        with self.lock:
            if self._catalog_busy:
                return {"ok": True, "pending": True, "items": []}
            self._catalog_busy = True
        self.note("Открываю каталог")
        threading.Thread(target=self._catalog_job, daemon=True).start()
        return {"ok": True, "pending": True, "items": []}

    def _catalog_job(self):
        try:
            items = agent.auction_listing(status=self.note)
            self.auction = items
            payload = {
                "ok": True,
                "items": [
                    {
                        "id": i["id"],
                        "name": i["name"],
                        "cat": i["cat"],
                        "color": i.get("color") or "DEFAULT",
                        "icon": stalzone_db.icon_url(i.get("icon")),
                        "rank": agent.RANK_NAME.get(i.get("color"), i.get("color") or ""),
                        "order": agent.RANK_ORDER.get(i.get("color"), 9),
                    }
                    for i in items
                ],
                "favs": sorted(self.fav),
                "recent": list(self.recent),
            }
            self.note(f"Каталог: {len(items)} предметов")
        except Exception as e:
            payload = {"ok": False, "error": str(e), "items": []}
            self.note(f"Каталог не загрузился: {e}")
        with self.lock:
            self._catalog_payload = payload
            self._catalog_busy = False

    def toggle_fav(self, slug):
        if not slug:
            return {"fav": False}
        if slug in self.fav:
            self.fav.remove(slug)
            self.note("Убрано из избранного")
            on = False
        else:
            self.fav.add(slug)
            self.note("Добавлено в избранное")
            on = True
        self._write_json("auction_fav.json", sorted(self.fav))
        return {"fav": on, "ids": sorted(self.fav)}

    def ledger(self):
        try:
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_add(self, name, buy, sell, qty=None, qlt="", ptn=""):
        try:
            count = None if qty in (None, "") else int(float(qty))
            created = book.add(name, int(float(buy or 0)), int(float(sell or 0)), count, qlt=qlt, ptn=ptn)
            self.note(("В учёте: " if created else "Уже в учёте сегодня: ") + str(name))
            snap = book.snapshot()
            snap["created"] = created
            return snap
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_hand(self, name, buy, sell, qty=None, qlt="", ptn=""):
        try:
            count = None if str(qty or "").strip() == "" else int(agent.parse_money(qty))
            sold = agent.parse_money(sell) if str(sell or "").strip() else 0
            book.add(str(name or "").strip(), agent.parse_money(buy), sold, count, hand=True, qlt=qlt, ptn=ptn)
            self.note("Своя позиция: " + str(name))
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_mark(self, row_id, qlt, ptn):
        try:
            book.set_mark(row_id, qlt, ptn)
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_name(self, row_id, name):
        try:
            book.set_name(row_id, name)
            self.note("Название обновлено")
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_buy(self, row_id, text):
        try:
            book.set_buy(row_id, agent.parse_money(text))
            self.note("Покупка обновлена")
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_sell(self, row_id, text):
        raw = str(text or "").strip()
        try:
            book.set_sell(row_id, None if not raw else agent.parse_money(raw))
            self.note("Продажа обновлена")
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_qty(self, row_id, text):
        raw = str(text or "").strip()
        try:
            book.set_qty(row_id, None if not raw else agent.parse_money(raw))
            snap = book.snapshot()
            row = next((item for item in snap["rows"] if item["id"] == str(row_id)), None)
            self.note("Количество обновлено" if row and row.get("hand") else "Количество обновлено, суммы пересчитаны")
            return snap
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def ledger_remove(self, row_id):
        try:
            book.remove(row_id)
            self.note("Строка убрана из учёта")
            return book.snapshot()
        except Exception as error:
            self.note(str(error))
            return {"ok": False, "error": str(error), "rows": [], "gain": 0, "today_gain": 0}

    def favs(self):
        return {"ids": sorted(self.fav), "recent": list(self.recent)}

    def cat_keys(self):
        return {key: sorted(names) for key, names in agent.AUCTION_CAT_KEYS.items()}

    def open_item(self, slug, name, qname, lo, hi):
        if not slug:
            return {"ok": False, "error": "Выбери предмет слева"}
        with self._item_lock:
            self._item_generation += 1
            generation = self._item_generation
            self.open_slug = slug
            self.lot_data = None
        self.recent = [slug] + [x for x in self.recent if x != slug]
        self.recent = self.recent[:30]
        self._write_json("auction_recent.json", self.recent)
        self.note(f"{name}: читаю лоты…")
        try:
            data = agent.item_view(slug, name or "")
        except Exception as e:
            self.note(f"Ошибка: {e}")
            return {"ok": False, "error": str(e)}
        payload = self._lots_payload(name, data, qname, lo, hi)
        with self._item_lock:
            if generation != self._item_generation:
                return {"ok": False, "error": "Выбран другой предмет"}
            self.lot_data = data
        return payload

    def filter_open(self, qname, lo, hi):
        if not self.lot_data:
            return {"ok": False}
        return self._lots_payload("", self.lot_data, qname, lo, hi)

    def _pass(self, row, qname, lo, hi):
        if qname and qname != "Все" and row["qname"] != qname:
            return False
        try:
            lo_n = int(lo)
            hi_n = int(hi)
        except (TypeError, ValueError):
            lo_n, hi_n = 0, 15
        if row["qlt"] is not None and not lo_n <= row["ptn"] <= hi_n:
            return False
        return True

    def _lots_payload(self, name, data, qname, lo, hi):
        lots = [r for r in data["lots"] if self._pass(r, qname, lo, hi)]
        sales = [r for r in data["sales"] if self._pass(r, qname, lo, hi)]
        lot_rows = []
        for r in lots:
            buy = money(r["buyout"]) if r["buyout"] else "—"
            unit = f"{r['unit']:.0f}" if r["unit"] else "—"
            start = money(r["start"]) if r["start"] else "—"
            ptn = f"+{r['ptn']}" if r["qlt"] is not None else "—"
            tag = f"q{r['qlt']}" if r["qlt"] is not None else ("buy" if r["buyout"] else "skip")
            lot_rows.append({"cells": [r["qname"], ptn, r["amount"], start, buy, unit, r["left"]], "tag": tag})
        sale_rows = []
        for r in sales:
            ptn = f"+{r['ptn']}" if r["qlt"] is not None else "—"
            tag = f"q{r['qlt']}" if r["qlt"] is not None else "skip"
            sale_rows.append({"cells": [r["time"], r["qname"], ptn, r["amount"], money(r["price"]), f"{r['unit']:.0f}"], "tag": tag})
        priced = [r["unit"] for r in lots if r["unit"]]
        cheap = min(priced) if priced else 0
        info = f"На аукционе {data['total']}, показано {len(lots)}. "
        info += f"Самый дешёвый выкуп {money(cheap)} за штуку." if cheap else "С выкупом ничего нет."
        if data.get("verdict"):
            info += " " + data["verdict"]
        if name:
            info = f"{name}: {info}"
            self.note(info)
        try:
            with self._stats_lock:
                stats = agent.auction_price_stats(data, qname, lo, hi)
            if stats["count"]:
                summary = (f"Средняя: {money(stats['mean'])} ₽/шт · "
                           f"Медиана: {money(stats['median'])} ₽/шт · "
                           f"Сделок: {stats['count']} · До 100 последних продаж за 7 дней")
                if stats["count"] < 5:
                    summary += " · Малая выборка"
                if stats["truncated"]:
                    summary += " · Неполная история: достигнут предел загрузки"
            else:
                summary = "Нет продаж за 7 дней для выбранных фильтров"
                if stats["truncated"]:
                    summary = "В загруженной части истории нет продаж для выбранных фильтров · Неполная история"
        except Exception:
            stats = None
            summary = "Статистика недоступна: не удалось загрузить историю"
        best = min((r for r in lots if r.get("buyout")), key=lambda r: r["unit"] or r["buyout"], default=None)
        mean = int(stats["mean"]) if stats and stats.get("count") else 0
        delta = ""
        if best and mean and best.get("unit"):
            delta = f"{round((best['unit'] - mean) / mean * 100):+d}% от средней"
        card = {
            "price": int(best["buyout"]) if best else 0,
            "unit": int(best["unit"]) if best else 0,
            "text": money(best["buyout"]) if best else "—",
            "left": best["left"] if best else "—",
            "qname": best["qname"] if best else "",
            "ptn": f"+{best['ptn']}" if best and best["qlt"] is not None else "",
            "amount": int(best["amount"]) if best else 0,
            "count": int(stats["count"]) if stats else 0,
            "mean": mean,
            "mean_text": money(mean) if mean else "—",
            "delta": delta,
            "verdict": data.get("verdict") or "",
        }
        return {"ok": True, "info": info, "lots": lot_rows, "sales": sale_rows,
                "stats": stats, "summary": summary, "card": card}


PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<title>STALZONE</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --bg: #080d11;
    --side: #0b1115;
    --card: #151b1f;
    --card-2: #192126;
    --line: #273037;
    --green: #55cf4d;
    --green-dim: rgba(28, 76, 38, .32);
    --orange: #f4c51d;
    --ink: #ebebec;
    --dim: #8c9297;
    --buy: #8dcdf2;
    --sell: #65d66a;
    --hold: #f4c51d;
    --skip: #767d82;
    --gold: #55cf4d;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: #d6d8da; font: 14px/1.4 "Segoe UI", Arial, sans-serif; }
  button, select, input { font: inherit; color: inherit; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: default; }
  button.gold, .primary-btn { background: linear-gradient(#2abf4e, #168732); color: #f4fff6; font-weight: 700; border: 1px solid #45cf5f; border-radius: 9px; }
  button.stop, .stop-btn, #bookbox button.drop, #ask-yes { background: linear-gradient(#e52f3e, #bd1f2d); color: #fff; border: 1px solid #e74550; border-radius: 9px; padding: 8px 12px; }
  body { display: flex; flex-direction: column; overflow: hidden; }
  header.compact-head { display: flex; gap: 8px; align-items: center; padding: 8px 12px; flex-shrink: 0; border-bottom: 1px solid #263039; background: #0c1216; }
  header.compact-head h1 { margin: 0; font-size: 15px; letter-spacing: 0.08em; color: var(--green); }
  header.compact-head button { padding: 5px 9px; border: 1px solid #313b42; border-radius: 8px; background: #10161a; color: #e9eaeb; }
  #compact-status { margin-left: auto; color: var(--dim); font-size: 12px; max-width: 52%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #full { display: grid; flex: 1; min-height: 0; height: 100%; }
  #compact { display: flex; flex: 1; min-height: 0; flex-direction: column; padding: 0 12px 10px; gap: 8px; }
  #compact .sheet { flex: 1; min-height: 0; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
  #compact th, #compact td { padding: 8px; font-size: 12px; }
  #compact td:first-child { white-space: normal; }
  #compact td:nth-child(3), #compact td:nth-child(4) { color: var(--green); font-weight: 700; }
  .compact-actions { display: flex; gap: 6px; }
  .compact-brand { display: flex; align-items: center; gap: 8px; }
  .logo { width: 28px; height: 28px; display: grid; place-items: center; background: linear-gradient(135deg, #66db58, #38aa35); color: #09100b; font-weight: 800; }
  #hudhint { font-size: 11px; color: var(--dim); flex-shrink: 0; padding: 6px 12px; border-top: 1px solid #20282d; }
  button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--green); outline-offset: 2px; }
  .app-shell {
    min-height: 0; height: 100%; flex: 1;
    display: grid; grid-template: 74px 1fr / 0 1fr;
    transition: grid-template-columns .32s cubic-bezier(.22,.8,.3,1);
    background: radial-gradient(circle at 82% 0%, rgba(43, 74, 54, .08), transparent 28%), linear-gradient(135deg, #0b1115, #080d11);
  }
  .app-shell.menu-open { grid-template-columns: 220px 1fr; }
  .topbar { grid-column: 1 / -1; display: flex; align-items: center; gap: 10px; min-width: 0; overflow: hidden; border-bottom: 1px solid #263039; background: rgba(12, 18, 22, .95); box-shadow: 0 2px 14px #0008; }
  .brand { height: 100%; width: 220px; flex: 0 0 220px; display: flex; align-items: center; gap: 9px; padding: 0 14px; border-right: 1px solid #252d32; white-space: nowrap; }
  .brand-mark, .logwin .mark { width: 42px; height: 42px; flex: 0 0 42px; display: block; padding: 0; border: 0; border-radius: 0; overflow: hidden; background: #45df61 url("data:image/jpeg;base64,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") center/cover no-repeat; }
  .logwin .mark { width: 32px; height: 32px; flex: 0 0 32px; }
  .brand strong { color: #48ed61; font-size: 18px; font-weight: 800; }
  .brand em { color: #b4b7ba; font-style: normal; font-size: 16px; }
  .top-actions { display: flex; gap: 10px; flex: 0 0 auto; }
  .topbar button.primary-btn, .topbar button.outline-btn, .topbar button.stop-btn { display: flex; align-items: center; justify-content: center; gap: 8px; height: 45px; border-radius: 9px; font-size: 15px; font-weight: 700; color: #e9eaeb; white-space: nowrap; }
  .primary-btn { padding: 0 16px; }
  .outline-btn, button.ingame, .bar button, .tools button, .sub button, #ask-no { padding: 0 14px; border: 1px solid #303941; background: #12191e; color: #e9eaeb; border-radius: 9px; }
  .outline-btn.active, .outline-btn.on, .sub button.on, #mapbar button.on, #maplayers button.on { border-color: #22823b; color: #fff; background: #123522; }
  .stop-btn { padding: 0 16px; }
  .stop-btn b { width: 15px; height: 15px; background: #f3f3f3; border-radius: 1px; }
  .settings { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); height: 42px; flex: 1; min-width: 0; }
  .setting { min-width: 0; padding: 0 10px; overflow: hidden; border-left: 1px solid #20282d; display: flex; flex-direction: column; justify-content: center; gap: 2px; white-space: nowrap; }
  .setting small { color: #8c9297; font-size: 12px; }
  .setting span, .setting .mode-btn { display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; font-size: 14px; color: #e1e2e3; }
  .mode-btn { border: 0; background: transparent; padding: 0; color: #e1e2e3; }
  .settings input { width: 64px; padding: 0; border: 0; background: transparent; color: #e1e2e3; text-align: left; }
  .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px #4fc64a44; }
  .hud-actions { display: flex; gap: 6px; flex: 0 0 auto; padding-right: 12px; }
  .hud-actions button { width: 36px; height: 36px; padding: 0; border: 1px solid #313b42; border-radius: 8px; background: #10161a; color: #e9eaeb; font-size: 22px; line-height: 1; }
  .sidebar { width: 220px; border-right: 1px solid #242d32; padding: 12px 10px 18px; display: flex; flex-direction: column; min-height: 0; overflow: hidden; opacity: 0; transform: translateX(-100%); visibility: hidden; transition: transform .32s cubic-bezier(.22,.8,.3,1), opacity .22s ease, visibility 0s linear .32s; }
  .menu-open .sidebar { opacity: 1; transform: none; visibility: visible; transition-delay: 0s; }
  .tabs { display: flex; flex-direction: column; gap: 2px; overflow: auto; }
  .tabs button { width: 100%; height: 44px; display: flex; align-items: center; gap: 15px; padding: 0 13px; border: 1px solid transparent; border-radius: 8px; color: #b9bdc1; background: transparent; font-size: 16px; text-align: left; }
  .tabs button svg { flex: 0 0 auto; }
  .tabs button:hover { background: #111a1c; color: #e8e9e9; }
  .tabs button.on { border-color: #16742a; color: #3ee95b; background: #0e2b19; }
  .subscription-card { position: relative; margin-top: auto; display: flex; align-items: center; gap: 12px; padding: 14px; overflow: hidden; border: 1px solid #285e34; border-radius: 9px; background: linear-gradient(135deg, rgba(35, 82, 45, .38), rgba(15, 27, 21, .72)); }
  .subscription-icon { flex: 0 0 38px; width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid #34763f; border-radius: 8px; color: var(--green); background: rgba(42, 103, 52, .24); }
  .subscription-card small { display: block; color: #7e8982; font-size: 11px; text-transform: uppercase; letter-spacing: .8px; }
  .subscription-card strong { color: #d7ddd8; font-size: 14px; font-weight: 500; }
  .stage { min-width: 0; min-height: 0; display: flex; flex-direction: column; padding: 15px 23px 16px 21px; }
  #screen-title { margin: 0; font-size: 36px; line-height: 1.2; font-weight: 600; color: #ebebec; letter-spacing: -.7px; }
  #screen-title:empty { display: none; }
  .rule { height: 2px; margin: 7px 0 13px; background: #20282d; flex: 0 0 2px; }
  #stats { display: none; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 0; }
  body[data-screen="buys"] #stats { display: grid; }
  .stat { height: 92px; border: 1px solid #293238; border-radius: 11px; background: linear-gradient(145deg, #192126, #151b1f); display: flex; align-items: center; gap: 12px; padding: 14px; color: var(--green); box-shadow: inset 0 1px rgba(255,255,255,.025), 0 3px 9px #0003; }
  .stat svg { flex: 0 0 auto; }
  .stat div { display: flex; flex-direction: column; min-width: 0; }
  .stat span { color: #a9adb1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .stat b { font-weight: 500; font-size: 28px; line-height: 1.15; color: inherit; }
  .stat.yellow { color: #f4c51d; }
  #main { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
  .view { display: none; min-height: 0; }
  .view.on { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .page { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 10px; }
  .page-head h2 { display: none; }
  .page-head p, .found { margin: 4px 0 0; color: var(--dim); }
  .sheet { flex: 1; min-height: 0; overflow: auto; background: rgba(18, 24, 28, .62); border: 1px solid #273037; border-radius: 11px; }
  .lots.panel { border: 0; background: transparent; box-shadow: none; }
  .lots { min-height: 0; flex: 1; display: flex; flex-direction: column; border: 1px solid #273037; border-radius: 11px; overflow: hidden; background: rgba(18, 24, 28, .62); }
  .table-head { height: 40px; flex: 0 0 40px; display: grid; grid-template-columns: 21% 23% 22% 22% 12%; align-items: center; padding: 0 23px; border-bottom: 1px solid #263037; color: #afb3b6; font-size: 12px; letter-spacing: .6px; }
  .table-head span:last-child { text-align: right; }
  .lots-list { min-height: 0; overflow: auto; flex: 1; }
  .lot-row { min-height: 62px; display: grid; grid-template-columns: 21% 23% 22% 22% 12%; align-items: center; padding: 0 23px; border-bottom: 1px solid #242e33; background: linear-gradient(90deg, rgba(25, 35, 31, .38), rgba(14, 20, 24, .18)); cursor: pointer; }
  .lot-row:hover { background: linear-gradient(90deg, rgba(47, 84, 51, .3), rgba(20, 29, 33, .5)); }
  .lot-row.purchased { opacity: .52; }
  .lot-row.purchased .lot-name strong { text-decoration: line-through; }
  .buy-check input { position: absolute; opacity: 0; pointer-events: none; }
  .buy-check > i { width: 21px; height: 21px; display: grid; place-items: center; border: 1px solid #465259; border-radius: 5px; color: transparent; background: #11181c; }
  .buy-check > i span { font-size: 14px; font-style: normal; font-weight: 700; }
  .buy-check input:checked + i { color: #071009; border-color: var(--green); background: var(--green); }
  .lot-name { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .lot-name > span { display: flex; flex-direction: column; min-width: 0; }
  .lot-name strong { overflow: hidden; color: #d8dddf; font-size: 14px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
  .lot-name small { margin-top: 3px; color: #707b80; font-size: 10px; letter-spacing: .4px; }
  .item-gem { width: 30px; height: 30px; flex: 0 0 30px; border: 1px solid currentColor; border-radius: 8px; display: grid; place-items: center; overflow: hidden; }
  .item-gem img { width: 22px; height: 22px; object-fit: contain; }
  .item-gem.master { color: #e07a7a; background: rgba(224, 122, 122, .22); }
  .item-gem.veteran { color: #c4a3ff; background: rgba(196, 163, 255, .22); }
  .item-gem.stalker { color: #8ebfff; background: rgba(142, 191, 255, .22); }
  .item-gem.newbie { color: #9ddeaf; background: rgba(157, 222, 175, .22); }
  .item-gem.legend { color: #e0b15a; background: rgba(224, 177, 90, .24); }
  .item-gem.common { color: #f4f1ea; background: rgba(244, 241, 234, .2); }
  .item-gem.quest { color: #d7c16e; background: rgba(215, 193, 110, .2); }
  td.named { display: flex; align-items: center; gap: 8px; }
  .price { color: #8dcdf2; font-size: 14px; }
  .profit { display: flex; flex-direction: column; width: fit-content; color: #65d66a; font-size: 14px; }
  .profit > i { width: 65px; height: 3px; margin-top: 5px; overflow: hidden; border-radius: 3px; background: #263138; }
  .profit > i b { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #329c3c, #6add60); }
  .hourly { justify-self: end; padding: 5px 9px; border: 1px solid #2b4935; border-radius: 12px; color: #73d978; background: rgba(48, 101, 55, .18); font-size: 12px; }
  .lot-more { padding: 8px 23px 12px; color: var(--dim); border-bottom: 1px solid #242e33; display: flex; flex-wrap: wrap; gap: 8px 16px; }
  .empty { flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #767d82; min-height: 220px; }
  .empty h2 { margin: 8px 0 0; color: #bfc2c4; font-size: 22px; font-weight: 400; }
  .empty p { margin-top: 9px; color: #9a9fa3; font-size: 16px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 10px 12px; text-align: left; white-space: nowrap; border-bottom: 1px solid #242e33; }
  th { position: sticky; top: 0; background: #1a2226; color: #afb3b6; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; cursor: pointer; }
  tr:hover td { background: #172024; }
  .buy { color: var(--green); } .sell { color: var(--sell); } .hold { color: var(--orange); } .skip { color: var(--skip); }
  .q0 { color: #c8c2b8; } .q1 { color: #7dcea0; } .q2 { color: #5dade2; }
  .q3 { color: #c39bd3; } .q4 { color: #e07a7a; } .q5 { color: #f0d78c; }
  .RANK_LEGEND { color: #e0b15a; } .RANK_MASTER { color: #e07a7a; } .RANK_VETERAN { color: #c4a3ff; }
  .RANK_STALKER { color: #8ebfff; } .RANK_NEWBIE { color: #9ddeaf; } .DEFAULT { color: var(--ink); }
  .log { flex: 0 0 189px; margin-top: 13px; border: 1px solid #273037; border-radius: 11px; overflow: hidden; background: rgba(18, 24, 28, .62); display: flex; flex-direction: column; }
  body:not([data-screen="buys"]) .log { display: none; }
  .log-title { height: 37px; display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid #253037; }
  .log-title b { font-size: 16px; font-weight: 500; color: #e2e3e4; }
  .log-title span { color: #aeb2b5; font-size: 13px; display: flex; align-items: center; gap: 7px; }
  .log-lines { padding: 7px 17px; color: #b8bdc0; font-size: 14px; line-height: 26px; overflow: auto; }
  .log-lines mark { color: #5ed257; background: none; }
  .bookstats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
  #bookbox input.sell { width: 120px; text-align: right; }
  #bookbox input.qty, #bookbox input.buy { width: 110px; text-align: right; }
  #bookbox input.name { width: 220px; text-align: left; }
  .own { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .own input { width: 140px; text-align: left; }
  .namebox { position: relative; flex: 1 1 260px; min-width: 220px; }
  .namebox input { width: 100%; text-align: left; }
  .namelist { position: absolute; z-index: 40; top: calc(100% + 4px); left: 0; width: min(420px, 70vw); max-height: 240px; overflow: auto; background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
  .namelist button { display: block; width: 100%; text-align: left; background: transparent; border: 0; border-radius: 0; padding: 8px 12px; color: var(--ink); }
  .namelist button.on, .namelist button:hover { background: var(--green-dim); color: var(--green); }
  .own .cut { color: var(--dim); font-size: 13px; }
  .own .cut b { color: var(--ink); }
  input, select { background: #0e1211; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
  #q { width: 100%; text-align: left; }
  #ask { display: none; position: fixed; inset: 0; z-index: 5000; background: rgba(6, 8, 7, .72); align-items: center; justify-content: center; }
  #ask.on { display: flex; }
  #license { display: none; position: fixed; inset: 0; z-index: 4500; background: #080d11; align-items: center; justify-content: center; }
  #license.on { display: flex; }
  .lic-card { position: relative; width: min(380px, calc(100% - 32px)); display: flex; flex-direction: column; align-items: center; gap: 12px; background: #151b1f; border: 1px solid #273037; border-radius: 16px; padding: 28px 22px 20px; }
  .lic-card .brand-mark { width: 84px; height: 84px; }
  .lic-card strong { color: #48ed61; font: 800 22px Arial, sans-serif; letter-spacing: .14em; }
  .lic-card p, .lic-card small { margin: 0; color: #9aa3a8; text-align: center; }
  .lic-card input, #license-go, #license-buy { width: 100%; }
  #license-go { height: 44px; }
  #license-buy { height: 40px; border: 1px solid #303941; border-radius: 9px; background: #12191e; color: #e9eaeb; }
  #license-msg { min-height: 18px; color: #e07a7a; }
  #license-close { position: absolute; top: 12px; right: 12px; width: 36px; height: 36px; padding: 0; border: 1px solid #303941; border-radius: 9px; background: #12191e; color: #e9eaeb; font-size: 22px; line-height: 1; }
  #license-off { margin-top: 8px; height: 28px; padding: 0 10px; border: 1px solid #303941; border-radius: 8px; background: #12191e; color: #e9eaeb; }
  .ask-card { width: min(420px, calc(100% - 32px)); background: #151b1f; border: 1px solid #273037; border-radius: 16px; padding: 18px 18px 14px; }
  .ask-card p { margin: 0 0 16px; }
  .ask-actions { display: flex; justify-content: flex-end; gap: 8px; }
  #bookbox td.num { text-align: right; font-variant-numeric: tabular-nums; }
  #bookbox .plus { color: var(--green); }
  #bookbox .minus { color: #e07a7a; }
  #bookbox tr.tone-common { --frame: #f4f1ea; }
  #bookbox tr.tone-newbie { --frame: #9ddeaf; }
  #bookbox tr.tone-stalker { --frame: #8ebfff; }
  #bookbox tr.tone-veteran { --frame: #c4a3ff; }
  #bookbox tr.tone-master { --frame: #e07a7a; }
  #bookbox tr.tone-legend { --frame: #e0b15a; }
  #bookbox table { width: 100%; }
  #bookbox th, #bookbox td { padding: 8px 6px; overflow: visible; }
  #bookbox td.named { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; white-space: normal; min-width: 168px; }
  #bookbox td.named .nmline { display: flex; align-items: center; gap: 8px; max-width: 220px; }
  #bookbox td.named .nm { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  #bookbox select.qlt { width: 158px; }
  #bookbox input.ptn { width: 58px; }
  #bookbox input.qty { width: 56px; text-align: right; }
  #bookbox input.sell { width: 108px; text-align: right; }
  #bookbox input.buy, #bookbox input.name { width: 100%; min-width: 0; box-sizing: border-box; }
  #bookbox button.ingame { padding: 4px 8px; white-space: nowrap; }
  #bookbox button.drop, #ask-yes { padding: 6px 12px; white-space: nowrap; }
  #ask-no, #ask-yes { height: auto; padding: 8px 14px; }
  #bookbox tr[class*="tone-"] td { border-top: 0; border-left: 0; border-right: 0; border-bottom: 1px solid #242e33; }
  #bookbox tr[class*="tone-"] td:first-child { box-shadow: inset 4px 0 0 var(--frame); }
  button.ingame { height: auto; padding: 6px 10px; }
  body[data-screen="auc"] #screen-title, body[data-screen="auc"] .rule { display: none; }
  #v-auc { min-height: 0; }
  .auc-page { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
  .auc-intro { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
  .auc-intro small { color: #35e95a; font: 700 11px Arial, sans-serif; letter-spacing: 1.3px; }
  .auc-intro h1 { margin: 8px 0 4px; font-size: 32px; line-height: 1; font-weight: 600; }
  .auc-intro p { margin: 0; color: #80929e; font-size: 14px; }
  .auc-filter-btn { height: 43px; padding: 0 15px; border: 1px solid #29343b; border-radius: 9px; background: #121a1f; color: #e9eaeb; font-weight: 700; }
  .auc-filter-btn b { margin-left: 7px; padding: 4px 7px; border-radius: 5px; color: #48eb60; background: #0c3b1b; }
  .auc-search { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .auc-q { display: flex; align-items: center; gap: 10px; width: min(431px, 100%); height: 46px; padding: 0 14px; color: #637580; border: 1px solid #2b353c; border-radius: 9px; background: #11191e; }
  .auc-q input { width: 100%; border: 0; background: transparent; color: #dfe5e8; padding: 0; }
  .auc-q kbd { padding: 4px 6px; border: 1px solid #344049; border-radius: 4px; color: #9aafba; font-size: 11px; }
  .chip { height: 36px; padding: 0 14px; border: 1px solid #29343c; border-radius: 8px; color: #9cb0bc; background: #0c1318; }
  .chip.on { color: #fff; border-color: #22823b; background: #123522; }
  .auc-filterbox { display: none; grid-template-columns: 1.4fr 1fr 1fr .8fr; gap: 8px 12px; padding: 12px; border: 1px solid #2a353c; border-radius: 9px; background: #12191f; }
  .auc-filterbox.on { display: grid; }
  .auc-filterbox label { color: #80929e; font-size: 12px; }
  .auc-filterbox select, .auc-filterbox input { width: 100%; }
  .range { display: flex; gap: 8px; }
  .market { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(420px, 1.7fr) minmax(300px, 1fr); gap: 14px; }
  .catalog, .details { min-height: 0; display: flex; flex-direction: column; border: 1px solid #2a353c; border-radius: 9px; background: #12191f; }
  .catalog { overflow: hidden; }
  .details { overflow: auto; }
  .catalog-head { height: 64px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 16px; border-bottom: 1px solid #2a353c; }
  .catalog-head h2 { margin: 0; font-size: 17px; font-weight: 600; }
  .catalog-head small { color: #66808f; font-size: 12px; }
  #asort { width: auto; border: 0; background: transparent; color: #8798a3; padding: 0; }
  .columns { display: grid; grid-template-columns: 1fr 120px 110px; height: 34px; align-items: center; padding: 0 48px 0 18px; color: #60717c; font-size: 10px; letter-spacing: 1px; }
  .auc-lots { flex: 1; min-height: 0; overflow: auto; }
  .alot { display: grid; grid-template-columns: 46px minmax(0, 1fr) 110px 92px 16px; align-items: center; gap: 8px; width: calc(100% - 14px); min-height: 68px; margin: 0 7px; padding: 6px 8px; border: 1px solid transparent; border-radius: 9px; background: transparent; color: inherit; text-align: left; }
  .alot.on { border-color: #1f8e38; background: #0f2b1a; }
  .alot .item-copy, .alot .price { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .alot .item-copy b, .alot .price b { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .alot .item-copy small, .alot .price small, .alot .time { color: #78909d; font-size: 11px; }
  .alot .time { white-space: nowrap; }
  .alot .arrow { color: #46545c; font-size: 20px; }
  .alot.on .arrow { color: #33ee59; }
  .auc-tabs { height: 52px; display: flex; gap: 22px; align-items: end; padding: 0 16px; border-bottom: 1px solid #2a353c; }
  .auc-tabs button { height: 52px; padding: 0; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; color: #798b96; }
  .auc-tabs button.on { color: #eef2f3; border-bottom-color: #45e560; background: transparent; }
  .product { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 16px 14px 8px; }
  .product .shield { width: 64px; height: 64px; display: grid; place-items: center; }
  .product .shield .item-gem { width: 64px; height: 64px; border-radius: 15px; }
  .product .shield .item-gem img { width: 40px; height: 40px; }
  #detail-q { padding: 3px 8px; border: 1px solid #39434a; border-radius: 8px; color: #95a0a7; font-size: 11px; }
  .product h2 { margin: 4px 0 0; font-size: 20px; }
  .product p { margin: 0; color: #79919f; font-size: 12px; }
  .current-price { margin: 8px 14px; padding: 16px 14px; border: 1px solid #2a343a; border-radius: 12px; background: #0c1216; display: flex; flex-direction: column; gap: 6px; }
  .current-price small, .facts small { color: #77909c; font-size: 11px; }
  .current-price strong { font-size: 26px; }
  .current-price b { color: #30df55; font-size: 12px; font-weight: 600; }
  .current-price b.up { color: #ef4f60; }
  .facts { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #2a343a; border-bottom: 1px solid #2a343a; }
  .facts div { display: flex; flex-direction: column; gap: 4px; padding: 10px 14px; border-right: 1px solid #2a343a; }
  .facts b { font-size: 14px; }
  .offer { display: flex; flex-direction: column; gap: 4px; margin: 12px 14px 8px; padding: 11px; border: 1px solid #187533; border-radius: 8px; color: #3ae55a; background: #0e2c1a; }
  .offer small { color: #79a786; }
  #lotstats { color: #78909d; font-size: 12px; padding: 0 14px 8px; }
  #v-auc .buy { display: flex; justify-content: space-between; align-items: center; height: 40px; margin: 0 14px 10px; padding: 0 13px; border: 0; border-radius: 6px; color: #07110a; background: linear-gradient(90deg, #38e85a, #42d65c); font-weight: 700; }
  #v-auc .buy:disabled { opacity: .45; }
  #v-auc #detail-find { height: auto; margin: 0 14px; }
  #v-auc #lotbox { margin: 0 14px 12px; border: 0; background: transparent; }
  #v-auc #lotbox table { font-size: 12px; }
  tr.more td { white-space: normal; color: var(--dim); }
  tr.face { cursor: pointer; }
  #lotinfo { color: var(--ink); background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; }
  #lotstats { color: var(--dim); font-size: 13px; padding: 4px 2px 8px; }
  .sub { display: flex; gap: 6px; }
  .sub button { height: auto; padding: 8px 12px; }
  .tools { display: flex; gap: 8px; align-items: center; padding: 8px; flex-wrap: wrap; }
  .tools button, .bar button { height: auto; padding: 8px 12px; }
  .mapwrap { display: flex; flex-direction: column; height: 100%; min-height: 0; }

  #mapq { width: 180px; text-align: left; }
  #wikimap { flex: 1; min-height: 0; background: #0e0c0a; }
  #logwin { position: fixed; z-index: 4000; inset: 74px 0 0 0; display: none; align-items: center; justify-content: center; pointer-events: none; }
  #logwin.on { display: flex; }
  .logwin { pointer-events: auto; width: min(760px, calc(100% - 48px)); height: min(560px, calc(100% - 36px)); display: flex; flex-direction: column; overflow: hidden; border: 1px solid #273037; border-radius: 12px; background: #0c1216; box-shadow: 0 22px 60px #000c; }
  .logwin header { height: 58px; display: flex; align-items: center; gap: 10px; padding: 0 14px; border-bottom: 1px solid #263039; background: rgba(12,18,22,.98); }
  .logwin .mark { width: 32px; height: 32px; flex: 0 0 32px; }
  .logwin strong { color: var(--green); font-size: 16px; }
  .logwin em { color: #b4b7ba; font-style: normal; }
  .logwin .state { margin-left: auto; display: flex; align-items: center; gap: 8px; color: #aeb2b5; font-size: 13px; }
  .logwin button { width: 36px; height: 36px; padding: 0; border: 1px solid #303941; border-radius: 9px; background: #12191e; color: #e9eaeb; font-size: 22px; line-height: 1; }
  .logwin .log-lines { flex: 1; min-height: 0; overflow: auto; padding: 8px 16px 14px; color: #b8bdc0; font-size: 14px; line-height: 26px; }
  .logwin .log-lines p { margin: 0; }
  .logwin mark { color: #5ed257; background: none; }
  @media (max-width: 1100px) {
    .brand em, .topbar svg { display: none; }
    .stat b { font-size: 22px; }
    #screen-title { font-size: 28px; }
    .table-head, .lot-row { padding: 0 10px; }
  }
</style>
</head>
<body data-screen="buys" class="full">
<div id="ask"><div class="ask-card"><p id="ask-text"></p><div class="ask-actions"><button type="button" id="ask-no">Оставить</button><button type="button" id="ask-yes" class="stop">Убрать</button></div></div></div>
<div id="license" class="on"><form class="lic-card" onsubmit="return false"><button type="button" id="license-close" aria-label="Закрыть">×</button><div class="brand-mark"></div><strong>STALZONE</strong><p>Один ключ на одного человека. Срок идёт с первого входа и не останавливается, если выйти.</p><input id="license-key" placeholder="Ключ" autocomplete="off"/><button type="button" class="gold" id="license-go">Войти</button><button type="button" id="license-buy">Купить подписку</button><small id="license-msg"></small></form></div>
<div id="full" class="app-shell menu-open">
  <header class="topbar pywebview-drag-region">
    <div class="brand">
      <button type="button" class="brand-mark" id="menu-toggle" aria-label="Открыть меню"></button>
      <strong>STALZONE</strong>
    </div>
    <div class="top-actions">
      <button class="primary-btn" id="run"><svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg> Прогон</button>
      <button class="outline-btn" id="auto"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="5" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><path d="m10 7-3 8m7-8 3 8M9 18h6"/></svg> Автопрогон</button>
      <button class="outline-btn" id="live">Онлайн</button>
      <button class="stop-btn" id="stop" disabled><b></b> Стоп</button>
    </div>
    <div class="settings">
      <div class="setting"><small>Статус</small><span><i class="dot"></i> <em id="status">Онлайн</em></span></div>
      <div class="setting"><small>Интервал</small><span>каждые <input id="mins" value="30" inputmode="numeric"/> мин</span></div>
      <div class="setting budget-setting"><small>Бюджет</small><span><input id="budget" value="5кк" placeholder="5кк" title="Можно писать 5кк, 500к или 5000000"/></span></div>
      <div class="setting"><small>Режим</small><button class="mode-btn" id="orderswitch2" data-order type="button">По часу</button></div>
    </div>
    <div class="hud-actions">
      <button class="act-close" id="closehud" type="button" aria-label="Закрыть">×</button>
    </div>
  </header>
  <aside class="sidebar">
    <nav class="tabs" id="tabs"></nav>
    <div class="subscription-card">
      <div class="subscription-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></svg></div>
      <div><small>Подписка</small><strong id="side-status">нет ключа</strong><button type="button" id="license-off">Отключить</button></div>
    </div>
  </aside>
  <div class="stage">
    <h1 id="screen-title">Выкуп</h1>
    <div class="rule"></div>
    <section id="stats">
      <article class="stat"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></svg><div><span>Лотов в бюджете</span><b id="stat-count">0</b></div></article>
      <article class="stat"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m3 17 6-6 4 4 8-9M15 6h6v6"/></svg><div><span>Плюс</span><b id="stat-gain">0</b></div></article>
      <article class="stat"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 7h14a2 2 0 0 1 2 2v10H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h11"/><path d="M15 11h7v5h-7a2.5 2.5 0 0 1 0-5Z"/></svg><div><span>Бюджет</span><b id="stat-budget">5000000</b></div></article>
      <article class="stat yellow"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></svg><div><span>Рынок ждёт</span><b id="stat-live">ждёт</b></div></article>
    </section>
    <div id="main"></div>
  </div>
</div>
<div id="logwin">
  <section class="logwin" role="dialog" aria-label="Лог">
    <header>
      <span class="mark"></span>
      <strong>STALZONE</strong>
      <em>Лог</em>
      <span class="state"><i class="dot"></i> <em id="log-state">Онлайн</em></span>
      <button id="log-close" type="button" aria-label="Закрыть лог">×</button>
    </header>
    <div class="log-lines" id="log"></div>
  </section>
</div>
<script>
const TAB_ORDER = ["buys","farm","arsenal","shelter_buy","shelter_sell","consumables","arts","protos"];
const TAB_BLURB = {
  buys: "Что купить и за сколько выставить. Плюс уже после 5%. Отметь «купил» — строка ляжет в учёт.",
  farm: "Дорогой бартер: держать или слить.",
  arsenal: "Арсенал. Цена, от которой есть смысл продавать.",
  shelter_buy: "Материалы убежища, которые ещё имеет смысл брать.",
  shelter_sell: "Готовое с убежища. Слить или подождать.",
  consumables: "Еда, хилки и бафы.",
  arts: "Популярные арты по той же цене, что и выкуп.",
  protos: "Протоартефакты, если после комиссии есть запас."
};
const TAB_NAME = {buys:"Выкуп", farm:"Фарм", arsenal:"Арсенал", shelter_buy:"Убежище купить", shelter_sell:"Убежище продать", consumables:"Расходники", arts:"Арты", protos:"Протоартефакты"};
const state = {columns:{}, tables:{}, rev:-1, sort:{}, detailRequest:0, catalog:[], fav:new Set(), recent:[], lot:"now", mapOpened:false, mapBooted:false, local:false, mapSlug:"south-zone", wiki:null, pack:null, marks:null, mine:[], placing:false, hidden:{}, icons:{}, order:"gain", openBuy:"", openRow:"", book:[], bookPath:"", picked:new Set(), buyDeals:{}, byName:new Map()};
const TAB_ICON = {buys:"cart", book:"clipboard", farm:"sprout", arsenal:"shield", shelter_buy:"home", shelter_sell:"home", consumables:"capsule", arts:"diamond", protos:"flask", auc:"gavel", map:"pin", log:"log"};
const $ = (id) => document.getElementById(id);
const RANK_TONE = {RANK_LEGEND:"legend", RANK_MASTER:"master", RANK_VETERAN:"veteran", RANK_STALKER:"stalker", RANK_NEWBIE:"newbie", DEFAULT:"common", QUEST_ITEM:"quest"};
const Q_TONE = ["common", "newbie", "stalker", "veteran", "master", "legend"];
const Q_BY_NAME = {"Обычный":"q0","Необычный":"q1","Особый":"q2","Редкий":"q3","Исключительный":"q4","Легендарный":"q5"};
function rarityTag(text) {
  return Q_BY_NAME[String(text || "").trim()] || "";
}
function rememberItems(items) {
  (items || []).forEach(item => {
    if (!item) return;
    if (item.name) state.byName.set(item.name, item);
    if (item.id) state.byName.set(item.id, item);
  });
}
function baseName(name) {
  return String(name || "").split(",")[0].trim();
}
function knownItem(name) {
  return state.byName.get(baseName(name)) || state.byName.get(name) || {};
}
function toneOf(name, tag) {
  const quality = /^q(\d)$/.exec(tag || "");
  if (quality) return Q_TONE[Number(quality[1])] || "common";
  return RANK_TONE[knownItem(name).color] || "common";
}
function gem(name, tag, iconUrl) {
  const src = iconUrl || knownItem(name).icon || "";
  const img = src ? `<img src="${esc(src)}" alt="" onerror="this.remove()">` : "";
  return `<b class="item-gem ${toneOf(name, tag)}">${img}</b>`;
}
const ICONS = {
  cart: '<circle cx="9" cy="20" r="1"/><circle cx="19" cy="20" r="1"/><path d="M3 4h3l2.4 11.5a2 2 0 0 0 2 1.5h7.7a2 2 0 0 0 2-1.6L22 8H7"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5M9 9h6M9 13h6M9 17h4"/>',
  sprout: '<path d="M12 21V10M12 13C7 13 4 10 4 5c5 0 8 3 8 8ZM12 10c0-4 3-7 8-7 0 5-3 7-8 7Z"/>',
  shield: '<path d="M12 22s8-3 8-10V5l-8-3-8 3v7c0 7 8 10 8 10Z"/>',
  home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v11h14V10M9 21v-7h6v7"/>',
  capsule: '<path d="m8.5 19.5-4-4a4.2 4.2 0 0 1 0-6l5-5a4.2 4.2 0 0 1 6 0l4 4a4.2 4.2 0 0 1 0 6l-5 5a4.2 4.2 0 0 1-6 0Z"/><path d="m7 17 10-10"/>',
  diamond: '<path d="M3 9h18l-9 12L3 9Z"/><path d="m3 9 4-5h10l4 5M8 9l4 12 4-12"/>',
  flask: '<path d="M9 3h6M10 3v6l-5 10a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3L14 9V3"/>',
  gavel: '<path d="m14 5 5 5M12 7l5 5M5 20l7-7M3 21h10"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  log: '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  target: '<circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="9"/><path d="M12 3v4m0 10v4M3 12h4m10 0h4"/>'
};
function icon(name) {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
function tabButton(key, label, on) {
  const b = document.createElement("button");
  b.dataset.key = key;
  b.className = on ? "on" : "";
  b.innerHTML = icon(TAB_ICON[key] || "layers") + `<span>${label}</span>`;
  b.onclick = () => show(key);
  return b;
}

function prettyMoney(raw) {
  const text = String(raw ?? "").trim().toLowerCase().replace(/\s/g, "").replace(",", ".");
  let mult = 1;
  let body = text;
  if (body.endsWith("кк")) { mult = 1000000; body = body.slice(0, -2); }
  else if (body.endsWith("м")) { mult = 1000000; body = body.slice(0, -1); }
  else if (body.endsWith("к")) { mult = 1000; body = body.slice(0, -1); }
  const n = Number(body) * mult;
  if (!n || Number.isNaN(n)) return String(raw || "");
  if (n % 1000000 === 0) return String(n / 1000000) + "кк";
  if (n % 1000 === 0) return String(n / 1000) + "к";
  return String(Math.round(n));
}

function scanSection() {
  return TAB_NAME[document.body.dataset.screen || "buys"] || "Общий";
}

function rubShort(n) {
  n = Number(n) || 0;
  if (n >= 1000000) return (n / 1000000).toFixed(2) + "кк";
  if (n >= 1000) return (n / 1000).toFixed(1) + "к";
  return String(Math.round(n));
}

function compactRows(rows) {
  const list = (rows || []).slice().sort((a, b) => (state.order === "hour" ? (b.hour_n || 0) - (a.hour_n || 0) : (b.gain_n || 0) - (a.gain_n || 0))).slice(0, 5);
  return list.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.price)}</td><td>${esc(r.gain)}</td><td>${esc(r.hour || "")}</td></tr>`).join("") ||
    '<tr><td colspan="4">Прогон найдёт подходящие лоты</td></tr>';
}

function setOrder(mode) {
  state.order = mode;
  const hour = mode === "hour";
  document.querySelectorAll("[data-order]").forEach(b => { b.textContent = hour ? "По плюсу" : "По часу"; });
  state.sort.buys = {i: hour ? 10 : 7, desc: true};
  if ($("t-buys")) paint("buys");
}

function sortValue(text) {
  const raw = String(text ?? "").trim().replace(/ /g, "").replace(",", ".").toLowerCase();
  if (!raw || raw === "—" || raw === "-") return [1, 0, ""];
  let mult = 1, body = raw;
  if (body.endsWith("кк")) { mult = 1e6; body = body.slice(0, -2); }
  else if (body.endsWith("к")) { mult = 1e3; body = body.slice(0, -1); }
  const n = Number(body);
  if (!Number.isNaN(n)) return [0, n * mult, ""];
  const nums = raw.match(/\d+(?:\.\d+)?/g);
  if (nums) return [0, Math.max(...nums.map(Number)), raw];
  return [2, 0, raw];
}

function paint(key) {
  const box = $("t-" + key);
  if (!box) return;
  const cols = state.columns[key] || [];
  const rows = (state.tables[key] || []).slice();
  const rule = state.sort[key];
  if (rule) {
    rows.sort((a, b) => {
      const av = sortValue(a.cells[rule.i]);
      const bv = sortValue(b.cells[rule.i]);
      const c = av[0] - bv[0] || av[1] - bv[1] || String(av[2]).localeCompare(String(bv[2]), "ru");
      return rule.desc ? -c : c;
    });
  }
  if (key === "buys") {
    paintBuys(box, rows, rule);
    return;
  }
  const head = cols.map((c, i) => `<th data-i="${i}">${c}${rule && rule.i === i ? (rule.desc ? " ↓" : " ↑") : ""}</th>`).join("");
  const body = rows.map((r, index) => {
    const id = key + ":" + index;
    const name = r.cells[0] || "";
    const cells = r.cells.map((c, i) => i === 0
      ? `<td class="named">${gem(c, r.tag)}<span>${esc(c)}</span></td>`
      : `<td>${esc(c)}</td>`);
    const more = state.openRow === id
      ? `<tr class="more"><td colspan="${Math.max(cols.length, 1)}"><button type="button" class="ingame" data-name="${esc(name)}">Найти на аукционе</button></td></tr>`
      : "";
    return `<tr class="${r.tag || ""}" data-id="${esc(id)}">${cells.join("")}</tr>${more}`;
  }).join("");
  box.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  box.querySelectorAll("th").forEach(th => th.onclick = () => {
    const i = Number(th.dataset.i);
    const prev = state.sort[key];
    state.sort[key] = {i, desc: prev && prev.i === i ? !prev.desc : true};
    paint(key);
  });
  box.querySelectorAll("tbody tr[data-id]").forEach(tr => tr.onclick = () => {
    state.openRow = state.openRow === tr.dataset.id ? "" : tr.dataset.id;
    paint(key);
  });
  box.querySelectorAll("button.ingame").forEach(btn => btn.onclick = (event) => {
    event.stopPropagation();
    pywebview.api.game_search(btn.dataset.name);
  });
}

function paintBuys(box, rows, rule) {
  state.buyDeals = {};
  if (!rows.length) {
    box.innerHTML = `<div class="empty"><div class="target">${icon("target")}</div><h2>Прогон найдёт подходящие лоты</h2><p>Запустите прогон для поиска лотов в бюджете.</p></div>`;
    return;
  }
  box.innerHTML = rows.map(r => {
    const id = `${r.cells[0]}|${r.cells[4]}`;
    const open = state.openBuy === id;
    if (r.deal) state.buyDeals[id] = r.deal;
    const bought = r.deal && (state.book || []).some(row => row.today && row.name === r.deal.name && Number(row.buy) === Number(r.deal.buy));
    const roiText = String(r.cells[8] || "");
    const roiNum = Number((roiText.match(/(\d+(?:[.,]\d+)?)/) || [])[1]?.replace(",", ".")) || 0;
    const roi = Math.max(0, Math.min(100, roiNum));
    const bits = [[1, "Редкость"], [2, "Точка"], [3, "Лоты"], [5, "Пачка"], [6, "После 5%"], [8, "Рентабельность"], [9, "Продаж в час"], [11, "План"]]
      .filter(([i]) => r.cells[i] && r.cells[i] !== "—")
      .map(([i, name]) => `<div><b>${name}.</b> ${esc(r.cells[i])}</div>`).join("");
    const check = r.deal
      ? `<span class="buy-check"><input type="checkbox" class="got" data-key="${esc(id)}"${bought ? " checked" : ""}><i><span>✓</span></i></span>`
      : "<span></span>";
    const more = open ? `<div class="lot-more">${bits}<button type="button" class="ingame">Найти на аукционе</button></div>` : "";
    return `<div class="lot-wrap"><label class="lot-row ${bought ? "purchased" : ""}" data-id="${esc(id)}" data-name="${esc(r.cells[0])}">${check}<span class="lot-name">${gem(r.cells[0], r.tag)}<span><strong>${esc(r.cells[0])}</strong><small>ROI ${esc(roiText || "—")}</small></span></span><span class="price">${esc(r.cells[4])}</span><span class="profit">${esc(r.cells[7])}<i><b style="width:${roi}%"></b></i></span><span class="hourly">${esc(r.cells[10] || "")}</span></label>${more}</div>`;
  }).join("");
  box.querySelectorAll(".lot-row").forEach(row => row.onclick = (event) => {
    if (event.target.closest(".buy-check")) return;
    state.openBuy = state.openBuy === row.dataset.id ? "" : row.dataset.id;
    paint("buys");
  });
  box.querySelectorAll("input.got").forEach(input => {
    input.onclick = (event) => event.stopPropagation();
    input.onchange = async () => {
      const deal = state.buyDeals[input.dataset.key];
      if (!deal) return;
      if (!input.checked) { input.checked = true; return; }
      const res = await pywebview.api.ledger_add(deal.name, deal.buy, deal.sell, deal.qty, deal.qlt || "", deal.ptn || "");
      if (res && res.ok !== false) state.book = res.rows || [];
      if (!res || res.ok === false) input.checked = false;
      else paint("buys");
    };
  });
  box.querySelectorAll("button.ingame").forEach(btn => btn.onclick = (event) => {
    event.stopPropagation();
    const row = btn.closest(".lot-wrap").querySelector(".lot-row");
    pywebview.api.game_search(row ? row.dataset.name : "");
  });
}

function rubExact(n) {
  if (n == null || n === "") return "—";
  const sign = n < 0 ? "−" : "";
  return sign + Math.abs(Math.round(n)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function moneyOf(text) {
  let raw = String(text || "").trim().toLowerCase().replace(/\s/g, "").replace(/\u00a0/g, "");
  if (!raw) return null;
  let mult = 1;
  if (raw.endsWith("кк")) { mult = 1000000; raw = raw.slice(0, -2); }
  else if (raw.endsWith("м")) { mult = 1000000; raw = raw.slice(0, -1); }
  else if (raw.endsWith("к")) { mult = 1000; raw = raw.slice(0, -1); }
  raw = raw.replace(",", ".");
  const n = Number(raw.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * mult) : null;
}

function cutOf(sell, buy) {
  if (sell == null) return {net: null, gain: null};
  const net = Math.floor(sell * 95 / 100);
  return {net, gain: net - (buy || 0)};
}

function paintOwnList() {
  const input = $("own-name");
  const list = $("own-list");
  if (!input || !list) return;
  const query = input.value.trim().toLowerCase();
  if (!query) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  const seen = new Set();
  const pool = [];
  const push = (name, used) => {
    const title = String(name || "").trim();
    const key = title.toLowerCase();
    if (!title || seen.has(key) || !key.includes(query)) return;
    seen.add(key);
    pool.push({title, used, start: key.startsWith(query)});
  };
  (state.book || []).forEach(row => push(row.name, true));
  (state.catalog || []).forEach(item => push(item.name, false));
  pool.sort((a, b) => Number(b.start) - Number(a.start) || Number(b.used) - Number(a.used) || a.title.localeCompare(b.title, "ru"));
  const shown = pool.slice(0, 12);
  if (!shown.length) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  if (state.ownPick >= shown.length) state.ownPick = shown.length - 1;
  if (state.ownPick < 0) state.ownPick = 0;
  list.hidden = false;
  list.innerHTML = shown.map((item, index) => `<button type="button" class="${index === state.ownPick ? "on" : ""}" data-name="${esc(item.title)}">${esc(item.title)}</button>`).join("");
  list.querySelectorAll("button").forEach(btn => btn.onmousedown = (event) => {
    event.preventDefault();
    input.value = btn.dataset.name;
    list.hidden = true;
  });
}

function showCut(netNode, gainNode, sell, buy) {
  const cut = cutOf(sell, buy);
  if (netNode) netNode.textContent = rubExact(cut.net);
  if (!gainNode) return;
  gainNode.textContent = rubExact(cut.gain);
  gainNode.classList.toggle("plus", cut.gain != null && cut.gain >= 0);
  gainNode.classList.toggle("minus", cut.gain != null && cut.gain < 0);
}

function paintBook() {
  const box = $("bookbox");
  if (!box) return;
  const rows = state.book || [];
  let picked = 0;
  rows.forEach(row => {
    if (state.picked.has(row.id) && row.sell != null && row.gain != null) picked += Number(row.gain) || 0;
  });
  const total = rows.reduce((sum, row) => sum + (row.sell == null ? 0 : Number(row.gain) || 0), 0);
  const today = rows.reduce((sum, row) => sum + (row.today && row.sell != null ? Number(row.gain) || 0 : 0), 0);
  if ($("book-gain")) $("book-gain").textContent = rubExact(total);
  if ($("book-today-gain")) $("book-today-gain").textContent = rubExact(today);
  if ($("book-picked")) $("book-picked").textContent = rubExact(picked);
  const body = rows.map(row => {
    const on = state.picked.has(row.id) ? " checked" : "";
    const tone = row.gain == null ? "" : (row.gain >= 0 ? "plus" : "minus");
    const sold = row.sell == null ? "" : String(row.sell);
    const qty = row.qty == null ? "" : String(row.qty);
    const name = row.hand
      ? `<input class="name" data-id="${esc(row.id)}" value="${esc(row.name)}">`
      : esc(row.name);
    const buy = row.hand
      ? `<input class="buy" data-id="${esc(row.id)}" value="${esc(String(row.buy))}">`
      : `<span class="num">${rubExact(row.buy)}</span>`;
    const tag = rarityTag(row.qlt);
    const frame = tag ? "tone-" + toneOf(row.name, tag) : "";
    const qltOptions = ["", "Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]
      .map(value => `<option value="${esc(value)}"${value === (row.qlt || "") ? " selected" : ""}>${esc(value || "—")}</option>`).join("");
    return `<tr class="${frame}" data-buy="${esc(String(row.buy))}">
      <td><input type="checkbox" class="pickrow" data-id="${esc(row.id)}"${on}></td>
      <td>${esc(row.date_ru)}</td>
      <td class="named"><span class="nmline">${gem(row.name, tag)}<span class="nm">${name}</span></span><button type="button" class="ingame" data-name="${esc(baseName(row.name))}">Найти на аукционе</button></td>
      <td><select class="qlt" data-id="${esc(row.id)}">${qltOptions}</select></td>
      <td><input class="ptn" data-id="${esc(row.id)}" value="${esc(row.ptn || "")}" placeholder="+0"></td>
      <td class="num">${buy}</td>
      <td><input class="qty" data-id="${esc(row.id)}" value="${esc(qty)}" placeholder="шт"></td>
      <td><input class="sell" data-id="${esc(row.id)}" value="${esc(sold)}" placeholder="за сколько продал"></td>
      <td class="num net">${rubExact(row.net)}</td>
      <td class="num gain ${tone}">${rubExact(row.gain)}</td>
      <td><button type="button" class="drop" data-id="${esc(row.id)}">Убрать</button></td>
    </tr>`;
  }).join("");
  box.innerHTML = `<table><thead><tr><th></th><th>Дата</th><th>Предмет</th><th>Редкость</th><th>Точка</th><th>Куплено</th><th>Штук</th><th>Продано</th><th>После 5%</th><th>Плюс</th><th></th></tr></thead><tbody>${body || '<tr><td colspan="11">Отметь лот на «Выкупе» или добавь свою позицию.</td></tr>'}</tbody></table>`;
  box.querySelectorAll("input.pickrow").forEach(input => input.onchange = () => {
    if (input.checked) state.picked.add(input.dataset.id);
    else state.picked.delete(input.dataset.id);
    paintBook();
  });
  const refreshCut = (input) => {
    const tr = input.closest("tr");
    const buyInput = tr.querySelector("input.buy");
    const buy = buyInput ? (moneyOf(buyInput.value) || 0) : Number(tr.dataset.buy || 0);
    showCut(tr.querySelector(".net"), tr.querySelector(".gain"), moneyOf(tr.querySelector("input.sell").value), buy);
  };
  box.querySelectorAll("input.sell, input.buy").forEach(input => input.oninput = () => refreshCut(input));
  box.querySelectorAll("input.sell").forEach(input => input.onchange = async () => {
    const res = await pywebview.api.ledger_sell(input.dataset.id, input.value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      paintBook();
    }
  });
  box.querySelectorAll("input.qty").forEach(input => input.onchange = async () => {
    const res = await pywebview.api.ledger_qty(input.dataset.id, input.value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      paintBook();
    }
  });
  box.querySelectorAll("input.name").forEach(input => input.onchange = async () => {
    const res = await pywebview.api.ledger_name(input.dataset.id, input.value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      paintBook();
    }
  });
  box.querySelectorAll("input.buy").forEach(input => input.onchange = async () => {
    const res = await pywebview.api.ledger_buy(input.dataset.id, input.value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      paintBook();
    }
  });
  const saveMark = async (input) => {
    const tr = input.closest("tr");
    const res = await pywebview.api.ledger_mark(input.dataset.id, tr.querySelector("select.qlt").value, tr.querySelector("input.ptn").value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      paintBook();
    }
  };
  box.querySelectorAll("select.qlt, input.ptn").forEach(input => input.onchange = () => saveMark(input));
  box.querySelectorAll("button.ingame").forEach(btn => btn.onclick = () => pywebview.api.game_search(btn.dataset.name));
  box.querySelectorAll("button.drop").forEach(btn => btn.onclick = async () => {
    const row = (state.book || []).find(item => item.id === btn.dataset.id);
    const name = row && row.name ? row.name : "этот лот";
    if (!await ask("Убрать «" + name + "» из учёта?")) return;
    const res = await pywebview.api.ledger_remove(btn.dataset.id);
    if (res && res.ok !== false) {
      state.picked.delete(btn.dataset.id);
      state.book = res.rows || [];
      paintBook();
      if ($("t-buys")) paint("buys");
    }
  });
}

async function loadBook() {
  const data = await pywebview.api.ledger();
  state.book = data.rows || [];
  state.bookPath = data.path || "";
  if ($("book-file")) $("book-file").textContent = state.bookPath ? "Файл: " + state.bookPath : "";
  paintBook();
}

function build() {
  const tabs = $("tabs");
  const main = $("main");
  TAB_ORDER.forEach((key, n) => {
    tabs.appendChild(tabButton(key, TAB_NAME[key], n === 0));
    const view = document.createElement("div");
    view.className = "view" + (n ? "" : " on");
    view.id = "v-" + key;
    view.innerHTML = key === "buys"
      ? `<section class="lots panel"><div class="table-head"><span>КУПИЛ</span><span>ПРЕДМЕТ</span><span>КУПИТЬ</span><span>ПЛЮС</span><span>В ЧАС</span></div><div class="lots-list" id="t-buys"></div></section>`
      : `<div class="page"><div class="page-head"><h2>${TAB_NAME[key]}</h2><p>${TAB_BLURB[key] || ""}</p></div><div class="sheet" id="t-${key}"></div></div>`;
    main.appendChild(view);
  });
  tabs.appendChild(tabButton("auc", "Аукцион", false));
  const view = document.createElement("div");
  view.className = "view";
  view.id = "v-auc";
  view.innerHTML = `
    <div class="auc-page">
      <div class="auc-intro">
        <div>
          <small>ТОРГОВАЯ ПЛОЩАДКА</small>
          <h1>Аукцион</h1>
          <p>Находите выгодные лоты и принимайте решение без лишнего шума.</p>
        </div>
        <button type="button" class="auc-filter-btn" id="filter-toggle">Фильтры <b id="filter-count">0</b></button>
      </div>
      <div class="auc-search">
        <label class="auc-q">⌕ <input id="q" placeholder="Название предмета или категория"/><kbd>⌘ K</kbd></label>
        <button type="button" class="chip on" data-chip="all">Все предметы</button>
        <button type="button" class="chip" data-chip="rare">Редкие</button>
        <button type="button" class="chip" data-chip="ptn">Заточка 0–15</button>
      </div>
      <div class="auc-filterbox" id="filterbox">
        <div><label>Раздел</label><select id="cat"></select></div>
        <div><label>Редкость</label><select id="lq"></select></div>
        <div><label>Заточка</label><div class="range"><input id="lo" value="0"/><input id="hi" value="15"/></div></div>
      </div>
      <div class="market">
        <section class="catalog">
          <div class="catalog-head"><div><h2>Каталог</h2><small id="found">Каталог грузится при открытии вкладки.</small></div><select id="asort"><option>По имени</option><option>По рангу</option></select></div>
          <div class="columns"><span>ПРЕДМЕТ</span><span>ЦЕНА</span><span>ОСТАЛОСЬ</span></div>
          <div id="items" class="auc-lots"></div>
        </section>
        <aside class="details">
          <div class="auc-tabs"><button type="button" class="on" id="now">Текущий лот</button><button type="button" id="hist">История</button></div>
          <div class="product">
            <span class="shield" id="detail-gem"></span>
            <small id="detail-q">—</small>
            <h2 id="detail-name">Выбери предмет</h2>
            <p id="detail-kind"></p>
            <button type="button" class="ingame" id="detail-find">Найти на аукционе</button>
          </div>
          <div class="current-price" id="lot-price"><small>Текущая цена</small><strong id="lot-now">—</strong><b id="lot-delta"></b></div>
          <div class="facts" id="lot-facts"></div>
          <div class="offer" id="lotinfo">Кликни предмет слева. Здесь будет цена и стоит ли его брать.</div>
          <div id="lotstats"></div>
          <button type="button" class="buy" id="auc-add" disabled>Добавить в выкуп <b id="auc-price">—</b></button>
          <div class="sheet" id="lotbox"></div>
        </aside>
      </div>
    </div>`;
  main.appendChild(view);
  tabs.appendChild(tabButton("map", "Карта", false));
  const logBtn = tabButton("log", "Лог", false);
  logBtn.onclick = () => {
    const open = $("logwin").classList.toggle("on");
    logBtn.classList.toggle("on", open);
  };
  tabs.appendChild(logBtn);
  const mapView = document.createElement("div");
  mapView.className = "view";
  mapView.id = "v-map";
  mapView.innerHTML = `<div class="mapwrap"><div class="tools" id="mapbar"></div><div id="mapstatus" role="status" style="padding:4px 8px;color:var(--dim)">Карты Лунара загрузятся при открытии вкладки.</div><div class="tools" id="maplayers"></div><div id="wikimap"></div></div>`;
  main.appendChild(mapView);
  const bookBtn = tabButton("book", "Учёт", false);
  tabs.insertBefore(bookBtn, tabs.children[1] || null);
  const bookView = document.createElement("div");
  bookView.className = "view";
  bookView.id = "v-book";
  bookView.innerHTML = `<div class="page"><div class="page-head"><h2>Учёт</h2><p>С выкупа строка встаёт сама. Свою позицию добавляешь сверху: название выбирается из списка, правится всё, кроме даты. После 5% и плюс считаются сразу. На строке с выкупа штуки пересчитывают суммы за штуку.</p><p id="book-file"></p></div><div class="own"><div class="namebox"><input id="own-name" placeholder="Начни вводить предмет" autocomplete="off"><div id="own-list" class="namelist" hidden></div></div><select id="own-qlt"><option value="">Редкость</option><option>Обычный</option><option>Необычный</option><option>Особый</option><option>Редкий</option><option>Исключительный</option><option>Легендарный</option></select><input id="own-ptn" placeholder="Точка"><input id="own-buy" placeholder="Куплено"><input id="own-qty" placeholder="Штук"><input id="own-sell" placeholder="Продано"><span class="cut">После 5% <b id="own-net">—</b></span><span class="cut">Плюс <b id="own-gain">—</b></span><button type="button" id="own-add" class="gold">Добавить</button></div><div class="bookstats"><div class="stat"><span>Весь плюс</span><b id="book-gain" class="green">0</b></div><div class="stat"><span>Сегодня</span><b id="book-today-gain" class="green">0</b></div><div class="stat"><span>Выделено</span><b id="book-picked" class="green">0</b></div></div><div class="bar"><button type="button" id="book-only-today">Только сегодня</button><button type="button" id="book-all">Выделить всё</button><button type="button" id="book-clear">Снять</button></div><div class="sheet" id="bookbox"></div></div>`;
  main.appendChild(bookView);
  $("book-only-today").onclick = () => {
    state.picked = new Set((state.book || []).filter(row => row.today).map(row => row.id));
    paintBook();
  };
  $("book-all").onclick = () => {
    state.picked = new Set((state.book || []).map(row => row.id));
    paintBook();
  };
  $("book-clear").onclick = () => {
    state.picked = new Set();
    paintBook();
  };
  const previewOwn = () => showCut($("own-net"), $("own-gain"), moneyOf($("own-sell").value), moneyOf($("own-buy").value) || 0);
  ["own-buy", "own-sell"].forEach(id => $(id).oninput = previewOwn);
  state.ownPick = 0;
  $("own-name").oninput = () => { state.ownPick = 0; paintOwnList(); };
  $("own-name").onfocus = () => {
    if (!state.catalog.length) pywebview.api.load_catalog();
    paintOwnList();
  };
  $("own-name").onkeydown = (event) => {
    const buttons = [...$("own-list").querySelectorAll("button")];
    const open = !$("own-list").hidden && buttons.length;
    if (event.key === "ArrowDown" && open) {
      event.preventDefault();
      state.ownPick = Math.min(buttons.length - 1, state.ownPick + 1);
      paintOwnList();
    } else if (event.key === "ArrowUp" && open) {
      event.preventDefault();
      state.ownPick = Math.max(0, state.ownPick - 1);
      paintOwnList();
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (open) {
        $("own-name").value = buttons[state.ownPick].dataset.name;
        $("own-list").hidden = true;
      } else $("own-add").click();
    } else if (event.key === "Escape") $("own-list").hidden = true;
  };
  $("own-name").onblur = () => setTimeout(() => { if ($("own-list")) $("own-list").hidden = true; }, 160);
  $("own-add").onclick = async () => {
    const name = $("own-name").value.trim();
    if (!name) return;
    const res = await pywebview.api.ledger_hand(name, $("own-buy").value, $("own-sell").value, $("own-qty").value, $("own-qlt").value, $("own-ptn").value);
    if (res && res.ok !== false && res.rows) {
      state.book = res.rows;
      ["own-name", "own-buy", "own-qty", "own-sell", "own-ptn"].forEach(id => { $(id).value = ""; });
      $("own-qlt").value = "";
      $("own-list").hidden = true;
      previewOwn();
      paintBook();
    }
  };
}

function mapViewOf(settings) {
  const zoom = settings.defaultZoom ?? 3;
  const minZoom = settings.minZoom ?? 2;
  const maxZoom = settings.maxZoom ?? 4;
  const width = settings.width || 2048;
  const height = settings.height || 2048;
  const world = 256 * Math.pow(2, zoom);
  const scale = world / 2 / Math.PI;
  const shift = -height + world / 2;
  const east = 180 / Math.PI * ((width - world / 2) / scale);
  const south = 360 / Math.PI * (Math.atan(Math.exp(shift / scale)) - Math.PI / 4);
  const mid = 360 / Math.PI * (Math.atan(Math.exp((world / 2 + shift) / 2 / scale)) - Math.PI / 4);
  return {center: [mid, (-180 + east) / 2], bounds: [[south, -180], [85.05112878, east]], minZoom, maxZoom, zoom};
}

function drawWiki(pack) {
  const box = $("wikimap");
  if (state.wiki) {
    state.wiki.remove();
    state.wiki = null;
  }
  let wiki;
  if (pack.local) {
    wiki = L.map(box, {crs: L.CRS.Simple, attributionControl: false, minZoom: -3, maxZoom: 3});
    const size = pack.tile;
    let south = Infinity, north = -Infinity, west = Infinity, east = -Infinity;
    pack.tiles.forEach(tile => {
      const bottom = tile.y * size;
      const left = tile.x * size;
      L.imageOverlay(pack.base + tile.file, [[bottom, left], [bottom + size, left + size]]).addTo(wiki);
      south = Math.min(south, bottom);
      north = Math.max(north, bottom + size);
      west = Math.min(west, left);
      east = Math.max(east, left + size);
    });
    if (pack.tiles.length) wiki.fitBounds([[south, west], [north, east]]);
  } else {
    const view = mapViewOf(pack.settings);
    wiki = L.map(box, {
      minZoom: view.minZoom,
      maxZoom: view.maxZoom,
      zoom: view.zoom,
      center: view.center,
      maxBounds: view.bounds,
      maxBoundsViscosity: 1,
      attributionControl: false
    });
    L.tileLayer(pack.settings.tiles + "/{z}-{x}-{y}.jpg", {
      minZoom: view.minZoom,
      maxZoom: view.maxZoom,
      noWrap: true,
      bounds: view.bounds
    }).addTo(wiki);
  }
  state.wiki = wiki;
  state.pack = pack;
  state.mine = pack.mine || [];
  state.placing = false;
  state.hidden = {};
  state.icons = {};
  const bar = $("maplayers");
  bar.innerHTML = "";
  const search = document.createElement("input");
  search.id = "mapq";
  search.placeholder = "Поиск метки";
  search.oninput = paintMarks;
  bar.appendChild(search);
  const name = document.createElement("input");
  name.id = "markname";
  name.placeholder = "Своя метка";
  bar.appendChild(name);
  const put = document.createElement("button");
  put.textContent = "Ставить";
  put.onclick = () => {
    state.placing = !state.placing;
    put.classList.toggle("on", state.placing);
    box.style.cursor = state.placing ? "crosshair" : "";
  };
  bar.appendChild(put);
  const own = document.createElement("button");
  own.textContent = "Свои";
  own.className = "on";
  own.onclick = () => {
    state.hidden["Свои"] = !state.hidden["Свои"];
    own.classList.toggle("on", !state.hidden["Свои"]);
    paintMarks();
  };
  bar.appendChild(own);
  wiki.on("click", async (event) => {
    if (!state.placing) return;
    const slug = state.pack.slug;
    const title = ($("markname").value || "").trim() || "Метка";
    const mine = await pywebview.api.add_mark(slug, event.latlng.lat, event.latlng.lng, title);
    if (state.pack.slug !== slug) return;
    state.mine = mine;
    paintMarks();
  });
  pack.areas.forEach(area => {
    const button = document.createElement("button");
    button.textContent = area.title;
    button.className = "on";
    button.onclick = () => {
      state.hidden[area.title] = !state.hidden[area.title];
      button.classList.toggle("on", !state.hidden[area.title]);
      paintMarks();
    };
    bar.appendChild(button);
  });
  pack.groups.forEach(group => {
    const button = document.createElement("button");
    button.textContent = group.title;
    button.className = "on";
    button.onclick = () => {
      state.hidden[group.title] = !state.hidden[group.title];
      button.classList.toggle("on", !state.hidden[group.title]);
      paintMarks();
    };
    bar.appendChild(button);
  });
  paintMarks();
  setTimeout(() => wiki.invalidateSize(), 60);
}

function markIcon(url) {
  if (!state.icons[url]) {
    state.icons[url] = L.icon({iconUrl: url, iconSize: [22, 22], iconAnchor: [11, 11]});
  }
  return state.icons[url];
}

function paintMarks() {
  if (state.pack && state.pack.lunar) return paintLunar();
  if (!state.wiki || !state.pack) return;
  if (state.marks) state.marks.remove();
  const query = ($("mapq") ? $("mapq").value : "").trim().toLowerCase();
  const layer = L.layerGroup();
  state.pack.areas.forEach(area => {
    if (state.hidden[area.title]) return;
    if (query) return;
    area.polygons.forEach(points => {
      L.polygon(points, {color: area.border, weight: 1, fillColor: area.fill, fillOpacity: 0.28})
        .bindTooltip(area.title)
        .addTo(layer);
    });
  });
  state.pack.groups.forEach(group => {
    if (state.hidden[group.title]) return;
    group.types.forEach(type => {
      type.markers.forEach(mark => {
        const blob = (group.title + " " + type.title + " " + (mark.text || "")).toLowerCase();
        if (query && !blob.includes(query)) return;
        const tip = type.title + (mark.text ? " — " + mark.text : "");
        const point = type.image
          ? L.marker([mark.lat, mark.lng], {icon: markIcon(type.image)})
          : L.circleMarker([mark.lat, mark.lng], {radius: 5, color: type.color, fillColor: type.color, fillOpacity: 0.9, weight: 1});
        point.bindTooltip(tip);
        point.on("click", () => navigator.clipboard.writeText(type.title));
        point.addTo(layer);
      });
    });
  });
  if (!state.hidden["Свои"]) {
    (state.mine || []).forEach(mark => {
      const blob = ("свои " + (mark.title || "")).toLowerCase();
      if (query && !blob.includes(query)) return;
      const point = L.circleMarker([mark.lat, mark.lng], {
        radius: 7, color: "#e0b15a", fillColor: "#e0b15a", fillOpacity: 1, weight: 2
      });
      point.bindTooltip("Своя: " + mark.title);
      point.on("click", async (event) => {
        L.DomEvent.stopPropagation(event);
        if (state.placing) return;
        if (!await ask("Убрать метку «" + mark.title + "»?")) return;
        const slug = state.pack.slug;
        const mine = await pywebview.api.delete_mark(slug, mark.id);
        if (state.pack.slug !== slug) return;
        state.mine = mine;
        paintMarks();
      });
      point.addTo(layer);
    });
  }
  layer.addTo(state.wiki);
  state.marks = layer;
}

async function openPda(slug) {
  const request = state.mapRequest = (state.mapRequest || 0) + 1;
  state.mapSlug = slug;
  state.mapOpened = true;
  state.placing = false;
  $("wikimap").style.pointerEvents = "none";
  $("maplayers").style.pointerEvents = "none";
  $("mapstatus").textContent = "Собираю карту из клиента…";
  document.querySelectorAll("#mapbar button").forEach(b => b.classList.toggle("on", b.dataset.slug === slug));
  try {
    const pack = await pywebview.api.pda_map(slug);
    if (request !== state.mapRequest) return;
    if (!pack || pack.error) throw new Error(pack?.error || "Пустой ответ карты");
    drawWiki(pack);
    $("wikimap").style.pointerEvents = "";
    $("maplayers").style.pointerEvents = "";
    $("mapstatus").textContent = pack.title + " · " + pack.count + " кусков, с диска";
  } catch (error) {
    if (request !== state.mapRequest) return;
    state.mapOpened = false;
    $("mapstatus").textContent = "Локальная карта не собралась: " + error.message;
  }
}

async function openWiki(slug) {
  const request = state.mapRequest = (state.mapRequest || 0) + 1;
  state.mapSlug = slug;
  state.mapOpened = true;
  state.placing = false;
  $("wikimap").style.pointerEvents = "none";
  $("maplayers").style.pointerEvents = "none";
  $("mapstatus").textContent = "Загружаю карту…";
  document.querySelectorAll("#mapbar button").forEach(b => b.classList.toggle("on", b.dataset.slug === slug));
  try {
    const pack = await pywebview.api.wiki_map(slug);
    if (request !== state.mapRequest) return;
    if (!pack || pack.error) throw new Error(pack?.error || "Пустой ответ карты");
    drawWiki(pack);
    $("wikimap").style.pointerEvents = "";
    $("maplayers").style.pointerEvents = "";
    $("mapstatus").textContent = pack.title + " · данные stalzone.wiki";
  } catch (error) {
    if (request !== state.mapRequest) return;
    state.mapOpened = false;
    $("mapstatus").textContent = "Карта не загрузилась: " + error.message + ". Нажмите на локацию, чтобы повторить.";
  }
}

async function openLunar(slug) {
  const request = state.mapRequest = (state.mapRequest || 0) + 1;
  state.mapSlug = slug;
  state.mapOpened = true;
  state.placing = false;
  $("wikimap").style.pointerEvents = "none";
  $("maplayers").style.pointerEvents = "none";
  $("mapstatus").textContent = "Загружаю карту Лунара…";
  document.querySelectorAll("#mapbar button").forEach(b => b.classList.toggle("on", b.dataset.slug === slug));
  try {
    const pack = await pywebview.api.lunar_map(slug);
    if (request !== state.mapRequest) return;
    if (!pack || pack.error) throw new Error(pack?.error || "Пустой ответ карты");
    drawLunar(pack);
    $("wikimap").style.pointerEvents = "";
    $("maplayers").style.pointerEvents = "";
  } catch (error) {
    if (request !== state.mapRequest) return;
    state.mapOpened = false;
    $("mapstatus").textContent = "Карта не загрузилась: " + error.message;
  }
}

function drawLunar(pack) {
  const box = $("wikimap");
  if (state.wiki) {
    state.wiki.remove();
    state.wiki = null;
  }
  const wiki = L.map(box, {
    crs: L.CRS.Simple,
    minZoom: -4,
    maxZoom: 1,
    attributionControl: false,
    preferCanvas: true,
    zoomSnap: 0.25
  });
  wiki.createPane("ground");
  wiki.getPane("ground").style.zIndex = 250;
  const bounds = [[0, 0], [pack.height, pack.width]];
  if (pack.overview) L.imageOverlay(pack.overview, bounds, {pane: "ground"}).addTo(wiki);
  wiki.fitBounds(bounds);
  wiki.setMaxBounds(bounds);
  state.wiki = wiki;
  state.pack = pack;
  state.ground = {};
  state.groundLevel = null;
  state.mine = pack.mine || [];
  state.placing = false;
  state.hidden = {};
  state.colors = {};
  (pack.categories || []).forEach(cat => { state.colors[cat.id] = cat.color; });
  const bar = $("maplayers");
  bar.innerHTML = "";
  const search = document.createElement("input");
  search.id = "mapq";
  search.placeholder = "Поиск метки";
  search.oninput = paintLunar;
  bar.appendChild(search);
  const name = document.createElement("input");
  name.id = "markname";
  name.placeholder = "Своя метка";
  bar.appendChild(name);
  const put = document.createElement("button");
  put.textContent = "Ставить";
  put.onclick = () => {
    state.placing = !state.placing;
    put.classList.toggle("on", state.placing);
    box.style.cursor = state.placing ? "crosshair" : "";
  };
  bar.appendChild(put);
  const showAll = document.createElement("button");
  showAll.textContent = "Показать все";
  showAll.onclick = () => {
    state.hidden = {};
    bar.querySelectorAll("button[data-cat], button[data-own]").forEach(b => b.classList.add("on"));
    paintLunar();
  };
  bar.appendChild(showAll);
  const hideAll = document.createElement("button");
  hideAll.textContent = "Скрыть все";
  hideAll.onclick = () => {
    (pack.categories || []).forEach(cat => { state.hidden[cat.id] = true; });
    state.hidden["Свои"] = true;
    bar.querySelectorAll("button[data-cat], button[data-own]").forEach(b => b.classList.remove("on"));
    paintLunar();
  };
  bar.appendChild(hideAll);
  const own = document.createElement("button");
  own.textContent = "Свои";
  own.className = "on";
  own.dataset.own = "1";
  own.onclick = () => {
    state.hidden["Свои"] = !state.hidden["Свои"];
    own.classList.toggle("on", !state.hidden["Свои"]);
    paintLunar();
  };
  bar.appendChild(own);
  (pack.categories || []).forEach(cat => {
    const button = document.createElement("button");
    button.textContent = cat.title;
    button.className = "on";
    button.dataset.cat = String(cat.id);
    button.onclick = () => {
      state.hidden[cat.id] = !state.hidden[cat.id];
      button.classList.toggle("on", !state.hidden[cat.id]);
      paintLunar();
    };
    bar.appendChild(button);
  });
  wiki.on("click", async (event) => {
    if (!state.placing) return;
    const here = state.pack.slug;
    const title = ($("markname").value || "").trim() || "Метка";
    const mine = await pywebview.api.add_mark(here, event.latlng.lat, event.latlng.lng, title);
    if (state.pack.slug !== here) return;
    state.mine = mine;
    paintLunar();
  });
  wiki.on("moveend", () => { paintTiles(); paintLunar(); });
  wiki.on("zoomend", paintTiles);
  paintTiles();
  paintLunar();
  setTimeout(() => { wiki.invalidateSize(); paintTiles(); paintLunar(); }, 60);
}

function paintTiles() {
  const pack = state.pack;
  const wiki = state.wiki;
  const tiles = pack && pack.tiles;
  if (!wiki || !tiles || !tiles.base || !tiles.grid) return;
  const zoom = wiki.getZoom();
  let level = Math.round(-zoom);
  if (level < 0) level = 0;
  if (level > tiles.zoomMax) level = tiles.zoomMax;
  const cells = tiles.grid[String(level)] || [];
  const known = {};
  cells.forEach(cell => { known[cell[0] + ":" + cell[1]] = true; });
  const span = tiles.size * Math.pow(2, level);
  const view = wiki.getBounds().pad(0.35);
  const west = view.getWest();
  const east = view.getEast();
  const top = pack.height - view.getNorth();
  const bottom = pack.height - view.getSouth();
  const tx0 = Math.floor(west / span) - 1;
  const tx1 = Math.floor(east / span) + 1;
  const ty0 = Math.floor(top / span) - 1;
  const ty1 = Math.floor(bottom / span) + 1;
  if (state.groundLevel !== level) {
    Object.values(state.ground).forEach(layer => wiki.removeLayer(layer));
    state.ground = {};
    state.groundLevel = level;
  }
  const keep = {};
  for (let tx = tx0; tx <= tx1; tx += 1) {
    for (let ty = ty0; ty <= ty1; ty += 1) {
      const key = tx + ":" + ty;
      if (!known[key]) continue;
      keep[key] = true;
      if (state.ground[key]) continue;
      const south = pack.height - (ty + 1) * span;
      const north = pack.height - ty * span;
      const url = tiles.base + "z" + level + "/" + tx + "_" + ty + ".webp" + tiles.query;
      state.ground[key] = L.imageOverlay(url, [[south, tx * span], [north, (tx + 1) * span]], {pane: "ground"}).addTo(wiki);
    }
  }
  Object.keys(state.ground).forEach(key => {
    if (keep[key]) return;
    wiki.removeLayer(state.ground[key]);
    delete state.ground[key];
  });
}

function paintLunar() {
  if (!state.wiki || !state.pack || !state.pack.lunar) return;
  if (state.marks) state.marks.remove();
  const pack = state.pack;
  const query = ($("mapq") ? $("mapq").value : "").trim().toLowerCase();
  const bounds = state.wiki.getBounds();
  const layer = L.layerGroup();
  let shown = 0;
  let matched = 0;
  const limit = 4000;
  (pack.markers || []).forEach(mark => {
    const cat = mark[2];
    if (state.hidden[cat]) return;
    const title = pack.titles[mark[3]] || "Метка";
    if (query && !title.toLowerCase().includes(query)) return;
    matched += 1;
    const lat = pack.height - mark[1];
    const lng = mark[0];
    if (!bounds.contains([lat, lng])) return;
    if (shown >= limit) return;
    shown += 1;
    const color = state.colors[cat] || "#e0b15a";
    const point = L.circleMarker([lat, lng], {radius: 4, color, fillColor: color, fillOpacity: 0.9, weight: 1});
    point.bindTooltip(title);
    point.on("click", () => navigator.clipboard.writeText(title));
    point.addTo(layer);
  });
  if (!state.hidden["Свои"]) {
    (state.mine || []).forEach(mark => {
      const blob = ("свои " + (mark.title || "")).toLowerCase();
      if (query && !blob.includes(query)) return;
      const point = L.circleMarker([mark.lat, mark.lng], {
        radius: 7, color: "#e0b15a", fillColor: "#e0b15a", fillOpacity: 1, weight: 2
      });
      point.bindTooltip("Своя: " + mark.title);
      point.on("click", async (event) => {
        L.DomEvent.stopPropagation(event);
        if (state.placing) return;
        if (!await ask("Убрать метку «" + mark.title + "»?")) return;
        const here = state.pack.slug;
        const mine = await pywebview.api.delete_mark(here, mark.id);
        if (state.pack.slug !== here) return;
        state.mine = mine;
        paintLunar();
      });
      point.addTo(layer);
    });
  }
  layer.addTo(state.wiki);
  state.marks = layer;
  let text = pack.title + " · " + (pack.markers || []).length + " меток, Лунар";
  if (matched > shown) text += " · на экране " + shown + ", приблизь или включи поиск";
  $("mapstatus").textContent = text;
}

function paintLicense(lic) {
  const seat = lic || {};
  const box = $("license");
  const side = $("side-status");
  if (!seat.active) {
    if (box) box.classList.add("on");
    if (side) side.textContent = seat.reason || "нет ключа";
    return;
  }
  if (box) box.classList.remove("on");
  if (side) side.textContent = seat.role === "owner" ? "владелец · безлимит" : ("истекает через: " + seat.days_left + " дн.");
}

function show(key) {
  document.body.dataset.screen = key;
  document.querySelectorAll(".tabs button").forEach(b => {
    if (b.dataset.key === "log") return;
    b.classList.toggle("on", b.dataset.key === key);
  });
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "v-" + key));
  if ($("screen-title")) $("screen-title").textContent = TAB_NAME[key] || {book:"Учёт", auc:"Аукцион", map:"Карта"}[key] || key;
  if (key === "auc" && !state.catalog.length) loadCatalog();
  if (key === "book") {
    loadBook();
    if (!state.catalog.length) pywebview.api.load_catalog();
  }
  if (key === "map") {
    if (!state.mapBooted) {
      state.mapBooted = true;
      pywebview.api.lunar_catalog().then(maps => {
        const bar = $("mapbar");
        bar.innerHTML = "";
        (maps || []).forEach(item => {
          const btn = document.createElement("button");
          btn.textContent = item.title;
          btn.dataset.slug = item.slug;
          btn.onclick = () => openLunar(item.slug);
          bar.appendChild(btn);
        });
        if (maps && maps.length) openLunar(maps[0].slug);
        else $("mapstatus").textContent = "Лунар не отдал карты";
      }).catch(error => {
        $("mapstatus").textContent = "Карты не загрузились: " + error.message;
      });
    } else if (state.wiki) {
      setTimeout(() => state.wiki.invalidateSize(), 60);
    }
  }
}

function ask(text) {
  const veil = $("ask");
  $("ask-text").textContent = text;
  veil.classList.add("on");
  return new Promise(resolve => {
    const finish = (value) => {
      veil.classList.remove("on");
      veil.onclick = null;
      $("ask-no").onclick = null;
      $("ask-yes").onclick = null;
      document.removeEventListener("keydown", onKey, true);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      finish(false);
    };
    $("ask-no").onclick = () => finish(false);
    $("ask-yes").onclick = () => finish(true);
    veil.onclick = (event) => { if (event.target === veil) finish(false); };
    document.addEventListener("keydown", onKey, true);
  });
}

function esc(s) {
  const amp = "\u0026";
  return String(s ?? "")
    .split("&").join(amp + "amp;")
    .split("<").join(amp + "lt;")
    .split(">").join(amp + "gt;")
    .split('"').join(amp + "quot;");
}

let selected = null;
function paintFilterCount() {
  const cat = $("cat");
  const lq = $("lq");
  const lo = Number($("lo") && $("lo").value);
  const hi = Number($("hi") && $("hi").value);
  let n = 0;
  if (cat && cat.value && cat.value !== "all") n += 1;
  if (lq && lq.value && lq.value !== "Все") n += 1;
  if (lo !== 0 || hi !== 15) n += 1;
  if ($("q") && $("q").value.trim()) n += 1;
  if ($("filter-count")) $("filter-count").textContent = String(n);
  document.querySelectorAll(".chip").forEach(btn => {
    const kind = btn.dataset.chip;
    const on = kind === "rare" ? !!(lq && /редк/i.test(lq.value))
      : kind === "all" ? (!cat || cat.value === "all") && (!lq || !lq.value || lq.value === "Все")
      : false;
    btn.classList.toggle("on", on);
  });
}

function paintCard(name, row) {
  const card = state.card || {};
  const item = row || state.catalog.find(i => i.id === selected) || {};
  const title = name || item.name || "";
  if ($("detail-q")) $("detail-q").textContent = card.qname || item.rank || "—";
  if ($("lot-now")) $("lot-now").textContent = card.price ? card.text + " ₽" : "—";
  const delta = $("lot-delta");
  if (delta) {
    delta.textContent = card.delta || "";
    delta.classList.toggle("up", String(card.delta || "").trim().startsWith("+"));
  }
  if ($("lot-facts")) {
    const cells = [["Качество", card.qname || "—"], ["Осталось", card.left || "—"], ["Средняя цена", card.mean ? card.mean_text + " ₽" : "—"], ["Продаж за 7 д", String(card.count || 0)]];
    $("lot-facts").innerHTML = cells.map(([k, v]) => `<div><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join("");
  }
  if ($("auc-price")) $("auc-price").textContent = card.price ? card.text : "—";
  const add = $("auc-add");
  if (add) {
    add.disabled = !card.price;
    add.onclick = async () => {
      if (!card.price) return;
      const res = await pywebview.api.ledger_add(title, card.price, "", card.amount || "", card.qname || "", card.ptn || "");
      if (res && res.rows) { state.book = res.rows; if ($("bookbox")) paintBook(); }
    };
  }
}

function renderItems() {
  const q = ($("q").value || "").trim().toLowerCase();
  const key = $("cat").value || "all";
  let items = state.catalog.slice();
  if (key === "fav") items = items.filter(i => state.fav.has(i.id));
  else if (key === "recent") {
    const order = Object.fromEntries(state.recent.map((id, n) => [id, n]));
    items = items.filter(i => order[i.id] !== undefined);
    items.sort((a, b) => order[a.id] - order[b.id]);
  } else if (key !== "all") {
    const allowed = state.catKeys[key] || [];
    if (key === "other") {
      const named = new Set(Object.values(state.catKeys).flat());
      items = items.filter(i => allowed.includes(i.cat) || !named.has(i.cat));
    } else items = items.filter(i => allowed.includes(i.cat));
  }
  if (key !== "recent") {
    if ($("asort").value === "По рангу") items.sort((a, b) => a.order - b.order || a.name.localeCompare(b.name, "ru"));
    else items.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }
  if (q) items = items.filter(i => i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q));
  const shown = items.slice(0, 500);
  const card = state.card || {};
  $("found").textContent = `Показано ${shown.length} из ${items.length}`;
  $("items").innerHTML = shown.map(i => {
    const on = selected === i.id ? " on" : "";
    const mine = selected === i.id && card.text;
    const price = mine ? card.text : "—";
    const left = mine ? (card.left || "—") : "—";
    const face = gem(i.name, "", i.icon);
    return `<button type="button" class="alot${on}" data-id="${esc(i.id)}">${face}<span class="item-copy"><b>${esc(i.name)}</b><small>${esc(i.cat)} · ${esc(i.rank)}</small></span><span class="price"><b>${esc(price)}</b><small>${esc(i.rank)}</small></span><span class="time">${esc(left)}</span><span class="arrow">›</span></button>`;
  }).join("");
  $("items").querySelectorAll(".alot").forEach(tr => {
    tr.onclick = () => {
      selected = tr.dataset.id;
      openItem();
    };
  });
  paintFilterCount();
}

async function loadCatalog() {
  $("found").textContent = "Читаю каталог EXBO…";
  const data = await pywebview.api.load_catalog();
  if (data && data.items && data.items.length) applyCatalog(data);
}

function applyCatalog(data) {
  if (!data || data.pending) return;
  state.catalog = data.items || [];
  rememberItems(state.catalog);
  if (data.favs) state.fav = new Set(data.favs);
  if (data.recent) state.recent = data.recent;
  if (!data.ok) {
    $("found").textContent = data.error || "Каталог не загрузился";
    return;
  }
  renderItems();
  TAB_ORDER.forEach(paint);
  if ($("bookbox")) paintBook();
  if ($("own-name") && document.activeElement === $("own-name")) paintOwnList();
}

function lotTable(rows, cols) {
  const item = state.catalog.find(i => i.id === selected) || {};
  const body = (rows || []).map(r => {
    const cells = r.cells.map((c, i) => i === 0
      ? `<td class="named">${gem(item.name || c, r.tag, item.icon)}<span>${esc(c)}</span></td>`
      : `<td>${esc(c)}</td>`);
    return `<tr class="${r.tag || ""}">${cells.join("")}</tr>`;
  }).join("");
  $("lotbox").innerHTML = `<table><thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

function auctionLoading(on) {
  state.itemLoading = on;
  for (const id of ["lq", "lo", "hi"]) {
    const node = $(id);
    if (node) node.disabled = on;
  }
}

async function openItem() {
  if (!selected) return;
  const request = ++state.detailRequest;
  auctionLoading(true);
  const row = state.catalog.find(i => i.id === selected);
  const name = row ? row.name : selected;
  if ($("detail-gem")) $("detail-gem").innerHTML = gem(name, "", row && row.icon);
  if ($("detail-name")) $("detail-name").textContent = name;
  if ($("detail-kind")) $("detail-kind").textContent = row ? `${row.cat} · ${row.rank}` : "";
  if ($("detail-q")) $("detail-q").textContent = "—";
  $("detail-find").onclick = () => pywebview.api.game_search(name);
  $("lotinfo").textContent = name + ": читаю лоты…";
  $("lotstats").textContent = "Считаю среднюю и медиану…";
  if ($("auc-add")) $("auc-add").disabled = true;
  let data;
  try { data = await pywebview.api.open_item(selected, name, $("lq").value, $("lo").value, $("hi").value); }
  catch (error) { data = {ok:false, error:String(error)}; }
  if (request !== state.detailRequest) return;
  auctionLoading(false);
  if (!data.ok) { $("lotinfo").textContent = data.error || "Ошибка"; $("lotstats").textContent = ""; return; }
  state.lots = data.lots; state.sales = data.sales; state.card = data.card || {};
  paintCard(name, row);
  $("lotinfo").textContent = (state.card.verdict || data.info || "").replace(/^.*?:\s*/, "");
  $("lotstats").textContent = data.summary || "";
  showLots();
  renderItems();
}

function showLots() {
  if (state.lot === "now") lotTable(state.lots, ["Качество","Заточка","Штук","Ставка","Выкуп","За штуку","Осталось"]);
  else lotTable(state.sales, ["Когда","Качество","Заточка","Штук","Цена","За штуку"]);
}

function wire() {
  $("run").onclick = () => pywebview.api.start_run(false, $("mins").value, $("budget").value, scanSection());
  $("auto").onclick = () => pywebview.api.start_run(true, $("mins").value, $("budget").value, scanSection());
  $("live").onclick = () => pywebview.api.start_live($("budget").value);
  $("stop").onclick = () => pywebview.api.stop_run();
  $("q").oninput = renderItems;
  $("cat").onchange = renderItems;
  $("asort").onchange = renderItems;
  $("filter-toggle").onclick = () => $("filterbox").classList.toggle("on");
  document.querySelectorAll(".chip").forEach(btn => btn.onclick = () => {
    if (btn.dataset.chip === "all") {
      $("cat").value = "all";
      if ([...$("lq").options].some(o => o.value === "Все")) $("lq").value = "Все";
    } else if (btn.dataset.chip === "rare") {
      const opt = [...$("lq").options].find(o => /редк/i.test(o.value));
      if (opt) $("lq").value = opt.value;
    } else {
      $("lo").value = "0";
      $("hi").value = "15";
    }
    renderItems();
    if ($("lq").onchange) $("lq").onchange();
  });
  $("budget").addEventListener("change", () => { $("budget").value = prettyMoney($("budget").value); });
  $("lq").onchange = $("lo").onchange = $("hi").onchange = async () => {
    if (state.itemLoading) return;
    const request = ++state.detailRequest;
    $("lotstats").textContent = "Пересчитываю по выбранным фильтрам…";
    const data = await pywebview.api.filter_open($("lq").value, $("lo").value, $("hi").value);
    if (request !== state.detailRequest) return;
    if (!data.ok) { $("lotstats").textContent = ""; return; }
    state.lots = data.lots; state.sales = data.sales; state.card = data.card || state.card || {};
    paintCard();
    if (data.info) $("lotinfo").textContent = data.card && data.card.verdict ? data.card.verdict : data.info;
    $("lotstats").textContent = data.summary || "";
    showLots();
    renderItems();
  };
  $("now").onclick = () => { state.lot = "now"; $("now").classList.add("on"); $("hist").classList.remove("on"); showLots(); };
  $("hist").onclick = () => { state.lot = "hist"; $("hist").classList.add("on"); $("now").classList.remove("on"); showLots(); };
}

async function tick() {
  const data = await pywebview.api.poll();
  const short = data.busy ? "В работе" : "Онлайн";
  $("status").textContent = short;
  $("status").title = data.status || "";
  const budgetText = prettyMoney($("budget").value || "");
  if ($("stat-count")) {
    const rows = data.compact || [];
    const gain = rows.reduce((sum, row) => sum + (Number(row.gain_n) || 0), 0);
    $("stat-count").textContent = String(rows.length);
    $("stat-gain").textContent = rubShort(gain);
    $("stat-budget").textContent = budgetText;
    $("stat-live").textContent = data.busy ? "скан" : "ждёт";
  }
  if (data.license) paintLicense(data.license);
  if ($("logwin").classList.contains("on")) {
    const lines = data.logs || [];
    const box = $("log");
    const nearEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
    box.innerHTML = lines.map(line => `<p>${esc(line).replace(/OK/g, "<mark>OK</mark>")}</p>`).join("")
      || `<p><mark>${data.busy ? "Прогон запущен, поиск лотов..." : "Ожидание следующего прогона..."}</mark></p>`;
    if (nearEnd) box.scrollTop = box.scrollHeight;
    $("log-state").textContent = short;
  }
  ["run","auto","live","mins","budget"].forEach(id => $(id).disabled = !!data.busy);
  $("stop").disabled = !data.busy;
  if (data.rev !== state.rev) {
    state.rev = data.rev;
    state.tables = data.tables || {};
    TAB_ORDER.forEach(paint);
  }
}

window.addEventListener("pywebviewready", async () => {
  const boot = await pywebview.api.boot();
  state.columns = boot.columns;
  rememberItems(boot.icons || []);
  paintLicense(boot.license);
  $("license-go").onclick = async () => {
    const res = await pywebview.api.license_activate($("license-key").value);
    paintLicense(res);
    const msg = $("license-msg");
    if (msg) msg.textContent = res && res.active ? "" : ((res && res.reason) || "Ключ не подошёл");
  };
  $("license-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("license-go").click();
  });
  $("license-buy").onclick = async () => {
    const res = await pywebview.api.license_buy();
    const msg = $("license-msg");
    if (msg) msg.textContent = res && res.ok ? "" : ((res && res.reason) || "Не удалось открыть оплату");
  };
  $("license-off").onclick = async () => {
    const res = await pywebview.api.license_drop();
    if ($("license-key")) $("license-key").value = "";
    if ($("license-msg")) $("license-msg").textContent = "Подписка отключена. Введи ключ снова.";
    paintLicense(res);
  };
  $("license-close").onclick = () => pywebview.api.hud_action("close");
  $("budget").value = prettyMoney(boot.budget);
  build();
  $("cat").innerHTML = boot.cats.map(c => `<option value="${esc(c.key)}">${esc(c.title)}</option>`).join("");
  $("lq").innerHTML = boot.qlt.map(s => `<option>${esc(s)}</option>`).join("");
  state.catKeys = await pywebview.api.cat_keys();
  await loadBook();
  wire();
  $("closehud").onclick = () => pywebview.api.hud_action("close");
  $("log-close").onclick = () => {
    $("logwin").classList.remove("on");
    const logBtn = document.querySelector('#tabs button[data-key="log"]');
    if (logBtn) logBtn.classList.remove("on");
  };
  $("menu-toggle").onclick = () => {
    const shell = $("full");
    const open = shell.classList.toggle("menu-open");
    $("menu-toggle").setAttribute("aria-label", open ? "Закрыть меню" : "Открыть меню");
  };
  $("quickstop") && ($("quickstop").onclick = () => pywebview.api.stop_run());
  document.querySelectorAll("[data-order]").forEach(b => b.onclick = () => setOrder(state.order === "hour" ? "gain" : "hour"));
  TAB_ORDER.forEach(paint);
  setInterval(tick, 400);
  tick();
});
</script>
</body>
</html>
"""


def main():
    folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    if not (folder / "exbo.json").exists():
        text = "Рядом с программой нет exbo.json. Положи ключ EXBO в ту же папку и запусти ещё раз."
        (folder / "stalzone_gui_error.log").write_text(text, encoding="utf-8")
        raise SystemExit(text)
    try:
        import webview
    except ImportError as e:
        text = "Нет окна. Поставь пакет: python -m pip install pywebview\n" + str(e)
        (folder / "stalzone_gui_error.log").write_text(text, encoding="utf-8")
        raise SystemExit(text)
    from stalzone_overlay import HudController
    bridge = Bridge()
    webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
    window = webview.create_window("STALZONE", html=PAGE, js_api=bridge,
        width=1280, height=820, min_size=(960, 640), frameless=True,
        easy_drag=False, on_top=False, hidden=True, background_color='#080d11')
    hud = HudController(window, folder / 'overlay_settings.json')
    bridge._hud = hud
    window.events.loaded += hud.start
    def closing():
        if hud.quit_requested:
            agent.HALT.set()
            hud.closing()
            return True
        hud.command('close')
        return False
    window.events.closing += closing
    window.events.closed += hud.stop
    webview.start(gui='edgechromium')


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        (folder / "stalzone_gui_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
