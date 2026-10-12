# -*- coding: utf-8 -*-
"""Карта Лунара: подложка и метки по категориям. Свои файлы игры сюда не входят."""
import json
import math
import struct
import re
import hashlib
from pathlib import Path

import httpx

ROOT = "https://lunar-zone.ru/web-api/maps2d"


def catalog():
    data = _json(ROOT)
    maps = []
    for item in data.get("maps") or []:
        count = int(item.get("markers") or 0)
        if count <= 0 or not item.get("slug"):
            continue
        maps.append({"slug": item["slug"], "title": item.get("title") or item["slug"], "markers": count})
    maps.sort(key=lambda row: row["markers"], reverse=True)
    return maps


def load(folder, slug):
    slug = str(slug or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", slug):
        raise ValueError("Неверная локация карты")
    manifest = _json(f"{ROOT}/{slug}")
    version = manifest.get("version") or {}
    chunks = manifest.get("chunks") or []
    salt = str((manifest.get("format") or {}).get("salt") or "")
    entry = str((manifest.get("format") or {}).get("entry") or "")
    stamp = _cache_stamp(manifest)
    cache = Path(folder) / "lunar_cache"
    cache.mkdir(parents=True, exist_ok=True)
    saved = _read(cache / f"{slug}.json")
    if not saved or saved.get("stamp") != stamp:
        saved = {
            "stamp": stamp,
            "titles": manifest.get("titles") or [],
            "categories": _categories(manifest.get("categories") or []),
            "markers": _markers(cache, salt, entry, slug, chunks),
        }
        (cache / f"{slug}.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    game = manifest.get("map") or {}
    return {
        "lunar": True,
        "slug": slug,
        "title": game.get("title") or slug,
        "width": int(version.get("width") or 1),
        "height": int(version.get("height") or 1),
        "overview": version.get("overview") or "",
        "tiles": _tiles(version),
        "titles": saved["titles"],
        "categories": saved["categories"],
        "markers": saved["markers"],
    }


def _cache_stamp(manifest):
    metadata = {key: manifest.get(key) for key in ('format','titles','categories','chunks')}
    version = manifest.get('version') or {}
    metadata['version'] = {key: version.get(key) for key in ('id','width','height','tileSize','zoomMax','grid')}
    return hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()


def _tiles(version):
    grid = {}
    for key, cells in (version.get("grid") or {}).items():
        level = str(key)[1:] if str(key).startswith("z") else str(key)
        grid[level] = cells
    return {
        "base": version.get("tileBase") or "",
        "query": version.get("tileQuery") or "",
        "size": int(version.get("tileSize") or 512),
        "zoomMax": int(version.get("zoomMax") or 0),
        "grid": grid,
    }


def _categories(rows):
    out = []
    for row in rows:
        if not int(row.get("markers") or 0):
            continue
        out.append({
            "id": int(row["id"]),
            "title": row.get("title") or "Метки",
            "color": row.get("color") or "#e0b15a",
            "count": int(row["markers"]),
        })
    return out


def _markers(cache, salt, entry, slug, chunks):
    if not salt or not entry:
        raise RuntimeError("Лунар не отдал разборщик карты")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", salt):
        raise ValueError("Неверный идентификатор разборщика карты")
    try:
        from wasmtime import Instance, Module, Store
    except ImportError as error:
        raise RuntimeError("Нет wasmtime. Пересобери программу через build_exe.bat") from error
    wasm = cache / f"dec-{salt}.wasm"
    if not wasm.exists() or wasm.stat().st_size < 100:
        wasm.write_bytes(_bytes(f"{ROOT}/dec.wasm?v={salt}"))
    store = Store()
    instance = Instance(store, Module(store.engine, wasm.read_bytes()), [])
    exports = instance.exports(store)
    run = exports.get(entry)
    memory = exports.get("m")
    if run is None or memory is None:
        raise RuntimeError("Разборщик карты не подошёл")
    marks = []
    with httpx.Client(timeout=40, headers={"User-Agent": "STALZONE"}) as client:
        for chunk in chunks:
            count = int(chunk.get("count") or 0)
            if count <= 0:
                continue
            resp = client.get(f"{ROOT}/{slug}/c/{chunk['id']}")
            if resp.status_code == 429:
                raise RuntimeError("Лунар ограничил запросы. Открой эту локацию позже")
            resp.raise_for_status()
            body = resp.content
            got = int(resp.headers.get("X-Map-Count") or count)
            marks.extend(_decode(store, memory, run, body, got, int(chunk.get("x") or 0), int(chunk.get("z") or 0)))
    return marks


def _decode(store, memory, run, data, count, origin_x, origin_z):
    if count <= 0 or not data:
        return []
    need = 4096 + len(data) + 20 * count
    page = 65536
    have = memory.size(store) * page
    if need > have:
        memory.grow(store, math.ceil((need - have) / page))
    memory.write(store, data, 1024)

    def align(value, step):
        return math.ceil(value / step) * step

    cursor = 1024 + len(data) + 16
    x_at = align(cursor, 4)
    cursor = x_at + 4 * count
    z_at = align(cursor, 4)
    cursor = z_at + 4 * count
    icon_at = align(cursor, 2)
    cursor = icon_at + 2 * count
    cat_at = align(cursor, 2)
    cursor = cat_at + 2 * count
    cursor = align(cursor, 2) + 2 * count
    id_at = align(cursor, 4)
    cursor = id_at + 4 * count
    name_at = align(cursor, 2)
    if run(store, 1025, len(data) - 1, origin_x, origin_z, x_at, z_at, icon_at, cat_at, align(cat_at + 2 * count, 2), id_at, name_at, count) != count:
        raise RuntimeError("Кусок карты не разобрался")
    xs = struct.unpack_from("<" + "f" * count, memory.read(store, x_at, x_at + 4 * count))
    zs = struct.unpack_from("<" + "f" * count, memory.read(store, z_at, z_at + 4 * count))
    cats = struct.unpack_from("<" + "H" * count, memory.read(store, cat_at, cat_at + 2 * count))
    names = struct.unpack_from("<" + "H" * count, memory.read(store, name_at, name_at + 2 * count))
    return [[int(round(x)), int(round(z)), int(cat), int(name)] for x, z, cat, name in zip(xs, zs, cats, names)]


def _json(url):
    with httpx.Client(timeout=40, headers={"User-Agent": "STALZONE"}) as client:
        resp = client.get(url)
    if resp.status_code == 429:
        raise RuntimeError("Лунар ограничил запросы. Подожди минуту")
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("message") or "Лунар отказал")
    return data


def _bytes(url):
    with httpx.Client(timeout=40, headers={"User-Agent": "STALZONE"}) as client:
        resp = client.get(url)
    resp.raise_for_status()
    return resp.content


def _read(path):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
