# -*- coding: utf-8 -*-
"""Окно агента. Расчёты те же, интерфейс на системном браузере Windows."""
import json
import sys
import threading
import time
import traceback
from pathlib import Path

import stalzone_agent as agent
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
        self.open_slug = None
        self._wiki = {}
        self._hud = None
        self._compact = []
        self._launch_lock = threading.Lock()
        self._search_lock = threading.Lock()

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
            self.status = str(msg)[:80]

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
        }

    def poll(self):
        with self.lock:
            return {
                "status": self.status,
                "busy": self.busy,
                "logs": list(self.logs),
                "tables": self.tables,
                "rev": self.rev,
                "compact": list(self._compact),
                "hud": self._hud.snapshot() if self._hud else {},
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

    def _start_run(self, auto, minutes, budget, section):
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
        try:
            items = agent.auction_listing()
        except Exception as e:
            self.note(f"Каталог не загрузился: {e}")
            return {"ok": False, "error": str(e), "items": []}
        self.auction = items
        self.note(f"Каталог: {len(items)} предметов")
        return {
            "ok": True,
            "items": [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "cat": i["cat"],
                    "color": i.get("color") or "DEFAULT",
                    "rank": agent.RANK_NAME.get(i.get("color"), i.get("color") or ""),
                    "order": agent.RANK_ORDER.get(i.get("color"), 9),
                }
                for i in items
            ],
        }

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

    def favs(self):
        return {"ids": sorted(self.fav), "recent": list(self.recent)}

    def cat_keys(self):
        return {key: sorted(names) for key, names in agent.AUCTION_CAT_KEYS.items()}

    def open_item(self, slug, name, qname, lo, hi):
        if not slug:
            return {"ok": False, "error": "Выбери предмет слева"}
        self.open_slug = slug
        self.recent = [slug] + [x for x in self.recent if x != slug]
        self.recent = self.recent[:30]
        self._write_json("auction_recent.json", self.recent)
        self.note(f"{name}: читаю лоты…")
        try:
            data = agent.item_view(slug, name or "")
        except Exception as e:
            self.note(f"Ошибка: {e}")
            return {"ok": False, "error": str(e)}
        self.lot_data = data
        return self._lots_payload(name, data, qname, lo, hi)

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
        return {"ok": True, "info": info, "lots": lot_rows, "sales": sale_rows}


PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<title>STALZONE</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --bg: #0c0f0e;
    --side: #101413;
    --card: #161b19;
    --card-2: #1c2220;
    --line: #2a312e;
    --green: #3ddc84;
    --green-dim: #173226;
    --orange: #f0a035;
    --ink: #f3f6f4;
    --dim: #8d9893;
    --buy: #3ddc84;
    --sell: #8fd0a4;
    --hold: #f0a035;
    --skip: #8d9893;
    --gold: #3ddc84;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--ink); font: 14px/1.4 "Segoe UI", sans-serif; }
  button, select, input { font: inherit; color: inherit; }
  button { cursor: pointer; border: 1px solid transparent; border-radius: 10px; padding: 8px 12px; background: var(--card-2); color: var(--ink); }
  button:hover { background: #24302b; }
  button:disabled { opacity: 0.45; cursor: default; }
  button.gold { background: var(--green); color: #06210f; font-weight: 700; border: 0; }
  button.gold:hover { background: #6aeea6; }
  button.stop { background: #3a2222; color: #f0c2b8; }
  body { display: flex; flex-direction: column; }
  header { display: flex; gap: 8px; align-items: center; padding: 8px 12px; flex-shrink: 0; border-bottom: 1px solid var(--line); background: var(--side); }
  header h1, .brand b { margin: 0; font-size: 15px; letter-spacing: 0.08em; color: var(--green); }
  header button { padding: 5px 9px; }
  #status { margin-left: auto; color: var(--dim); font-size: 12px; }
  #full { display: none; flex: 1; min-height: 0; }
  body.full #full { display: flex; }
  body.full #compact, body.full .compact-brand { display: none; }
  #compact { display: flex; flex: 1; min-height: 0; flex-direction: column; padding: 0 12px 10px; gap: 8px; }
  #compact .sheet { flex: 1; min-height: 0; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
  #compact th, #compact td { padding: 8px; font-size: 12px; }
  #compact td:first-child { white-space: normal; }
  #compact td:nth-child(3), #compact td:nth-child(4) { color: var(--green); font-weight: 700; }
  .compact-actions { display: flex; gap: 6px; }
  .compact-brand { display: flex; align-items: center; gap: 8px; }
  .logo {
    width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
    background: var(--green); color: #06210f; font-weight: 800;
  }
  #hudhint { font-size: 11px; color: var(--dim); flex-shrink: 0; padding: 6px 12px; border-top: 1px solid var(--line); }
  button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--green); outline-offset: 2px; }
  .sidenav { width: 228px; flex-shrink: 0; background: var(--side); border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; }
  .brand { display: flex; gap: 10px; align-items: center; padding: 16px 14px 8px; }
  .brand small { display: block; color: var(--dim); letter-spacing: 0; font-size: 11px; }
  .workspace { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 12px 18px; }
  .bar span { color: var(--dim); font-size: 12px; }
  input, select { background: #0e1211; border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; }
  input { width: 88px; text-align: center; }
  #q { width: 100%; text-align: left; }
  .tabs { display: flex; flex-direction: column; gap: 2px; padding: 8px; overflow: auto; }
  .tabs button { background: transparent; color: var(--dim); text-align: left; border-radius: 10px; }
  .tabs button.on { background: var(--green-dim); color: var(--green); }
  #stats { display: none; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 0 18px 12px; }
  body[data-screen="buys"] #stats { display: grid; }
  .stat { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
  .stat span { display: block; color: var(--dim); font-size: 12px; margin-bottom: 6px; }
  .stat b { font-size: 22px; font-weight: 700; }
  .stat b.green { color: var(--green); }
  main { flex: 1; min-height: 0; overflow: hidden; }
  .view { display: none; height: 100%; min-height: 0; }
  .view.on { display: flex; flex-direction: column; }
  .page { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 4px 18px 12px; gap: 10px; }
  .page-head h2 { margin: 0; font-size: 26px; font-weight: 700; }
  .page-head p, .found { margin: 4px 0 0; color: var(--dim); }
  .sheet { flex: 1; min-height: 0; overflow: auto; background: var(--card); border: 1px solid var(--line); border-radius: 14px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 10px 12px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--line); }
  th { position: sticky; top: 0; background: #1e2522; color: var(--dim); font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; cursor: pointer; }
  tr:hover td { background: #202824; }
  .buy { color: var(--green); } .sell { color: var(--sell); } .hold { color: var(--orange); } .skip { color: var(--skip); }
  .q0 { color: #c8c2b8; } .q1 { color: #7dcea0; } .q2 { color: #5dade2; }
  .q3 { color: #c39bd3; } .q4 { color: #e07a7a; } .q5 { color: #f0d78c; }
  .RANK_LEGEND { color: #e0b15a; } .RANK_MASTER { color: #e07a7a; } .RANK_VETERAN { color: #c4a3ff; }
  .RANK_STALKER { color: #8ebfff; } .RANK_NEWBIE { color: #9ddeaf; } .DEFAULT { color: var(--ink); }
  #log { height: 64px; flex-shrink: 0; margin: 0 18px 10px; overflow: auto; background: #0e1211; color: #c5cdc8; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--line); font: 12px/1.4 Consolas, monospace; white-space: pre-wrap; }
  .balance { margin-top: auto; margin: auto 12px 12px; padding: 12px; border: 1px solid var(--line); border-radius: 14px; background: #0e1512; }
  .balance span, .balance small { display: block; color: var(--dim); font-size: 12px; }
  .balance b { display: block; margin: 4px 0; color: var(--green); font-size: 20px; }
  .auc { flex: 1; min-height: 0; display: grid; grid-template-columns: 240px minmax(280px, 1fr) minmax(300px, 380px); }
  .filters, .detail { min-height: 0; overflow: auto; padding: 14px; background: var(--side); }
  .filters { border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
  .detail { border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; background: var(--bg); }
  .filters h3, .detail h2 { margin: 4px 0; }
  .filters label { color: var(--dim); font-size: 12px; }
  .range { display: flex; gap: 8px; }
  .range input { width: 100%; }
  .results { min-width: 0; min-height: 0; display: flex; flex-direction: column; padding: 14px 16px; gap: 8px; }
  .result-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 8px; }
  .pick { display: flex; gap: 12px; align-items: center; width: 100%; text-align: left; background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; }
  .pick.on { border-color: var(--green); background: #14211b; }
  .pick .avatar { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: #101614; color: var(--green); font-weight: 700; flex-shrink: 0; }
  .pick .who { display: flex; flex-direction: column; min-width: 0; }
  .pick .who b { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pick .who small, .found { color: var(--dim); }
  .pick .watch { margin-left: auto; color: var(--orange); }
  #lotinfo { color: var(--ink); background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; }
  .sub { display: flex; gap: 6px; }
  .sub button.on { color: #06210f; background: var(--green); }
  .detail .sheet { background: var(--card); }
  .tools { display: flex; gap: 8px; align-items: center; padding: 8px; flex-wrap: wrap; position: sticky; top: 0; z-index: 1; background: var(--side); }
  .mapwrap { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  #mapbar button.on, #maplayers button.on { background: var(--green); color: #06210f; }
  #mapq { width: 180px; text-align: left; }
  #wikimap { flex: 1; min-height: 0; background: #0e0c0a; }
  #mapbar button.on, #maplayers button.on { background: var(--green); color: #06210f; }
  #mapq { width: 180px; text-align: left; }
  #wikimap { flex: 1; min-height: 0; background: #0e0c0a; }
</style>
</head>
<body data-screen="buys">
<header class="pywebview-drag-region">
  <div class="compact-brand"><span class="logo">S</span><h1>STALZONE</h1></div>
  <div id="status" role="status">ожидание</div>
  <button id="expand" title="Развернуть интерфейс">Развернуть</button>
  <button id="backgame" title="Вернуть управление игре (Esc)">В игру</button>
  <button id="closehud" aria-label="Закрыть оверлей">×</button>
</header>
<div id="compact">
  <div class="sheet"><table><thead><tr><th>Предмет</th><th>Купить и продать</th><th>Плюс</th><th>В час</th></tr></thead><tbody id="deals"></tbody></table></div>
  <div class="compact-actions">
    <button class="gold" id="quickrun">Прогон</button>
    <button id="orderswitch" data-order type="button">По часу</button>
    <button class="stop" id="quickstop" disabled>Стоп</button>
    <button id="quickmap">Карта</button>
  </div>
</div>
<div id="full">
  <aside class="sidenav">
    <div class="brand"><span class="logo">S</span><div><b>STALZONE</b><small>Аукцион</small></div></div>
    <div class="tabs" id="tabs"></div>
    <div class="balance"><span>Бюджет на выкуп</span><b id="side-budget">5 000 000</b><small id="side-status">ожидание</small></div>
  </aside>
  <div class="workspace">
    <div class="bar">
      <button class="gold" id="run">Прогон</button>
      <button id="auto">Автопрогон</button>
      <button id="live">Онлайн</button>
      <span>каждые</span>
      <input id="mins" value="30"/>
      <span>мин</span>
      <span>бюджет</span>
      <input id="budget" value="5000000"/>
      <button id="orderswitch2" data-order type="button">По часу</button>
      <button class="stop" id="stop" disabled>Стоп</button>
      <select id="section"></select>
    </div>
    <div id="stats">
      <div class="stat"><span>Лотов в бюджете</span><b id="stat-count">0</b></div>
      <div class="stat"><span>Плюс</span><b id="stat-gain" class="green">0</b></div>
      <div class="stat"><span>Бюджет</span><b id="stat-budget">5000000</b></div>
      <div class="stat"><span>Рынок</span><b id="stat-live">ждёт</b></div>
    </div>
    <main id="main"></main>
    <div id="log"></div>
  </div>
</div>
<div id="hudhint">F10 — управление оверлеем</div>
<script>
const TAB_ORDER = ["buys","farm","arsenal","shelter_buy","shelter_sell","consumables","arts","protos"];
const TAB_BLURB = {
  buys: "Что купить и за сколько выставить. Плюс уже после 5%.",
  farm: "Дорогой бартер: держать или слить.",
  arsenal: "Арсенал. Цена, от которой есть смысл продавать.",
  shelter_buy: "Материалы убежища, которые ещё имеет смысл брать.",
  shelter_sell: "Готовое с убежища. Слить или подождать.",
  consumables: "Еда, хилки и бафы.",
  arts: "Популярные арты по той же цене, что и выкуп.",
  protos: "Протоартефакты, если после комиссии есть запас."
};
const TAB_NAME = {buys:"Выкуп", farm:"Фарм", arsenal:"Арсенал", shelter_buy:"Убежище купить", shelter_sell:"Убежище продать", consumables:"Расходники", arts:"Арты", protos:"Протоартефакты"};
const state = {columns:{}, tables:{}, rev:-1, sort:{}, catalog:[], fav:new Set(), recent:[], lot:"now", mapOpened:false, mapBooted:false, local:false, mapSlug:"south-zone", wiki:null, pack:null, marks:null, mine:[], placing:false, hidden:{}, icons:{}, order:"gain"};
const $ = (id) => document.getElementById(id);

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
  const head = cols.map((c, i) => `<th data-i="${i}">${c}${rule && rule.i === i ? (rule.desc ? " ↓" : " ↑") : ""}</th>`).join("");
  const body = rows.map(r => `<tr class="${r.tag || ""}">${r.cells.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("");
  box.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  box.querySelectorAll("th").forEach(th => th.onclick = () => {
    const i = Number(th.dataset.i);
    const prev = state.sort[key];
    state.sort[key] = {i, desc: prev && prev.i === i ? !prev.desc : true};
    paint(key);
  });
  box.querySelectorAll("tbody tr").forEach(tr => tr.onclick = () => pywebview.api.game_search(tr.cells[0].textContent));
}

function build() {
  const tabs = $("tabs");
  const main = $("main");
  TAB_ORDER.forEach((key, n) => {
    const b = document.createElement("button");
    b.textContent = TAB_NAME[key];
    b.dataset.key = key;
    b.className = n ? "" : "on";
    b.onclick = () => show(key);
    tabs.appendChild(b);
    const view = document.createElement("div");
    view.className = "view" + (n ? "" : " on");
    view.id = "v-" + key;
    view.innerHTML = `<div class="page"><div class="page-head"><h2>${TAB_NAME[key]}</h2><p>${TAB_BLURB[key] || ""}</p></div><div class="sheet" id="t-${key}"></div></div>`;
    main.appendChild(view);
  });
  const b = document.createElement("button");
  b.textContent = "Аукцион";
  b.dataset.key = "auc";
  b.onclick = () => show("auc");
  tabs.appendChild(b);
  const view = document.createElement("div");
  view.className = "view";
  view.id = "v-auc";
  view.innerHTML = `
    <div class="auc">
      <aside class="filters">
        <h3>Поиск</h3>
        <input id="q" placeholder="Предмет или категория"/>
        <label>Раздел</label>
        <select id="cat"></select>
        <label>Порядок</label>
        <select id="asort"><option>По имени</option><option>По рангу</option></select>
        <label>Редкость</label>
        <select id="lq"></select>
        <label>Заточка</label>
        <div class="range"><input id="lo" value="0"/><input id="hi" value="15"/></div>
        <button id="fav">В избранное</button>
        <button class="gold" id="open">Открыть лот</button>
      </aside>
      <section class="results">
        <div class="page-head"><h2>Аукцион</h2><p class="found" id="found">Каталог грузится при открытии вкладки.</p></div>
        <div id="items" class="result-list"></div>
      </section>
      <aside class="detail">
        <h2 id="detail-name">Лот</h2>
        <div id="lotinfo">Выбери предмет слева и открой лот. Здесь будет цена, медиана и почему его брать или нет.</div>
        <div class="sub"><button class="on" id="now">Сейчас</button><button id="hist">История</button></div>
        <div class="sheet" id="lotbox"></div>
      </aside>
    </div>`;
  main.appendChild(view);
  const mapBtn = document.createElement("button");
  mapBtn.textContent = "Карта";
  mapBtn.dataset.key = "map";
  mapBtn.onclick = () => show("map");
  tabs.appendChild(mapBtn);
  const mapView = document.createElement("div");
  mapView.className = "view";
  mapView.id = "v-map";
  mapView.innerHTML = `<div class="mapwrap"><div class="tools" id="mapbar"></div><div id="mapstatus" role="status" style="padding:4px 8px;color:var(--dim)">Карты Лунара загрузятся при открытии вкладки.</div><div class="tools" id="maplayers"></div><div id="wikimap"></div></div>`;
  main.appendChild(mapView);
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
        if (!confirm("Убрать метку «" + mark.title + "»?")) return;
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
        if (!confirm("Убрать метку «" + mark.title + "»?")) return;
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

function show(key) {
  document.body.dataset.screen = key;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.key === key));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "v-" + key));
  if (key === "auc" && !state.catalog.length) loadCatalog();
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

function esc(s) {
  const amp = "\u0026";
  return String(s ?? "")
    .split("&").join(amp + "amp;")
    .split("<").join(amp + "lt;")
    .split(">").join(amp + "gt;")
    .split('"').join(amp + "quot;");
}

let selected = null;
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
  $("found").textContent = `Найдено ${items.length}. Показано ${shown.length}.`;
  $("items").innerHTML = shown.map(i => {
    const on = selected === i.id ? " on" : "";
    const star = state.fav.has(i.id) ? "★" : "";
    const letter = (i.name || "?").slice(0, 1);
    return `<button type="button" class="pick ${esc(i.color)}${on}" data-id="${esc(i.id)}"><span class="avatar">${esc(letter)}</span><span class="who"><b>${esc(i.name)}</b><small>${esc(i.cat)} · ${esc(i.rank)}</small></span><span class="watch">${star}</span></button>`;
  }).join("");
  $("items").querySelectorAll(".pick").forEach(tr => {
    tr.onclick = () => {
      selected = tr.dataset.id;
      $("items").querySelectorAll(".pick").forEach(row => row.classList.toggle("on", row.dataset.id === selected));
      const row = state.catalog.find(i => i.id === selected);
      if (row && $("detail-name")) $("detail-name").textContent = row.name;
    };
    tr.ondblclick = () => { selected = tr.dataset.id; openItem(); };
  });
}

async function loadCatalog() {
  $("found").textContent = "Читаю каталог EXBO…";
  const data = await pywebview.api.load_catalog();
  state.catalog = data.items || [];
  const fav = await pywebview.api.favs();
  state.fav = new Set(fav.ids || []);
  state.recent = fav.recent || [];
  renderItems();
}

function lotTable(rows, cols) {
  const body = (rows || []).map(r => `<tr class="${r.tag || ""}">${r.cells.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("");
  $("lotbox").innerHTML = `<table><thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

async function openItem() {
  if (!selected) return;
  const row = state.catalog.find(i => i.id === selected);
  const name = row ? row.name : selected;
  $("detail-name").textContent = name;
  $("lotinfo").textContent = name + ": читаю лоты…";
  const data = await pywebview.api.open_item(selected, name, $("lq").value, $("lo").value, $("hi").value);
  if (!data.ok) { $("lotinfo").textContent = data.error || "Ошибка"; return; }
  state.lots = data.lots; state.sales = data.sales;
  $("lotinfo").textContent = data.info;
  showLots();
}

function showLots() {
  if (state.lot === "now") lotTable(state.lots, ["Качество","Заточка","Штук","Ставка","Выкуп","За штуку","Осталось"]);
  else lotTable(state.sales, ["Когда","Качество","Заточка","Штук","Цена","За штуку"]);
}

function wire() {
  $("run").onclick = () => pywebview.api.start_run(false, $("mins").value, $("budget").value, $("section").value);
  $("auto").onclick = () => pywebview.api.start_run(true, $("mins").value, $("budget").value, $("section").value);
  $("live").onclick = () => pywebview.api.start_live($("budget").value);
  $("stop").onclick = () => pywebview.api.stop_run();
  $("q").oninput = renderItems;
  $("cat").onchange = renderItems;
  $("asort").onchange = renderItems;
  $("fav").onclick = async () => {
    if (!selected) return;
    const r = await pywebview.api.toggle_fav(selected);
    state.fav = new Set(r.ids || []);
    renderItems();
  };
  $("open").onclick = openItem;
  $("lq").onchange = $("lo").onchange = $("hi").onchange = async () => {
    const data = await pywebview.api.filter_open($("lq").value, $("lo").value, $("hi").value);
    if (!data.ok) return;
    state.lots = data.lots; state.sales = data.sales;
    if (data.info) $("lotinfo").textContent = data.info;
    showLots();
  };
  $("now").onclick = () => { state.lot = "now"; $("now").classList.add("on"); $("hist").classList.remove("on"); showLots(); };
  $("hist").onclick = () => { state.lot = "hist"; $("hist").classList.add("on"); $("now").classList.remove("on"); showLots(); };
}

async function tick() {
  const data = await pywebview.api.poll();
  $("status").textContent = data.status || "";
  if ($("side-status")) $("side-status").textContent = data.status || "";
  if ($("side-budget")) $("side-budget").textContent = $("budget").value || "";
  if ($("stat-count")) {
    const rows = data.compact || [];
    const gain = rows.reduce((sum, row) => sum + (Number(row.gain_n) || 0), 0);
    $("stat-count").textContent = String(rows.length);
    $("stat-gain").textContent = rubShort(gain);
    $("stat-budget").textContent = $("budget").value || "";
    $("stat-live").textContent = data.busy ? "скан" : "ждёт";
  }
  $("log").textContent = (data.logs || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  ["run","auto","live","mins","budget","section"].forEach(id => $(id).disabled = !!data.busy);
  $("stop").disabled = !data.busy;
  $("quickrun").disabled = !!data.busy;
  $("quickstop").disabled = !data.busy;
  const hud = data.hud || {};
  const full = hud.mode === "full";
  const changed = document.body.classList.contains("full") !== full;
  document.body.classList.toggle("full", full);
  $("expand").textContent = full ? "Свернуть" : "Развернуть";
  $("hudhint").textContent = !hud.hotkey ? "Горячая клавиша занята другой копией — закройте её и перезапустите оверлей" :
    (hud.interactive ? "УПРАВЛЕНИЕ · Esc — в игру" : "ПРОСМОТР · F10 — управление") +
    (hud.game ? "" : " · окно игры не найдено");
  $("deals").innerHTML = compactRows(data.compact);
  $("deals").querySelectorAll("tr").forEach(tr => {
    const name = tr.cells[0] ? tr.cells[0].textContent : "";
    if (name && tr.cells.length > 1) tr.onclick = () => pywebview.api.game_search(name);
  });
  if (changed && full && state.wiki) setTimeout(() => state.wiki.invalidateSize(), 100);
  if (data.rev !== state.rev) {
    state.rev = data.rev;
    state.tables = data.tables || {};
    TAB_ORDER.forEach(paint);
  }
}

window.addEventListener("pywebviewready", async () => {
  const boot = await pywebview.api.boot();
  state.columns = boot.columns;
  $("section").innerHTML = boot.sections.map(s => `<option>${esc(s)}</option>`).join("");
  $("budget").value = boot.budget;
  build();
  $("cat").innerHTML = boot.cats.map(c => `<option value="${esc(c.key)}">${esc(c.title)}</option>`).join("");
  $("lq").innerHTML = boot.qlt.map(s => `<option>${esc(s)}</option>`).join("");
  state.catKeys = await pywebview.api.cat_keys();
  wire();
  $("expand").onclick = () => pywebview.api.hud_action(document.body.classList.contains("full") ? "compact" : "full");
  $("backgame").onclick = () => pywebview.api.hud_action("passive");
  $("closehud").onclick = () => pywebview.api.hud_action("close");
  $("quickmap").onclick = async () => { await pywebview.api.hud_action("full"); await tick(); show("map"); };
  $("quickrun").onclick = () => pywebview.api.start_run(false, $("mins").value, $("budget").value, "Выкуп");
  $("quickstop").onclick = () => pywebview.api.stop_run();
  document.querySelectorAll("[data-order]").forEach(b => b.onclick = () => setOrder(state.order === "hour" ? "gain" : "hour"));
  document.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); pywebview.api.hud_action("passive"); } });
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
    window = webview.create_window("STALZONE — карта и оверлей", html=PAGE, js_api=bridge,
        width=520, height=380, min_size=(440, 340), frameless=True,
        easy_drag=False, on_top=True, hidden=True, background_color='#12100e')
    hud = HudController(window, folder / 'overlay_settings.json')
    bridge._hud = hud
    window.events.loaded += hud.start
    def closing():
        agent.HALT.set()
        hud.closing()
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
