# -*- coding: utf-8 -*-
"""STALZONE агент. Цены и список предметов только из официальных данных EXBO."""
import argparse
import json
import math
import os
import statistics
import sys
import threading
import time
import traceback
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import stalzone_db
import stalzone_market as market


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DIR = app_dir()
EXBO = "https://eapi.stalzone.com"
DB_ZIP = "https://codeload.github.com/EXBO-Studio/stalzone-database/zip/refs/heads/main"
DB_LISTING = "https://raw.githubusercontent.com/EXBO-Studio/stalzone-database/main/ru/listing.json"
DB_LISTINGS = (
    "https://cdn.jsdelivr.net/gh/EXBO-Studio/stalzone-database@main/ru/listing.json",
    DB_LISTING,
)
LOG = DIR / "stalzone_agent.log"
BUY_HTML = DIR / "buy_now.html"
COMM = 0.95
UA = "stalzone-agent/1.0"
MSK = timezone(timedelta(hours=3))
HALT = threading.Event()
WORKERS = 4
AUCTION_WORKERS = 16
_LOG_LOCK = threading.Lock()
BUDGET = 5_000_000


# Дорогой бартер: фиолетовый (ветеран) и красный (мастер), север и Любеч.
BARTER_FARM = [
    ("7l127", "Аномальная пыль"),
    ("z301y", "Цветущий северный мох"),
    ("gn956", "Камень Жмых-Вжух-Плюх"),
    ("z30my", "Цветущий рыжий папоротник"),
    ("z3ogm", "Расцветший Горьколистник"),
    ("gnpr5", "Темный Лимб"),
    ("4k3qo", "Концентрированная лимбоплазма"),
    ("gn976", "Очищенное вещество 07270"),
    ("9dk7y", "Пси-маячок"),
    ("gn975", "Портативный квантовый генератор"),
    ("w3zj3", "Модифицированная аномальная батарея"),
    ("dr61j", "Блок данных «Бета»"),
    ("y409k", "Блок данных «Гамма»"),
    ("y4y33", "Блок данных «Лямбда»"),
]
ARSENAL = [
    ("4k5gr", "Блок данных «Альфа»"),
    ("dr61j", "Блок данных «Бета»"),
    ("y409k", "Блок данных «Гамма»"),
    ("y4y33", "Блок данных «Лямбда»"),
    ("8fg9w", "Большой ящик с продовольствием"),
    ("9d10q", "Военный радиопередатчик"),
    ("knpzj", "Глаз сильного бурелома"),
    ("qjqn4", "Голова сильной бестии"),
    ("egn0u", "Дорогие сигареты"),
    ("egh7l", "Драгоценности"),
    ("z3wgm", "Запчасти для ПДА"),
    ("gn1nn", "Комплект заводских инструментов"),
    ("j0q0l", "Компоненты редких сплавов"),
    ("4k3qo", "Концентрированная лимбоплазма"),
    ("007oy", "Кость мутанта"),
    ("y4gr3", "Крупный артефактный фрагмент"),
    ("krpnp", "Лоскут светящейся кожи"),
    ("z3k1m", "Малый артефактный фрагмент"),
    ("nb9wi", "Малый ящик с продовольствием"),
    ("y4n40", "Медицинские инструменты"),
    ("9d3gy", "Медная катушка"),
    ("w3zj3", "Модифицированная аномальная батарея"),
    ("olz36", "Моток медной проволоки"),
    ("9kpmj", "Набор компонентов брони (Мастер)"),
    ("3gq6k", "Набор компонентов оружия (Мастер)"),
    ("771lj", "Ноутбук"),
    ("55ymq", "Обычный артефактный фрагмент"),
    ("b80pf", "Обычный ящик с продовольствием"),
    ("w39k3", "Огромный артефактный фрагмент"),
    ("55olq", "Остатки приборов «Шепота»"),
    ("gn976", "Очищенное вещество 07270"),
    ("gn975", "Портативный квантовый генератор"),
    ("y3nmw", "Продвинутые запчасти"),
    ("4q7pl", "Продвинутые инструменты"),
    ("c4n76", "Промышленные запчасти"),
    ("dm6l2", "Протоартефакт"),
    ("vn3n7", "Прототипы «Шепота»"),
    ("9dk7y", "Пси-маячок"),
    ("z3ogm", "Расцветший Горьколистник"),
    ("wjlzz", "Рука сильного шныря"),
    ("rjvwy", "Сердце лимб"),
    ("s0xp7", "Системы наведения"),
    ("gnk55", "Соленоид"),
    ("l0og1", "Стандартные запчасти"),
    ("qjqw9", "Стандартные инструменты"),
    ("gnpr5", "Темный Лимб"),
    ("y4g93", "Фильтр"),
    ("1rl61", "Хроносфера"),
    ("z30my", "Цветущий рыжий папоротник"),
    ("l0ryo", "Черная селезенка"),
    ("nia64", "Ящик с деталями"),
    ("drym2", "Ящик с запчастями"),
    ("22odq", "Ящик с ресурсами (ветеран, украдены)"),
    ("pjn64", "Ящик с ресурсами (ветеран)"),
    ("n96ww", "Ящик с ресурсами (сталкер)"),
]

SHELTER_BUY = [
    ("z7pn", "Ткань"),
    ("2d76", "Мясо кабана"),
    ("9mr0", "Жгут"),
    ("5lo3o", "Копыто сильного кабана"),
    ("r22z", "Ноотроп"),
    ("g00n", "Мякоть сластены"),
    ("z3ozm", "Светящийся сахар"),
    ("7rp7", "Чеснок"),
    ("dq0n", "Мясо хрюши"),
    ("prrd", "Янтарная полынь"),
    ("drmwj", "Технический спирт"),
    ("m22k", "Водонос"),
    ("rrrz", "Бледнолист"),
    ("rwow5", "Бутылка чистой воды"),
    ("npp9", "Чертоцвет"),
    ("kl9v", "Молоко"),
    ("rr05", "Дрожжи"),
    ("1dk6", "Набор специй"),
    ("033k", "Кислотная крапива"),
    ("9mmq", "Мякоть солевика"),
    ("l2kk", "Глицерин"),
    ("5drg", "Брага"),
    ("mmn2", "Кровяная сыворотка"),
    ("y7dz", "Морозная смесь"),
    ("ovv5", "Гнозис"),
    ("404p", "Термическая смесь"),
    ("6rpy", "Помидор"),
    ("dm1ln", "Красная икра"),
    ("prl2", "Кофе"),
    ("km9v", "Коагулянт"),
    ("z77k", "Мякоть спиртня"),
    ("5ddo", "Мякоть куборбуза"),
    ("y770", "Мякоть лимонника"),
    ("1ddr", "Мякоть мятноплода"),
    ("1d31", "Банка с фасолью"),
    ("5dp0", "Банка с пшеном"),
    ("rwoj5", "Лимон"),
    ("y220", "Адреналин"),
]

SHELTER_SELL = [
    ("g4lzg", "Водка «Гейзер»"),
    ("wj2zp", "Чесночный суп"),
    ("y39yz", "Гороховый суп"),
    ("7l9l7", "Холодец «Копытом по лицу»"),
    ("7lyo3", "Алкобык"),
    ("zzqn9", "Коктейль «Незабываемый»"),
    ("3g1zz", "Субтропики"),
    ("g4lp0", "Измененный сидр"),
    ("5l23g", "Солянка"),
    ("m0pyj", "Аномальное шампанское"),
    ("qjmlk", "Бутерброд с икрой"),
    ("4qd3p", "Уха из сома «Дворянская»"),
    ("dm165", "Макароны по-флотски"),
    ("3g12z", "Жаркое из мутантов"),
    ("ly6w1", "Бутерброд с колбасой"),
    ("g0y0", "Соленья"),
    ("rwol5", "Консервированная фасоль"),
    ("y391o", "Колбасная нарезка"),
    ("4qdqn", "Отечественный ИРП"),
    ("j5mg7", "Игристое шампанское"),
    ("r2mv", "Вино с осадком"),
    ("j5456", "Отличная тушенка"),
    ("964z0", "Водка «Кривой Коготь»"),
    ("0row1", "Рыбные консервы"),
    ("qjmjk", "Боевой горох"),
    ("okdpo", "Веселый лимонад"),
    ("n4lg6", "Пшенка с мясом"),
    ("p62q6", "Морфин"),
    ("vjy3n", "Эпинефрин"),
    ("1r2l6", "Астрикцин"),
    ("g4lz0", "Биозаплатка"),
    ("6w59j", "УДАР"),
    ("1r216", "ТОПОТ"),
    ("y3knz", "Убийца Боли"),
    ("6w5lj", "Шизоерш"),
    ("zzqn2", "Нейротоник"),
    ("p6256", "Панацея"),
    ("964k0", "Сильная мазь от ожогов"),
    ("964ow", "Энергетик «Батарейка»"),
    ("1r2yq", "Силовой стимулятор"),
]


# Еда, хилки и бафы. Не только морфин.
CONSUMABLES = [
    ("vjy3n", "Эпинефрин"),
    ("p62q6", "Морфин"),
    ("g4lk0", "Военная аптечка"),
    ("96430", "Аптечка индивидуальная"),
    ("1r2o6", "Аптечка ученых"),
    ("7ly13", "Аптечка проводника"),
    ("zzqk2", "Бинт"),
    ("g4lz0", "Биозаплатка"),
    ("5lzyg", "Гемостат"),
    ("y3knz", "Убийца Боли"),
    ("p6256", "Панацея"),
    ("1r2l6", "Астрикцин"),
    ("2o9g0", "Озверин"),
    ("6w59j", "УДАР"),
    ("1r216", "ТОПОТ"),
    ("6w5lj", "Шизоерш"),
    ("1r2yq", "Силовой стимулятор"),
    ("g4l10", "Анаболик ATLAS"),
    ("zzqo2", "Анаболик SALT"),
    ("7lyd3", "Анаболик STARK"),
    ("zzqn2", "Нейротоник"),
    ("964ow", "Энергетик «Батарейка»"),
    ("lynkj", "Энергетик «Жидень EXTRA»"),
    ("rw1mg", "Тоник «Арни»"),
    ("j5mq7", "Антидот первого класса"),
    ("qj9y6", "Антидот второго класса"),
    ("lynrj", "Антидот третьего класса"),
    ("y3kgz", "Антирад Б-191"),
    ("wjw9p", "Антирад Б-292"),
    ("4qgop", "Антирад Б-393"),
    ("n4vw6", "Мазь от ожогов"),
    ("964k0", "Сильная мазь от ожогов"),
    ("4qdqn", "Отечественный ИРП"),
    ("wj2jo", "Американский ИРП"),
    ("j5456", "Отличная тушенка"),
    ("okrq0", "Мясные консервы"),
    ("rwow5", "Бутылка чистой воды"),
    ("z3o52", "Боевой набор"),
]
PROTO = ("dm6l2", "Протоартефакт")

ARTS = [
    ("gyq5", "Спираль"), ("1kv2", "Прима"), ("kqgy", "Браслет"),
    ("kqp0", "Жар-птица"), ("zy32", "Батарейка"), ("y54z", "Гиря"),
    ("qoq6", "Солнце"), ("zyqk", "Хрусталь"), ("5rpq", "Янтарник"),
    ("y5jk", "Жильник"), ("5rg1", "Проклятая роза"), ("wgvd", "Чернильница"),
    ("jkj4", "Ряска"), ("4l7p", "Гребешок"), ("5r5g", "Ледяной ежик"),
    ("qodk", "Бубльгум"), ("kqr0", "Гелий"), ("wg53", "Атом"),
    ("lj0j", "Катушка"), ("qo06", "Трансформатор"), ("rnvg", "Шишка"),
    ("g34p", "Юла"), ("jkq7", "Магма"), ("y5k0", "Вихрь"),
    ("wg62", "Белая роза"), ("zyly", "Цибуля"), ("9n1w", "Ягодка"),
    ("gypg", "Плод"), ("ljpq", "Многогранник"), ("4lml", "Змеиный глаз"),
    ("zyw2", "Огонек"), ("ljrj", "Радиатор"), ("zyrm", "Зеркало"),
    ("y5yw", "Гантель"), ("9nvy", "Вехотка"), ("kqoj", "Каблук"),
    ("gyg5", "Креветка"), ("qo94", "Куриный бог"), ("5rwq", "Осколок"),
    ("4l1r", "Протоцибуля"), ("wgwz", "Фаренгейт"), ("wg3p", "Дезинтегратор"),
    ("1kdg", "Липкий репях"), ("zy7y", "Ежик"), ("9nd0", "Призрачный кристалл"),
    ("1k96", "Трещотка"), ("qo59", "Жвачка"), ("kqj3", "Улитка"),
]
QLT = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with _LOG_LOCK:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def rub(n):
    try:
        n = float(n)
    except Exception:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}кк"
    if n >= 1000:
        return f"{n / 1000:.1f}к"
    return f"{n:.0f}"


def parallel(items, fn):
    results = [None] * len(items)
    if not items or HALT.is_set():
        return results
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = e
    return results


def qlabel(qlt, ptn):
    qname = QLT[qlt] if 0 <= qlt < len(QLT) else f"qlt {qlt}"
    return f"{qname} +{ptn}"


def _art_one(item):
    slug, name = item
    try:
        deals = find_flips(market_book(slug, 4), slug, name, allow_single=True, limit=12)
    except Exception as e:
        return [{"name": name, "err": str(e)}]
    rows = []
    for deal in deals:
        rows.append({
            "name": name,
            "qlt": deal.get("qlt") or "—",
            "ptn": deal.get("ptn") or "—",
            "qlt_i": deal.get("qlt_i"),
            "n": deal.get("n") or 0,
            "cheap": deal["unit"],
            "med": deal["med"],
            "net": deal["profit"],
            "liq": "ВЫКУПИТЬ",
        })
    return rows


def art_deals():
    parts = parallel(ARTS, _art_one)
    rows, checked = [], 0
    for part in parts:
        if isinstance(part, Exception):
            continue
        if part:
            rows.extend(part)
            checked += 1
        elif part == []:
            checked += 1
    rows.sort(key=lambda r: (0 if r.get("liq") == "ВЫКУПИТЬ" else 1, -(r.get("net") or 0)))
    return rows[:80], checked


_PACE = threading.Lock()
_NEXT_AT = 0.0
_GAP = 0.10
_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def _reset_client():
    global _CLIENT
    with _CLIENT_LOCK:
        old = _CLIENT
        _CLIENT = None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def _client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = httpx.Client(
                timeout=httpx.Timeout(12.0, connect=8.0),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=16),
            )
        return _CLIENT


_EXBO = None


def exbo_headers():
    global _EXBO
    if _EXBO is None:
        path = DIR / "exbo.json"
        if not path.exists():
            raise RuntimeError("нет exbo.json рядом со скриптом")
        raw = json.loads(path.read_text(encoding="utf-8"))
        _EXBO = (str(raw["client_id"]), str(raw["client_secret"]))
    client_id, secret = _EXBO
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Client-Id": client_id,
        "Client-Secret": secret,
    }


def get_json(url):
    """Один запрос к EXBO. Соединение держится открытым, пауза общая на все потоки."""
    global _NEXT_AT, _GAP
    for attempt in range(5):
        with _PACE:
            now = time.time()
            slot = max(_NEXT_AT, now)
            wait = slot - now
            _NEXT_AT = slot + _GAP
        if wait > 0:
            time.sleep(wait)
        try:
            resp = _client().get(url, headers=exbo_headers())
            resp.raise_for_status()
            data = resp.json()
            with _PACE:
                _GAP = max(0.08, _GAP * 0.98)
            return data
        except httpx.HTTPStatusError as error:
            failure = error
            code = error.response.status_code
            if attempt == 4 or not (code in (408, 425, 429) or code >= 500):
                raise
            limited = code == 429
            delay = 0.8 if limited else 0.3
            if limited:
                try:
                    retry_after = float(error.response.headers.get("Retry-After", "0"))
                    if 0 <= retry_after < float("inf"):
                        delay = min(5.0, max(delay, retry_after))
                except ValueError:
                    pass
        except httpx.TransportError as error:
            failure = error
            if attempt == 4:
                raise
            limited, delay = False, 0.3
        # httpx drops failed connections itself. Closing the shared client here
        # would abort unrelated requests running in other scan threads.
        with _PACE:
            if limited:
                _GAP = min(0.45, max(_GAP * 1.5, _GAP + 0.08))
            else:
                _GAP = min(0.45, _GAP + 0.03)
        if HALT.wait(delay):
            raise failure


_LIVE = {}
_LIVE_LOCK = threading.Lock()
_BOOK = {}
_BOOK_LOCK = threading.Lock()


def cached_live(slug):
    with _LIVE_LOCK:
        hit = _LIVE.get(slug)
    if hit is not None:
        return hit
    lots = live_lots(slug)
    with _LIVE_LOCK:
        _LIVE[slug] = lots
    return lots


def live_lots(slug, pages=4):
    out = []
    offset = 0
    total = None
    while total is None or offset < total:
        if HALT.is_set():
            break
        data = get_json(
            f"{EXBO}/RU/auction/{slug}/lots?additional=true&limit=200&offset={offset}"
            "&sort=buyout_price&order=asc"
        )
        total = data.get("total") or 0
        batch = data.get("lots") or []
        if not batch:
            break
        out.extend(batch)
        offset += 200
        if offset >= pages * 200 or offset >= total:
            break
    return out


def catalog():
    rows = []
    seen = set()
    groups = (
        ("Фарм", BARTER_FARM),
        ("Арсенал", ARSENAL),
        ("Убежище", list(SHELTER_BUY) + list(SHELTER_SELL)),
        ("Расходники", CONSUMABLES),
        ("Арты", ARTS),
        ("Прото", [PROTO]),
    )
    for group, items in groups:
        for slug, name in items:
            if slug in seen:
                continue
            seen.add(slug)
            rows.append((name, slug, group))
    rows.sort(key=lambda r: r[0].lower())
    return rows


AUCTION_CATS = (
    ("all", "Все предметы"),
    ("fav", "Избранное"),
    ("recent", "Недавние"),
    ("weapon", "Оружие"),
    ("armor", "Броня"),
    ("artefact", "Артефакты"),
    ("attachment", "Обвесы"),
    ("container", "Контейнеры"),
    ("backpack", "Рюкзаки"),
    ("medicine", "Медицина"),
    ("supply", "Снабжение"),
    ("grenade", "Гранаты"),
    ("bullet", "Патроны"),
    ("other", "Другое"),
)
AUCTION_CAT_KEYS = {
    "weapon": {"weapon"},
    "armor": {"armor"},
    "artefact": {"artefact"},
    "attachment": {"attachment", "weapon_modules"},
    "container": {"containers", "container"},
    "backpack": {"backpacks", "backpack"},
    "medicine": {"medicine"},
    "supply": {"supply", "food", "drink"},
    "grenade": {"grenade"},
    "bullet": {"bullet"},
    "other": {"other", "misc", "barter", "device"},
}
RANK_NAME = {
    "RANK_LEGEND": "Легенда",
    "RANK_MASTER": "Мастер",
    "RANK_VETERAN": "Ветеран",
    "RANK_STALKER": "Сталкер",
    "RANK_NEWBIE": "Новичок",
    "DEFAULT": "Обычный",
    "QUEST_ITEM": "Квест",
}
RANK_ORDER = {"RANK_LEGEND": 0, "RANK_MASTER": 1, "RANK_VETERAN": 2, "RANK_STALKER": 3, "RANK_NEWBIE": 4, "DEFAULT": 5, "QUEST_ITEM": 6}
_LISTING = None
_LISTING_LOCK = threading.Lock()
_OFF = None
_OFF_LOCK = threading.Lock()
_QUIET = None
_QUIET_LOCK = threading.Lock()
QUIET_FOR = 30 * 60
_QUIET_DIRTY = False
_QUIET_FLUSH_AT = 0.0
_SELL = None
_SELL_LOCK = threading.Lock()
SELL_FOR = 20 * 60


def hub_url():
    env = os.environ.get("STALZONE_HUB", "").strip()
    if env:
        return env.rstrip("/")
    path = DIR / "hub.url"
    if not path.exists():
        return ""
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return lines[0].rstrip("/") if lines else ""


def hub_token():
    env = os.environ.get("STALZONE_HUB_TOKEN", "").strip()
    if env:
        return env
    path = DIR / "hub.url"
    if not path.exists():
        return ""
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else ""


def _hub_get(suffix):
    import urllib.request
    headers = {"Accept": "application/json"}
    token = hub_token()
    if token:
        headers["X-Hub-Token"] = token
    request = urllib.request.Request(hub_url() + suffix, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode())


def _pull_hub_catalog(status=None):
    if not hub_url():
        return None
    path = DIR / "catalog.json"
    if path.exists() and time.time() - path.stat().st_mtime < 6 * 3600:
        return None
    try:
        data = _hub_get("/v1/catalog")
    except Exception as exc:
        log(f"хранилище каталога: {exc}")
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return None
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    _tell(status, f"Каталог взят из хранилища, {len(items)} предметов")
    return items


def _pull_hub_deals():
    if not hub_url():
        return None
    try:
        data = _hub_get("/v1/deals")
    except Exception as exc:
        log(f"хранилище снимка: {exc}")
        return None
    if not isinstance(data, dict) or not data.get("rows") or not data.get("ts"):
        return None
    return data


def _publish_board(rows, scanned, total):
    try:
        market.open_store(DIR / "market.db").save_board(rows, scanned, total)
    except Exception as exc:
        log(f"снимок хранилища: {exc}")


_BOARD_LOCK = threading.Lock()
BOARD_RECHECK = 30


def _offer_alive(row, lots):
    buy = int(row.get("buyout") or 0)
    amt = int(row.get("amount") or 0)
    if buy <= 0 or amt <= 0:
        return False
    for lot in lots or []:
        if int(lot.get("buyoutPrice") or 0) == buy and int(lot.get("amount") or 0) == amt:
            return True
    return False


def refresh_board(store=None):
    """Проверяет только лоты из снимка, без истории и без всего каталога. Купленного уже нет."""
    store = store or market.open_store(DIR / "market.db")
    board = store.board()
    if not board or not board.get("rows"):
        return board
    slugs = []
    seen = set()
    for row in board["rows"]:
        slug = row.get("slug")
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    live = {}

    def one(slug):
        try:
            return slug, live_lots(slug, pages=1)
        except Exception as exc:
            log(f"{slug}: снимок не сверить ({exc})")
            return slug, None

    with ThreadPoolExecutor(max_workers=AUCTION_WORKERS) as pool:
        for slug, lots in pool.map(one, slugs):
            live[slug] = lots
    kept = []
    for row in board["rows"]:
        lots = live.get(row.get("slug"))
        if lots is None or _offer_alive(row, lots):
            kept.append(row)
    store.save_board(kept, board.get("scanned") or 0, board.get("total") or 0)
    return store.board()


def board_for_team(store=None):
    store = store or market.open_store(DIR / "market.db")
    with _BOARD_LOCK:
        board = store.board()
        if not board:
            return {"ts": 0, "scanned": 0, "total": 0, "rows": []}
        if time.time() - float(board.get("ts") or 0) < BOARD_RECHECK:
            return board
        try:
            return refresh_board(store) or board
        except Exception as exc:
            log(f"сверка снимка: {exc}")
            return board


def auction_listing(force=False, status=None):
    """Каталог из официальной базы предметов EXBO. Сайт не вызывается."""
    global _LISTING
    with _LISTING_LOCK:
        if _LISTING is not None and not force:
            return _LISTING
    items = _load_catalog(force, status)
    off = _off_auction()
    items = [item for item in items if item.get("tradable", 1) and item["id"] not in off]
    with _LISTING_LOCK:
        _LISTING = items
    return items


def _tell(status, msg):
    log(msg)
    if status:
        status(msg)


def _load_catalog(force=False, status=None):
    path = DIR / "catalog.json"
    pulled = None if force else _pull_hub_catalog(status)
    if pulled:
        _sync_items(pulled)
        return _auction_rows(pulled)
    fresh = path.exists() and time.time() - path.stat().st_mtime < 3 * 86400
    if fresh and not force:
        items = json.loads(path.read_text(encoding="utf-8"))
        _sync_items(items)
        return _auction_rows(items)
    try:
        items = _catalog_from_exbo(status)
    except Exception:
        if path.exists():
            _tell(status, "База EXBO не скачалась, беру прошлый каталог")
            items = json.loads(path.read_text(encoding="utf-8"))
            _sync_items(items)
            return _auction_rows(items)
        raise
    if not items:
        if path.exists():
            path.touch()
            items = json.loads(path.read_text(encoding="utf-8"))
            _sync_items(items)
            return _auction_rows(items)
        raise RuntimeError("База предметов пустая")
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    _sync_items(items)
    return _auction_rows(items)


def _catalog_from_exbo(status=None):
    """Список предметов из ru/listing.json. Полный архив только если список не открылся."""
    _tell(status, "Качаю список предметов EXBO")
    try:
        items = _catalog_from_listing(status)
    except Exception as exc:
        _tell(status, f"Список предметов не открылся ({exc}). Качаю архив базы")
        return _catalog_from_zip(status)
    if items is None:
        return None
    if items:
        return items
    _tell(status, "Список предметов пустой, качаю архив базы")
    return _catalog_from_zip(status)


def _catalog_from_listing(status=None):
    errors = []
    for url in DB_LISTINGS:
        try:
            return _listing_from(url, status)
        except Exception as exc:
            errors.append(str(exc))
            log(f"Список не открылся ({url}): {exc}")
    raise RuntimeError(errors[-1] if errors else "список предметов пуст")


def _listing_from(url, status=None):
    path = DIR / "catalog.json"
    stamp = DIR / "catalog.etag"
    headers = {"User-Agent": UA, "Accept": "application/json"}
    saved = stamp.read_text(encoding="utf-8").splitlines() if stamp.exists() else []
    if path.exists() and len(saved) >= 2 and saved[0].strip() == url and saved[1].strip():
        headers["If-None-Match"] = saved[1].strip()
    timeout = httpx.Timeout(20.0, connect=8.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as res:
            if res.status_code == 304:
                _tell(status, "База предметов не менялась, архив заново не качаю")
                return None
            res.raise_for_status()
            total = int(res.headers.get("content-length") or 0)
            etag = (res.headers.get("etag") or "").strip()
            chunks = []
            got = 0
            mark = 0
            for chunk in res.iter_bytes(64 * 1024):
                chunks.append(chunk)
                got += len(chunk)
                if status and got - mark >= 256 * 1024:
                    mark = got
                    if total:
                        status(f"Список предметов {got // 1024} из {max(total, got) // 1024} КБ")
                    else:
                        status(f"Список предметов {got // 1024} КБ")
    items = _items_in_listing(json.loads(b"".join(chunks)))
    if etag and items:
        stamp.write_text(url + "\n" + etag + "\n", encoding="utf-8")
    return items


def _auction_rows(items):
    return [item for item in items or [] if item.get("tradable", 1)]


def _sync_items(items):
    if not items:
        return
    try:
        stalzone_db.sync_items(DIR / "items.db", items)
    except Exception as exc:
        log(f"база предметов: {exc}")


def _items_in_listing(rows):
    found = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        data_path = str(row.get("data") or "")
        parts = [part for part in data_path.split("/") if part]
        if "items" not in parts:
            continue
        stem = Path(data_path).stem
        item = _item_row(stem, parts[parts.index("items") + 1], row)
        if item:
            found[item["id"]] = item
    _sync_items(list(found.values()))
    return _sorted_items({key: item for key, item in found.items() if item.get("tradable", 1)})


def _catalog_from_zip(status=None):
    """Запасной путь: весь архив базы, если короткий список недоступен."""
    _tell(status, "Качаю архив базы EXBO, около 190 МБ")
    tmp = DIR / "stalzone-database.zip"
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            with client.stream("GET", DB_ZIP, headers={"User-Agent": UA}) as src:
                src.raise_for_status()
                total = int(src.headers.get("content-length") or 0)
                got = 0
                with tmp.open("wb") as dst:
                    for chunk in src.iter_bytes(1024 * 1024):
                        dst.write(chunk)
                        got += len(chunk)
                        if total:
                            _tell(status, f"Архив базы {got // 1048576} из {max(total, got) // 1048576} МБ")
                        else:
                            _tell(status, f"Архив базы {got // 1048576} МБ")
        return _items_in_zip(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _items_in_zip(path):
    found = {}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if "/ru/items/" not in name or not name.endswith(".json"):
                continue
            if "/_variants/" in name:
                continue
            stem = Path(name).stem
            if stem.isdigit():
                continue
            data = json.loads(zf.read(name))
            parts = name.split("/")
            try:
                cat = parts[parts.index("items") + 1]
            except ValueError:
                continue
            icon = ""
            if "/items/" in name:
                icon = "/icons/" + name.split("/items/", 1)[1].rsplit(".", 1)[0] + ".png"
            item = _item_row(data.get("id") or stem, cat, data, icon)
            if item:
                found[item["id"]] = item
    _sync_items(list(found.values()))
    return _sorted_items({key: item for key, item in found.items() if item.get("tradable", 1)})


def _item_row(item_id, cat, data, icon=""):
    item_id = str(item_id or "")
    if not item_id or item_id.isdigit():
        return None
    status = data.get("status")
    if isinstance(status, dict):
        status = str(status.get("state") or "")
    else:
        status = str(status or "")
    title = ((data.get("name") or {}).get("lines") or {}).get("ru") or item_id
    row = {
        "id": item_id,
        "name": title,
        "cat": cat,
        "color": data.get("color") or "DEFAULT",
        "icon": str(data.get("icon") or icon or ""),
        "status": status,
    }
    tradable, reason = stalzone_db.classify(row)
    row["tradable"] = tradable
    row["reason"] = reason
    return row


def _sorted_items(found):
    items = list(found.values())
    items.sort(key=lambda item: item["name"].lower())
    log(f"В базе EXBO {len(items)} предметов")
    return items


def _off_auction():
    """Предметы, которые нельзя купить или продать, и те, кого аукцион не знает."""
    now = time.time()
    fresh = set()
    for slug, ts in _off_map().items():
        if now - ts < 14 * 86400:
            fresh.add(slug)
    try:
        fresh.update(stalzone_db.untradable_ids(DIR / "items.db"))
    except Exception:
        pass
    return fresh


def _off_map():
    global _OFF
    with _OFF_LOCK:
        if _OFF is None:
            path = DIR / "not_on_auction.json"
            _OFF = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _OFF = {k: float(v) for k, v in raw.items()}
                    elif isinstance(raw, list):
                        _OFF = {k: time.time() for k in raw}
                except Exception:
                    _OFF = {}
        return _OFF


def _remember_off(slug):
    global _LISTING
    book = _off_map()
    with _OFF_LOCK:
        book[slug] = time.time()
        (DIR / "not_on_auction.json").write_text(
            json.dumps(book, ensure_ascii=False), encoding="utf-8"
        )
    try:
        stalzone_db.mark_untradable(DIR / "items.db", slug, "auction")
    except Exception:
        pass
    with _LISTING_LOCK:
        _LISTING = None


def _quiet_map():
    global _QUIET
    with _QUIET_LOCK:
        if _QUIET is None:
            path = DIR / "quiet_lots.json"
            _QUIET = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _QUIET = {k: float(v) for k, v in raw.items()}
                except Exception:
                    _QUIET = {}
        return _QUIET


def quiet_lots():
    """Пустые лоты не трогаем повторно следующие полчаса. История при этом не запрашивается."""
    now = time.time()
    return {slug for slug, ts in _quiet_map().items() if now - ts < QUIET_FOR}


def _remember_quiet(slug):
    global _QUIET_DIRTY
    book = _quiet_map()
    with _QUIET_LOCK:
        book[slug] = time.time()
        _QUIET_DIRTY = True
    _flush_quiet(False)


def _flush_quiet(force=False):
    global _QUIET_DIRTY, _QUIET_FLUSH_AT
    now = time.time()
    if not force and (not _QUIET_DIRTY or now < _QUIET_FLUSH_AT):
        return
    book = _quiet_map()
    with _QUIET_LOCK:
        if not force and not _QUIET_DIRTY:
            return
        fresh = {key: ts for key, ts in book.items() if now - ts < QUIET_FOR}
        book.clear()
        book.update(fresh)
        try:
            (DIR / "quiet_lots.json").write_text(json.dumps(book), encoding="utf-8")
        except OSError:
            pass
        _QUIET_DIRTY = False
        _QUIET_FLUSH_AT = now + 2


def _sell_map():
    global _SELL
    with _SELL_LOCK:
        if _SELL is None:
            path = DIR / "sell_cache.json"
            _SELL = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _SELL = raw
                except Exception:
                    _SELL = {}
        return _SELL


def _sell_id(slug, key, amount):
    return f"{slug}|{amount}|{key}"


def _stored_sell(sid, now):
    book = _sell_map()
    with _SELL_LOCK:
        hit = book.get(sid) or {}
    sell = hit.get("sell")
    ts = hit.get("ts") or 0
    if sell and now - ts <= SELL_FOR:
        return float(sell)
    try:
        return market.open_store(DIR / "market.db").sell(sid, now)
    except Exception:
        return None


def _still_dear(slug, lots):
    """Историю не качаем, если даже прошлая обычная цена не даёт запаса."""
    now = time.time()
    groups = {}
    for lot in lots:
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0:
            continue
        groups.setdefault(_sell_id(slug, side_key(lot.get("additional")), amt), []).append(buy / amt)
    if not groups:
        return False
    for sid, units in groups.items():
        sell = _stored_sell(sid, now)
        if not sell or min(units) <= sell * 0.92:
            return False
    return True


def _note_exits(slug, book):
    now = time.time()
    store = _sell_map()
    with _SELL_LOCK:
        for key, rows in (book.get("sales") or {}).items():
            by_amount = {}
            for row in rows:
                if len(row) < 3:
                    continue
                by_amount.setdefault(row[0], []).append((row[1], row[2]))
            for amount, samples in by_amount.items():
                got = _fair_exit(samples, now, 4 if key is not None else 6)
                if not got:
                    continue
                store[_sell_id(slug, key, amount)] = {"sell": got[0], "ts": now}


def flush_sells():
    book = _sell_map()
    now = time.time()
    with _SELL_LOCK:
        fresh = {key: row for key, row in book.items() if now - (row.get("ts") or 0) <= SELL_FOR}
        book.clear()
        book.update(fresh)
        try:
            (DIR / "sell_cache.json").write_text(json.dumps(book), encoding="utf-8")
        except OSError:
            pass
        try:
            market.open_store(DIR / "market.db").put_sells(
                [(sid, row.get("sell"), row.get("ts")) for sid, row in book.items()]
            )
        except Exception:
            pass
    _flush_quiet(True)


def _qname(qlt):
    if qlt is None:
        return "—"
    qlt = int(qlt)
    return QLT[qlt] if 0 <= qlt < len(QLT) else str(qlt)


def _stamp(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return ""
    return dt.astimezone(MSK).strftime("%d.%m %H:%M")


def _left(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return ""
    sec = int((dt - datetime.now(timezone.utc)).total_seconds())
    if sec <= 0:
        return "0м"
    hours, minutes = sec // 3600, (sec % 3600) // 60
    return f"{hours}ч {minutes}м" if hours else f"{minutes}м"


def auction_price_stats(data, qname="Все", lo=0, hi=15):
    """Up to 100 completed sales within a week, each valued per unit."""
    now = time.time()
    cutoff = now - 7 * 86400
    try:
        lo, hi = int(lo), int(hi)
    except (TypeError, ValueError):
        lo, hi = 0, 15
    pages = data.setdefault("history_pages", [])
    sample = []
    truncated = False
    while True:
        sample = []
        oldest = None
        for page in pages:
            for row in page:
                try:
                    dt = datetime.fromisoformat(str(row.get("time")).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        continue
                    ts = dt.timestamp()
                    oldest = ts if oldest is None else min(oldest, ts)
                    amount = int(row.get("amount") or 0)
                    price = float(row.get("price") or 0)
                    add = row.get("additional") or {}
                    quality = add.get("qlt")
                    point = int(add.get("ptn") or 0)
                    if not cutoff <= ts <= now or amount <= 0 or not 0 < price < float('inf'):
                        continue
                    if qname and qname != "Все" and _qname(quality) != qname:
                        continue
                    if quality is not None and not lo <= point <= hi:
                        continue
                    sample.append((ts, price / amount))
                except (TypeError, ValueError, OverflowError):
                    continue
        sample.sort(key=lambda row: row[0], reverse=True)
        if len(sample) >= 100:
            sample = sample[:100]
            break
        # EXBO returns history newest first. Short pages exhaust the history.
        if pages and (len(pages[-1]) < 200 or (oldest is not None and oldest < cutoff)):
            break
        if len(pages) >= 50:
            truncated = True
            break
        offset = len(pages) * 200
        result = get_json(f"{EXBO}/RU/auction/{data['slug']}/history?additional=true&limit=200&offset={offset}")
        pages.append(result.get("prices") or [])
    units = [unit for _ts, unit in sample]
    return {"mean": statistics.mean(units) if units else None,
            "median": statistics.median(units) if units else None,
            "count": len(units), "truncated": truncated}


def item_view(slug, name=""):
    """Живые лоты и последние продажи одного предмета с EXBO."""
    lots_raw = []
    offset = 0
    total = None
    while total is None or offset < total:
        data = get_json(
            f"{EXBO}/RU/auction/{slug}/lots?additional=true&limit=200&offset={offset}"
            "&sort=buyout_price&order=asc"
        )
        total = data.get("total") or 0
        batch = data.get("lots") or []
        if not batch:
            break
        lots_raw.extend(batch)
        offset += 200
        if offset >= 600 or offset >= total:
            break
    hist = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset=0")
    lots = []
    for lot in lots_raw:
        add = lot.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        lots.append({
            "qlt": None if qlt is None else int(qlt),
            "qname": _qname(qlt),
            "ptn": 0 if ptn is None else int(ptn),
            "amount": amt,
            "start": int(lot.get("startPrice") or 0),
            "buyout": buy,
            "unit": (buy / amt) if buy > 0 and amt > 0 else 0,
            "left": _left(lot.get("endTime")),
        })
    sales = []
    for p in hist.get("prices") or []:
        add = p.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        amt = max(int(p.get("amount") or 1), 1)
        price = int(p.get("price") or 0)
        sales.append({
            "time": _stamp(p.get("time")),
            "qlt": None if qlt is None else int(qlt),
            "qname": _qname(qlt),
            "ptn": 0 if ptn is None else int(ptn),
            "amount": amt,
            "price": price,
            "unit": price / amt,
        })
    verdict = flip_reason(slug, name or slug, lots_raw, _sales_book(hist.get("prices") or []), allow_single=True)
    return {
        "lots": lots, "sales": sales, "total": total or len(lots_raw), "verdict": verdict,
        "slug": slug, "history_pages": [hist.get("prices") or []],
    }


def write_buys(rows):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    body, lines = [], [f"Выкуп  {now}", "Медиана за 7 дней, после 5% плюс от 10 тысяч. Выше в списке больший плюс.", ""]
    if not rows:
        body.append("<tr><td colspan='8'>Сейчас нет лота, который после 5% даст хотя бы 10 тысяч и который ещё купят.</td></tr>")
        lines.append("выкупать нечего")
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{r['name']}</td><td>{r['copies']} x {r['amount']} шт</td>"
            f"<td>{r['buyout']:,}</td><td>{r['unit']:.0f}</td><td>{r['med']:.0f}</td>"
            f"<td>{r['gain']:,.0f}</td><td>{r['roi'] * 100:.0f}%</td><td>{r['spend']:,}</td></tr>".replace(",", " ")
        )
        lines.append(r.get("plan") or (
            f"{r['name']}: выкупить {r['copies']} лот(ов) по {r['buyout']} "
            f"за {r['amount']} шт ({r['unit']:.0f}/шт, рынок {r['med']:.0f}) прибыль ~{r['gain']:.0f}"
        ))
    html = f"""<!doctype html><meta charset="utf-8"><title>Выкуп {now}</title>
<style>body{{font:15px/1.4 sans-serif;background:#111;color:#eee;margin:24px}}
table{{border-collapse:collapse;width:100%;max-width:980px}}
td,th{{border-bottom:1px solid #333;padding:6px 10px;text-align:left}}</style>
<h1>Что выкупать</h1>
<p>Обновлено {now}. Бюджет {BUDGET:,} руб.</p>
<table><tr><th>Предмет</th><th>Лоты</th><th>Выкуп</th><th>За штуку</th><th>Продают</th><th>Прибыль</th><th>Доходность</th><th>Потратить</th></tr>
{''.join(body)}</table>"""
    BUY_HTML.write_text(html, encoding="utf-8")
    (DIR / "buy_now.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"записано {BUY_HTML.name}, позиций {len(rows)}")



SELL_STACK = {"7l127": 3000}


def side_key(add):
    add = add or {}
    attrs = add.get("attributes") or []
    sig = tuple(sorted(a.get("definitionId") or "" for a in attrs if a.get("definitionId")))
    if "qlt" not in add and "ptn" not in add and not sig:
        return None
    qlt = add.get("qlt")
    ptn = add.get("ptn")
    qlt = 0 if qlt is None else int(qlt)
    ptn = 0 if ptn is None else int(ptn)
    if ptn < 0 or ptn > 15:
        ptn = 0
    base = (qlt, ptn)
    if sig:
        # Модуль без одинаковых свойств — другой предмет. Общую медиану к нему не клеим.
        return ("mod", base, sig)
    if "qlt" not in add and "ptn" not in add:
        return None
    return base


def module_name(key):
    base, sig = key[1], key[2]
    parts = []
    for raw in sig:
        parts.append(raw.replace("_pre", "").replace("_aff", "").replace("_suf", "").replace("_", " "))
    q = qlabel(base[0], base[1]) if base else ""
    return f"{q} [{', '.join(parts)}]".strip()


def market_book(slug, pages):
    key = (slug, pages)
    with _BOOK_LOCK:
        hit = _BOOK.get(key)
    if hit is not None:
        return hit
    sales = {}
    for page in range(pages):
        if HALT.is_set():
            break
        data = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset={page * 200}")
        batch = data.get("prices") or []
        for p in batch:
            amt = max(int(p.get("amount") or 1), 1)
            price = p.get("price")
            if not price:
                continue
            ts = _epoch(p.get("time"))
            sales.setdefault(side_key(p.get("additional")), []).append((amt, price / amt, ts))
        if len(batch) < 200:
            break
    live = {}
    for lot in cached_live(slug):
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0:
            continue
        unit = buy / amt
        k = side_key(lot.get("additional"))
        if k not in live or unit < live[k]:
            live[k] = unit
    book = {"sales": sales, "live": live}
    with _BOOK_LOCK:
        _BOOK[key] = book
    return book


def usual_sale(prices):
    units = [p[1] if isinstance(p, tuple) else p for p in prices]
    if len(units) < 6:
        return None
    last = units[0]
    ordered = sorted(units)
    mid = statistics.median(ordered)
    if mid <= 0:
        return None
    usable = [v for v in ordered if v >= mid * 0.4]
    if len(usable) < 6:
        return None
    return last, statistics.median(usable), len(usable)


def _epoch(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def drop_market(slug):
    with _BOOK_LOCK:
        for key in list(_BOOK):
            if key[0] == slug:
                _BOOK.pop(key, None)
    with _LIVE_LOCK:
        _LIVE.pop(slug, None)


TRACKER_MIN = 10_000
TRACKER_DEPTH = 7
TRACKER_NEED = 3
# Как у трекера: 1, 3, 4, 7, 14, 30, 90 дней. Короткое окно, если в нём меньше трёх продаж, само расширяется.
DEPTHS = (1, 3, 4, 7, 14, 30, 90)
HORIZONS = (("d1", 1, "1 день"), ("d7", 7, "7 дней"), ("d30", 30, "месяц"))


def _pct(ordered, q):
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _clip_rows(samples):
    units = sorted(row[0] for row in samples)
    if not units:
        return []
    base = statistics.median(units[: max(1, len(units) // 2)])
    if base <= 0:
        return []
    cap = base * 2.5
    return [row for row in samples if row[0] <= cap]


def _fair_of(samples, method):
    units = [row[0] for row in samples]
    if method == "mean":
        return sum(units) / len(units)
    if method == "weighted":
        newest = max(row[1] for row in samples)
        span = max(newest - min(row[1] for row in samples), 3600)
        weight = total = 0.0
        for price, ts in samples:
            w = 0.5 ** ((newest - ts) / span)
            weight += w
            total += price * w
        return total / weight if weight else 0.0
    return statistics.median(units)


def _in_days(samples, now, days):
    limit = days * 86400
    return [row for row in samples if now - row[1] <= limit]


def _select_window(samples, now, depth_days, ignore_depth):
    """7 дней, если продаж хватает. Иначе, как у них при редком предмете, берём более длинное окно от 3 продаж."""
    chosen = _in_days(samples, now, depth_days)
    if not ignore_depth or len(chosen) >= TRACKER_NEED:
        return chosen, depth_days
    for days in DEPTHS:
        if days <= depth_days:
            continue
        wider = _in_days(samples, now, days)
        if len(wider) >= TRACKER_NEED:
            return wider, days
    if len(samples) >= TRACKER_NEED:
        return list(samples), None
    return chosen, depth_days


def _gap_stats(samples):
    times = sorted(row[1] for row in samples)
    if len(times) < 2:
        return None
    gaps = sorted((times[i] - times[i - 1]) / 3600 for i in range(1, len(times)))
    return _pct(gaps, 0.25), _pct(gaps, 0.75), _pct(gaps, 0.80)


def _one_horizon(code, days, title, block, method):
    if len(block) < TRACKER_NEED:
        return {"code": code, "title": title, "status": "INSUFFICIENT_EVIDENCE", "ask": 0, "share": False, "n": len(block), "hours": None}
    kept = _clip_rows(block)
    if not kept:
        return {"code": code, "title": title, "status": "INSUFFICIENT_EVIDENCE", "ask": 0, "share": False, "n": 0, "hours": None}
    gaps = _gap_stats(kept)
    hours = (gaps[0], gaps[1]) if gaps else None
    # 8 из 10 уходят в этот срок, если 80-й перцентиль паузы между продажами не длиннее горизонта.
    share = bool(gaps and gaps[2] <= days * 24)
    return {
        "code": code, "title": title, "status": "ok", "ask": _fair_of(kept, method),
        "share": share, "hours": hours, "n": len(kept),
    }


def _mark_inversion(horizons):
    """Длинный срок не может просить дешевле короткого: сроки тогда расходятся, цены нет."""
    last = None
    for row in horizons:
        if row["status"] != "ok":
            continue
        if last is not None and row["ask"] + 1 < last["ask"] * 0.98:
            row["status"] = "PRICE_INVERSION"
            row["share"] = False
        else:
            last = row


def _net_profit(stack_price, buyout):
    """На руки после 5%: целые рубли, без копеечной ошибки float."""
    gross = int(math.floor(float(stack_price) + 1e-6))
    return gross * 95 // 100 - int(buyout)


def tracker_quote(samples, now, ignore_depth=True, method="median", depth_days=TRACKER_DEPTH):
    """Цена выставления: медиана продаж за глубину (по умолчанию 7 дней). Редкий лот берёт окно длиннее."""
    window, days = _select_window(samples, now, depth_days, ignore_depth)
    kept = _clip_rows(window)
    if len(window) < TRACKER_NEED or not kept:
        return None
    ask = _fair_of(kept, method)
    if ask <= 0:
        return None
    span = max(now - min(row[1] for row in kept), 20 * 60)
    per_h = len(kept) / (span / 3600)
    horizons = []
    for code, horizon_days, title in HORIZONS:
        block = _in_days(samples, now, horizon_days)
        horizons.append(_one_horizon(code, horizon_days, title, block, method))
    _mark_inversion(horizons)
    advisor = next((row for row in horizons if row["status"] == "ok" and row["share"]), None)
    if advisor is None:
        advisor = next((row for row in horizons if row["status"] == "ok"), None)
    return {
        "ask": ask,
        "code": f"d{days}" if days else "all",
        "title": f"{days} дн." if days else "вся история",
        "depth_days": days,
        "advisor": advisor["code"] if advisor else None,
        "advisor_title": advisor["title"] if advisor else None,
        "share": bool(advisor and advisor["share"]),
        "hours": advisor["hours"] if advisor else None,
        "n": len(window),
        "per_h": per_h,
        "per_day": per_h * 24,
        "horizons": horizons,
        "stale_min": None,
        "method": method,
    }


def _fair_exit(samples, now, need):
    """Обычная цена без разовых многомиллионных сделок. Продажи идут от новых к старым."""
    recent = [row for row in samples if now - row[1] <= 12 * 3600]
    if len(recent) < need:
        return None
    recent.sort(key=lambda row: row[1], reverse=True)
    if now - recent[0][1] > 2 * 3600:
        return None
    units = [row[0] for row in recent[:12]]
    ordered = sorted(units)
    base = statistics.median(ordered[: max(1, len(ordered) // 2)])
    if base <= 0:
        return None
    cap = base * 2.5
    kept = [unit for unit in units if unit <= cap]
    if len(kept) < need:
        return None
    normal = [row for row in recent if row[0] <= cap]
    if len(normal) < need or now - normal[0][1] > 2 * 3600:
        return None
    span = max(now - normal[-1][1], 20 * 60)
    per_h = len(normal) / (span / 3600)
    return statistics.median(kept), per_h


def _label_for(name, key):
    qlt_i = None
    qlt_name = ""
    ptn_s = ""
    if isinstance(key, tuple) and key and key[0] != "mod":
        qlt_i = int(key[0])
        qlt_name = QLT[qlt_i] if 0 <= qlt_i < len(QLT) else str(qlt_i)
        ptn_s = f"+{int(key[1])}"
        label = name
    elif isinstance(key, tuple) and key and key[0] == "mod":
        label = f"{name} {module_name(key)}"
    else:
        label = name
    return label, qlt_name, ptn_s, qlt_i


def _hand_bit(profit):
    n = int(profit)
    if n >= 0:
        return f"после 5% плюс {n}"
    return f"после 5% минус {-n}"


def _price_bit(exit_hist, nxt, sell_at):
    if nxt is not None and nxt < exit_hist:
        return f"медиана {exit_hist:.0f}, соседний лот {nxt:.0f}"
    return f"медиана {sell_at:.0f}"


def _judge_group(slug, name, key, amt, rows, hist, now):
    rows = sorted(rows)
    unit, buy = rows[0]
    j = 1
    while j < len(rows) and rows[j][1] == buy:
        j += 1
    copies = j
    nxt = rows[j][0] if j < len(rows) else None
    label, qlt_name, ptn_s, qlt_i = _label_for(name, key)
    quote = tracker_quote(hist, now)
    row = {
        "name": label, "slug": slug, "amount": amt, "buyout": buy,
        "unit": unit, "count": copies, "required_copies": copies,
        "qlt": qlt_name, "ptn": ptn_s, "qlt_i": qlt_i,
        "ok": False, "profit": None,
        "why": f"лот {int(buy)}, у этой пачки меньше трёх продаж, медианы нет",
    }
    if not quote:
        return row
    exit_hist = quote["ask"]
    sell_at = exit_hist if nxt is None else min(exit_hist, nxt)
    profit = _net_profit(sell_at * amt, buy)
    per_h = quote["per_h"]
    price_bit = _price_bit(exit_hist, nxt, sell_at)
    hand = _hand_bit(profit)
    row.update({
        "med": sell_at, "net_u": profit / amt if amt else 0, "profit": profit,
        "roi": profit / buy if buy else 0, "per_h": per_h,
        "per_day": quote["per_day"], "hours": quote.get("hours"),
        "horizon": quote.get("advisor") or quote["code"],
        "horizon_title": quote.get("advisor_title") or quote["title"],
        "share": quote["share"], "stale_min": quote.get("stale_min"),
        "n": quote["n"],
    })
    if profit < TRACKER_MIN:
        row["why"] = f"лот {int(buy)}, {price_bit}, {hand}. Мало: нужно хотя бы {TRACKER_MIN}."
        return row
    if copies > max(1, int(per_h * 1.5)):
        row["why"] = (
            f"лот {int(buy)}, {price_bit}, {hand}. "
            f"Таких лотов {copies}, за час уходит {per_h:.1f}, пачку не сольёшь."
        )
        return row
    row["ok"] = True
    row["why"] = f"Брать: лот {int(buy)}, {price_bit}, {hand}."
    return row


def _sales_book(prices):
    sales = {}
    for p in prices or []:
        amt = max(int(p.get("amount") or 1), 1)
        price = p.get("price")
        if not price:
            continue
        sales.setdefault(side_key(p.get("additional")), []).append((amt, price / amt, _epoch(p.get("time"))))
    return sales


def _groups(slug, name, allow_single, lots, sales):
    now = time.time()
    offers = {}
    for lot in lots or []:
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        add = lot.get("additional") or {}
        if buy <= 0 or amt <= 0 or add.get("personal_on_get"):
            continue
        key = side_key(add)
        if amt <= 1 and not (allow_single or key is not None):
            continue
        offers.setdefault((key, amt), []).append((buy / amt, buy))
    judged = []
    for (key, amt), rows in offers.items():
        hist = []
        for row in (sales or {}).get(key) or []:
            if row[0] != amt:
                continue
            ts = row[2] if len(row) > 2 else now
            hist.append((row[1], ts))
        judged.append(_judge_group(slug, name, key, amt, rows, hist, now))
    return judged


def find_flips(book, slug, name, allow_single=False, limit=3):
    """Лот выгоден, только если его реально покупают прямо сейчас и после комиссии есть запас."""
    judged = _groups(slug, name, allow_single, cached_live(slug), book.get("sales"))
    deals = []
    for row in judged:
        if not row["ok"]:
            continue
        deal = dict(row)
        deal.pop("ok", None)
        deal.pop("why", None)
        deals.append(deal)
    deals.sort(key=lambda r: (r["profit"] * r["count"], r["profit"] * r["per_h"]), reverse=True)
    return deals[:limit]


def flip_reason(slug, name, lots, sales, allow_single=True):
    """Одна строка: почему лот брать или что именно его остановило."""
    judged = _groups(slug, name, allow_single, lots, sales)
    if not judged:
        priced = [
            lot for lot in lots or []
            if int(lot.get("buyoutPrice") or 0) > 0 and int(lot.get("amount") or 0) > 0
        ]
        if not priced:
            return "С выкупом ничего нет."
        return "Одиночный лот без редкости не считаю. Нужна пачка или отмеченный предмет."
    good = [row for row in judged if row["ok"]]
    if good:
        best = max(good, key=lambda r: (r["profit"] * r["count"], r["profit"]))
        return best["why"]
    known = [row for row in judged if row.get("profit") is not None]
    pool = known or judged
    best = max(pool, key=lambda r: (r["profit"] if r.get("profit") is not None else -10 ** 18, -r["buyout"]))
    return best["why"]


def sell_call(last, sold, live):
    if live is None:
        if last < sold * 0.9:
            return "ДЕРЖАТЬ", sold, f"последняя {last:.0f}, обычная {sold:.0f}, выкупа нет"
        return "СЛИТЬ", sold, f"ставь {sold:.0f}"
    if live < sold * 0.9:
        return "ДЕРЖАТЬ", sold, f"лоты просели до {live:.0f}, обычная продажа {sold:.0f}"
    ask = sold if live > sold else live
    return "СЛИТЬ", ask, f"лот {live:.0f}, продажи {sold:.0f}, ставь {ask:.0f}"


def sell_advice(item):
    slug, name = item[0], item[1]
    try:
        book = market_book(slug, 2)
    except Exception as e:
        return {"name": name, "err": str(e)}
    sales = book["sales"]
    if not sales:
        return {"name": name, "err": "нет сделок"}
    key = max(sales, key=lambda k: len(sales[k]))
    got = usual_sale(sales[key])
    if not got:
        return {"name": name, "err": "мало сделок"}
    last, sold, n = got
    act, ask, why = sell_call(last, sold, book["live"].get(key))
    stack = SELL_STACK.get(slug, 0)
    pack = ""
    if stack and ask:
        gross = stack * ask
        pack = f"{rub(gross)} на руки {rub(gross * COMM)}"
    return {
        "name": name, "last": last, "med": sold, "ask": ask,
        "farm": act, "buy": act, "why": why, "pack": pack, "deals": [], "n": n,
    }


def item_advice(item):
    slug, name = item
    try:
        book = market_book(slug, 2)
    except Exception as e:
        return {"name": name, "err": str(e)}
    sales = book["sales"]
    if not sales:
        return {"name": name, "err": "нет сделок"}
    key = max(sales, key=lambda k: len(sales[k]))
    got = usual_sale(sales[key])
    if not got:
        return {"name": name, "err": "мало сделок"}
    last, sold, n = got
    act, ask, why_sell = sell_call(last, sold, book["live"].get(key))
    try:
        deals = find_flips(book, slug, name, allow_single=False)
    except Exception as e:
        return {"name": name, "last": last, "med": sold, "farm": act, "buy": "НЕ ВЫКУПАТЬ", "why": str(e), "deals": []}
    why = flip_reason(slug, name, cached_live(slug), sales, allow_single=False)
    buy_act = "ВЫКУПИТЬ" if deals else "НЕ ВЫКУПАТЬ"
    return {"name": name, "last": last, "med": sold, "ask": ask, "farm": act, "buy": buy_act, "why": why, "why_sell": why_sell, "deals": deals, "n": n}



def _skip_buy(cat, name, color=""):
    low = (name or "").lower()
    if cat in ("bullet", "grenade"):
        return True
    if "подсумок" in low:
        return True
    if any(w in low for w in ("гранатом", "гп-25", "m203", "костер")):
        return True
    if "гранат" in low and cat != "armor":
        return True
    if "пуля" in low and cat in ("misc", "other", "bullet"):
        return True
    if "ящик" in low and any(w in low for w in ("патрон", "гранат", "картеч", "дроб", "вог", "светошум", "m381", "m397")):
        return True
    if "сумка" in low and any(w in low for w in ("патрон", "дроб", "картеч", "пластин")):
        return True
    if "патрон" in low or (cat != "attachment" and "картеч" in low):
        return True
    if cat == "backpacks" and color in ("RANK_NEWBIE", "RANK_STALKER"):
        return True
    if cat in ("weapon", "armor") and color in ("RANK_NEWBIE", "RANK_STALKER"):
        return True
    return False


ERROR_NAMES = {
    "Набор для шитья", "Кислота", "Морозная смесь", "Раствор йода", "Электросмесь",
    "Нитроглицерин", "Анилин", "Антитоксин", "Ноотроп", "Сверло", "Сосуд реактора",
    "Полиэтиленовая основа", "Кевлар", "Баллон с горючей смесью",
    "Патрон 7.62 мм специальный", "Патрон 12.7 мм", "Патрон 12.7 мм ПП",
    "Патрон 12.7 мм снайперский", "Боевая пуля 23x75", "Картечь 23x75", "Баррикада",
    "Патрон 12 калибра жгучий", "Патрон 9 мм жгучий", "Патрон 5.45 мм жгучий",
    "Патрон 5.56 мм жгучий", "Патрон 7.62 мм жгучий", "Патрон 9x39 мм жгучий",
    "Патрон 10 мм бронебойный",
    "«Жребий гладиатора»", "«Горохострел»", "«JFG»", "«Ларец Пандоры»",
    "«Морозный перевал»", "«Ящеробой»", "«Мудрость Перуна»",
    "«USS-01»", "«Магмовый воин»", "«Легенда»", "«Цельнометаллический»",
    "«Взрыв красок»", "«Капеллан»", "«Печь»", "«Псих»",
    "L85A1", "Walther MPK", "АКС-74У", "HK MP5", "ПП-19 «Бизон-2-01»",
    "ПП-19-01 «Витязь»", "FN P90", "АС «Вал»",
    "Прицел оптический Trijicon ACOG", "Прицел оптический Elcan",
    "Прицел оптический Sig Sauer", "Прицел оптический Elcan M145",
    "Прицел оптический Acecare", "Прицел широкоугольный «Ракурс»",
    "Прицел оптический ПСО", "Прицел оптический ПОСП",
    "Прицел оптический ПУ на боковой кронштейн", "Прицел оптический ПУ для СВТ",
    "Прицел оптический «Тюльпан»", "Прицел коллиматорный Micro",
    "Прицел коллиматорный EoTech",
    "Теплый свитер", "Костюм «Штрих»", "«Гражданин»",
    "Тяжелый бронекостюм «Легионер»", "Защитный бронекостюм «Йорш»",
    "Солянка", "Макароны по-флотски", "Заливное", "Фасолевый суп",
    "Портативный квантовый генератор", "Псалмы «Шепота»", "Покрышка",
    "Протоартефакт", "«ClearMind+»", "Рука шныря",
    "Набор компонентов оружия (Сталкер)", "Тройник", "Контейнер 2-го уровня",
}


def buy_targets(favs=None):
    """Весь продаваемый каталог. Избранное не режется категорией. Арты идут первыми."""
    favs = {str(slug) for slug in (favs or ()) if slug}
    single_cats = {
        "artefact", "weapon", "armor", "attachment",
        "containers", "container", "backpacks", "backpack", "grenade", "device",
        "weapon_modules",
    }
    try:
        catalog = auction_listing()
    except Exception as e:
        log(f"каталог аукциона: {e}")
        catalog = []
    if catalog:
        arts, pinned, rest = [], [], []
        off = _off_auction()
        quiet = quiet_lots()
        for item in catalog:
            starred = item["id"] in favs
            if item["id"] in off:
                continue
            blocked = (
                item["cat"] == "weapon_modules"
                or item["name"] in ERROR_NAMES
                or item["id"] in quiet
                or _skip_buy(item["cat"], item["name"], item.get("color"))
            )
            if blocked and not starred:
                continue
            single = starred or item["cat"] in single_cats
            row = (item["id"], item["name"], single, 1, 1)
            if item["cat"] == "artefact":
                arts.append(row)
            elif starred:
                pinned.append(row)
            else:
                rest.append(row)
        if PROTO[0] not in {row[0] for row in arts} and (PROTO[0] in favs or PROTO[1] not in ERROR_NAMES):
            arts.insert(0, (PROTO[0], PROTO[1], True, 1, 1))
        seen = {row[0] for row in arts + pinned + rest}
        for slug in favs:
            if slug not in seen and slug not in off:
                pinned.append((slug, slug, True, 1, 1))
        return arts + pinned + rest
    seen = {}
    for slug in favs:
        seen[slug] = (slug, slug, True, 1, 1)
    for slug, name in ARTS:
        seen[slug] = (slug, name, True, 1, 1)
    for slug, name in list(SHELTER_BUY) + list(CONSUMABLES):
        if slug not in seen:
            seen[slug] = (slug, name, False, 1, 1)
    return list(seen.values())


def _buy_one(item):
    slug, name, single, hist_pages, lot_pages = item
    if HALT.is_set():
        return []
    try:
        lots = live_lots(slug, pages=lot_pages)
        with _LIVE_LOCK:
            _LIVE[slug] = lots
        if HALT.is_set() or not lots:
            if not lots and not HALT.is_set():
                _remember_quiet(slug)
            return []
        if not any(int(lot.get("buyoutPrice") or 0) > 0 for lot in lots):
            return []
        if _still_dear(slug, lots):
            return []
        book = market_book(slug, hist_pages)
        _note_exits(slug, book)
        return find_flips(book, slug, name, allow_single=single)
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        if code == 404:
            _remember_off(slug)
            log(f"{name}: на аукционе этого предмета нет")
        elif code == 429:
            log(f"{name}: лимит запросов, предмет пропущен")
        else:
            log(f"{name}: ошибка {code}")
        return []
    except Exception as e:
        log(f"{name}: {e}")
        return []


def parse_money(text):
    raw = str(text or "").strip().lower().replace(" ", "").replace("\u00a0", "")
    if not raw:
        return 0
    mult = 1
    if raw.endswith("кк"):
        mult = 1_000_000
        raw = raw[:-2]
    elif raw.endswith("м"):
        mult = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("к"):
        mult = 1000
        raw = raw[:-1]
    raw = raw.replace(",", ".")
    if raw.count(".") > 1:
        raw = raw.replace(".", "")
    return max(0, int(float(raw) * mult))


def _hour_gain(item):
    copies = int(item.get("copies") or item.get("count") or 1)
    if copies <= 0:
        return 0.0
    gain = item.get("gain")
    if gain is None:
        gain = float(item.get("profit") or 0) * copies
    return float(gain) * float(item.get("per_h") or 0) / copies


def fit_budget(deals, budget):
    """Сначала самый большой плюс. Процент сам по себе лот наверх не поднимает."""
    ranked = sorted(deals, key=lambda r: ((r.get("gain") or 0), _hour_gain(r)), reverse=True)
    if not budget or budget <= 0:
        return ranked[:40]
    left = int(budget)
    chosen = []
    for row in ranked:
        price = int(row.get("buyout") or 0)
        if price <= 0 or price > left:
            continue
        copies = min(int(row.get("copies") or 1), left // price)
        if copies <= 0 or copies < int(row.get("required_copies") or 1):
            continue
        item = dict(row)
        item["copies"] = copies
        item["spend"] = copies * price
        item["gain"] = copies * (row.get("profit") or 0)
        item["hour_gain"] = _hour_gain(item)
        item["plan"] = _plan(item)
        chosen.append(item)
        left -= item["spend"]
        if len(chosen) >= 40:
            break
    return chosen


def buy_scan(status=None, budget=0, on_update=None, favs=None):
    remote = _pull_hub_deals()
    if remote is not None:
        age = max(0, int(time.time() - float(remote.get("ts") or 0)))
        if status:
            status(f"Общее хранилище, снимок {age // 60} мин {age % 60} с назад")
        shown = fit_budget(remote.get("rows") or [], budget)
        if on_update:
            on_update(shown, int(remote.get("scanned") or 0), int(remote.get("total") or 0))
        return shown
    global _GAP
    _GAP = 0.10
    if status:
        status("Собираю каталог аукциона")
    items = buy_targets(favs)
    total = len(items)
    if status:
        status(f"Выкуп по всему аукциону: {total} предметов. Таблица будет заполняться по ходу")
    deals = []
    done = 0
    if not items or HALT.is_set():
        return []
    with ThreadPoolExecutor(max_workers=AUCTION_WORKERS) as pool:
        remaining = iter(items)
        pending = set()
        def fill():
            while len(pending) < AUCTION_WORKERS and not HALT.is_set():
                item = next(remaining, None)
                if item is None:
                    break
                pending.add(pool.submit(_buy_one, item))
        fill()
        try:
            while pending and not HALT.is_set():
                finished, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for fut in finished:
                    if HALT.is_set():
                        break
                    done += 1
                    try:
                        part = fut.result()
                    except Exception:
                        part = []
                    changed = False
                    if isinstance(part, list) and part:
                        deals.extend(_as_buys(part))
                        changed = True
                    if changed or done % 15 == 0 or done == total:
                        shown = fit_budget(deals, budget)
                        if status:
                            status(f"Выкуп {done}/{total}, в бюджете {len(shown)}")
                        if on_update and (changed or done == total):
                            on_update(shown, done, total)
                fill()
        finally:
            for fut in pending:
                fut.cancel()
            flush_sells()
    _publish_board(deals, done, total)
    return fit_budget(deals, budget)


def _flip_arts(item):
    slug, name = item
    try:
        return find_flips(market_book(slug, 4), slug, name, allow_single=True)
    except Exception:
        return []


def _plan(item):
    if "med" not in item or "amount" not in item:
        return item.get("plan") or ""
    copies = int(item.get("copies") or item.get("count") or 1)
    buy = int(item["buyout"])
    ask = float(item["med"]) * int(item["amount"])
    hand = ask * COMM
    gain = float(item.get("gain") or 0)
    spent = copies * buy
    roi = gain / spent * 100 if spent else 0
    hour = _hour_gain(item)
    extra = ""
    if item.get("horizon"):
        hours = item.get("hours")
        if hours and hours[1] < 1:
            when = f"Обычно уходит за {hours[0] * 60:.0f}–{hours[1] * 60:.0f} мин. "
        elif hours and hours[0] < 1:
            when = f"Обычно уходит за {hours[0] * 60:.0f} мин – {hours[1]:.0f} ч. "
        elif hours:
            when = f"Обычно уходит за {hours[0]:.0f}–{hours[1]:.0f} ч. "
        else:
            when = "Сроки продажи ещё собираются. "
        share = f"8 из 10 таких лотов продаются за {item.get('horizon_title')}. " if item.get("share") else ""
        stale = f"Лента молчит {item['stale_min']} мин. " if item.get("stale_min") else ""
        extra = when + share + f"{float(item.get('per_day') or 0):.1f} продано/день. " + stale
    return (
        f"Купи {copies} по {buy}. Выстави пачку за {ask:.0f}. "
        f"После 5% придёт {hand:.0f}. Плюс {gain:.0f} ({roi:.0f}%). "
        f"Плюс в час {hour:.0f}. " + extra
    )


def _as_buys(deals):
    found = []
    for deal in deals:
        item = dict(deal)
        item["copies"] = item["count"]
        item["spend"] = item["copies"] * item["buyout"]
        item["gain"] = item["copies"] * item["profit"]
        item["hour_gain"] = _hour_gain(item)
        item["plan"] = _plan(item)
        found.append(item)
    return found


def _pack(rows):
    out = []
    for row in rows:
        if isinstance(row, Exception):
            out.append({"name": "позиция", "err": str(row)})
        elif row:
            out.append(row)
    return out


def proto_deals():
    slug, name = PROTO
    try:
        deals = find_flips(market_book(slug, 4), slug, name, allow_single=True, limit=30)
    except Exception as e:
        return [{"name": name, "err": str(e)}]
    rows = []
    for deal in deals:
        q = " ".join(part for part in (deal.get("qlt"), deal.get("ptn")) if part)
        rows.append({
            "name": deal["name"], "qlt": q or name, "n": deal.get("n") or 0,
            "buy": "ВЫКУПИТЬ", "farm": "СЛИТЬ",
            "cheap": deal["unit"], "med": deal["med"], "net": deal["profit"],
        })
    rows.sort(key=lambda r: r.get("net") or 0, reverse=True)
    return rows


def run_once(status=None, only=None, budget=0, on_update=None, favs=None):
    _LIVE.clear()
    _BOOK.clear()
    log("прогон старт" if not only else f"прогон: {only}")

    def say(msg):
        log(msg)
        if status:
            status(msg)

    want = only or None
    out = {}
    if want == "buys":
        deals = buy_scan(say, budget, on_update, favs)
        out["buys"] = deals
        if deals:
            spent = sum(r["spend"] for r in deals)
            gain = sum(r["gain"] for r in deals)
            say(f"Выкуп: {len(deals)} лотов, вложено {rub(spent)} из {rub(budget)}, плюс {rub(gain)}")
            if not HALT.is_set():
                write_buys(deals)
        else:
            say("Выкуп: сейчас нет лота, который купят и который даст плюс")
        log("выкуп готов")
        return out
    out = {}
    sell_rank = {"ДЕРЖАТЬ": 0, "СЛИТЬ": 1}
    buy_rank = {"ВЫКУПИТЬ": 0, "НЕ ВЫКУПАТЬ": 1}

    def sell_sort(rows):
        rows.sort(key=lambda r: (sell_rank.get(r.get("farm"), 2), -(r.get("med") or 0)))
        return rows

    def buy_sort(rows):
        rows.sort(key=lambda r: (buy_rank.get(r.get("buy"), 2), r.get("name") or ""))
        return rows

    if want in (None, "farm") and not HALT.is_set():
        say(f"Фарм, цена продажи: {len(BARTER_FARM)}")
        out["farm"] = sell_sort(_pack(parallel(BARTER_FARM, sell_advice)))
    if want in (None, "arsenal") and not HALT.is_set():
        say(f"Арсенал, цена продажи: {len(ARSENAL)}")
        out["arsenal"] = sell_sort(_pack(parallel(ARSENAL, sell_advice)))
    if want in (None, "shelter_buy") and not HALT.is_set():
        say(f"Убежище, купить материалы: {len(SHELTER_BUY)}")
        out["shelter_buy"] = buy_sort(_pack(parallel(SHELTER_BUY, item_advice)))
    if want in (None, "shelter_sell") and not HALT.is_set():
        say(f"Убежище, продать готовое: {len(SHELTER_SELL)}")
        out["shelter_sell"] = sell_sort(_pack(parallel(SHELTER_SELL, sell_advice)))
    if want in (None, "consumables") and not HALT.is_set():
        say(f"Расходники, {len(CONSUMABLES)} позиций")
        out["consumables"] = buy_sort(_pack(parallel(CONSUMABLES, item_advice)))
    if want in (None, "arts") and not HALT.is_set():
        say("Популярные арты")
        arts, checked = art_deals()
        out["arts"] = [r for r in arts if (r.get("net") or 0) > 0 or r.get("err")]
        out["checked"] = checked
    buys = []
    if "shelter_buy" in out or "consumables" in out:
        for row in out.get("shelter_buy", []) + out.get("consumables", []):
            buys.extend(_as_buys(row.get("deals") or []))
    if want in (None, "arts") and not HALT.is_set():
        say("Перекуп артов, только то что покупают")
        for part in parallel(ARTS, _flip_arts):
            if isinstance(part, list):
                buys.extend(_as_buys(part))
    if buys:
        buys = fit_budget(buys, budget)
        out["buys"] = buys
        spent = sum(r["spend"] for r in buys)
        gain = sum(r["gain"] for r in buys)
        say(f"Выкуп: {len(buys)} лотов, вложено {rub(spent)} из {rub(budget)}, плюс {rub(gain)}")
        if not HALT.is_set():
            write_buys(buys)
    elif want in (None, "shelter_buy", "consumables", "arts"):
        out["buys"] = []
        say("Выкуп: сейчас нет лота, который купят и который даст плюс")
    if want in (None, "protos") and not HALT.is_set():
        say("Протоартефакты")
        out["protos"] = proto_deals()
    log("раздел готов" if want else "общий прогон готов")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--every", type=int, default=30)
    p.add_argument("--buys", action="store_true")
    args = p.parse_args()
    if args.buys:
        log("считаю выгодный выкуп")
        write_buys(buy_scan(budget=BUDGET))
        return
    run_once()
    if args.once:
        return
    log(f"фон каждые {args.every} мин. остановить: Ctrl+C")
    while True:
        time.sleep(max(args.every, 5) * 60)
        try:
            run_once()
        except Exception:
            log(traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("стоп")
        sys.exit(0)
