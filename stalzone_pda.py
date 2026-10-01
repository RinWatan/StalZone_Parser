# -*- coding: utf-8 -*-
"""Карта ПДА из клиента. Куски .ol собираются в png рядом с программой."""
import hashlib
import os
import re
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from game_window import running_game_exes

TAILS = (
    Path("modassets") / "assets" / "pda" / "global_map",
    Path("runtime") / "stalcraft" / "modassets" / "assets" / "pda" / "global_map",
)
MIP = 2
XOR = 103
NULL = 71


def map_root(folder):
    found = locate(folder)
    return found or Path(folder) / "pda-not-found"


def locate(folder):
    folder = Path(folder)
    for start in _starts(folder):
        found = pda_folder(start)
        if found:
            _remember(folder, found)
            return found
    return None


def pda_folder(start):
    """От exe, корня клиента или самой папки кусков до global_map."""
    current = Path(start)
    for _ in range(10):
        if _has_tiles(current):
            return current
        for tail in TAILS:
            nested = current / tail
            if _has_tiles(nested):
                return nested
        if current.parent == current:
            break
        current = current.parent
    return None


def _has_tiles(path):
    try:
        return path.is_dir() and any(path.glob("r.*.ol"))
    except OSError:
        return False


def _starts(folder):
    override = _text_file(folder / "map_dir.txt")
    if override:
        yield Path(override)
    remembered = _text_file(folder / "pda_root.txt")
    if remembered:
        yield Path(remembered)
    for exe in running_game_exes():
        yield Path(exe)
    for library in _steam_libraries():
        yield library / "steamapps" / "common" / "STALCRAFT"
        yield library / "steamapps" / "common" / "STALZONE"
    for env in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            yield Path(base) / "EXBO"
    yield from _launcher_roots()
    yield from _epic_locations()


def _remember(folder, found):
    try:
        (Path(folder) / "pda_root.txt").write_text(str(found), encoding="utf-8")
    except OSError:
        pass


def _text_file(path):
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip().strip('"')
    except OSError:
        return ""


def _steam_libraries():
    roots = []
    for steam in _steam_installs():
        roots.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if not vdf.exists():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in re.findall(r'"path"\s+"([^"]+)"', text):
            roots.append(Path(raw.replace("\\\\", "\\")))
    return roots


def _steam_installs():
    found = []
    if os.name == "nt":
        import winreg
        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    value, _ = winreg.QueryValueEx(handle, "SteamPath")
            except OSError:
                continue
            if value:
                found.append(Path(value))
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            found.append(Path(base) / "Steam")
    return found


def _launcher_roots():
    """Лаунчер часто стоит не в AppData, а как E:\\games\\EXBO."""
    names = (
        Path("games") / "EXBO",
        Path("Games") / "EXBO",
        Path("EXBO"),
        Path("games") / "STALCRAFT",
        Path("Games") / "STALCRAFT",
        Path("Games") / "Stalcraft",
        Path("VK Play") / "Stalcraft",
    )
    for drive in _drives():
        for name in names:
            yield drive / name


def _drives():
    if os.name != "nt":
        return []
    return [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]


def _epic_locations():
    program_data = os.environ.get("PROGRAMDATA")
    if not program_data:
        return
    manifests = Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not manifests.is_dir():
        return
    for item in manifests.glob("*.item"):
        try:
            text = item.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "stalcraft" not in text.lower() and "stalzone" not in text.lower():
            continue
        match = re.search(r'"InstallLocation"\s*:\s*"([^"]+)"', text)
        if match:
            yield Path(match.group(1).replace("\\\\", "\\"))


def list_maps(root):
    root = Path(root)
    if not root.exists():
        return []
    found = []
    direct = sorted(root.glob("r.*.ol"))
    if direct:
        found.append({"slug": "global_map", "title": "Глобальная", "dir": str(root), "count": len(direct)})
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        tiles = list(child.glob("r.*.ol"))
        if tiles:
            found.append({
                "slug": _slug(child.name),
                "title": child.name,
                "dir": str(child),
                "count": len(tiles),
            })
    return found


def _slug(name):
    raw = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return raw[:48] or "map"


def prepare(source, cache_dir):
    """Возвращает список кусков и базовый адрес локального сервера."""
    source = Path(source)
    tiles = sorted(source.glob("r.*.ol"))
    if not tiles:
        raise FileNotFoundError("В папке нет кусков r.*.ol")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(tiles)
    marker = cache / "stamp.txt"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == stamp and any(cache.glob("*.png")):
        files = _existing(cache, tiles)
    else:
        files = []
        for path in tiles:
            try:
                files.append(_write_tile(path, cache))
            except Exception:
                continue
        if not files:
            raise ValueError("Ни один кусок не разобрался")
        marker.write_text(stamp, encoding="utf-8")
    return {
        "tile": 2048 >> MIP,
        "tiles": [item for item in files if item],
        "base": _serve(cache.parent) + cache.name + "/",
    }


def _stamp(tiles):
    lines = []
    for path in tiles:
        stat = path.stat()
        lines.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()


def _existing(cache, tiles):
    ready = []
    for path in tiles:
        x, y = _coords(path.name)
        name = _file(x, y)
        if (cache / name).exists():
            ready.append({"x": x, "y": y, "file": name})
    return ready


def _coords(name):
    body = name[2:-3]
    x, y = body.split(".")
    return int(x), int(y)


def _file(x, y):
    return f"{x}_{y}.png".replace("-", "m")


def _write_tile(path, cache):
    x, y = _coords(path.name)
    name = _file(x, y)
    image = _decode(path.read_bytes(), MIP)
    _save_png(image, cache / name)
    return {"x": x, "y": y, "file": name}


def _decode(data, mip_index):
    import lz4.block

    offset = 4
    width, height, mips = struct.unpack_from(">III", data, offset)
    offset += 12
    raw = data[offset:offset + 16]
    offset += 16
    fmt = bytes(byte ^ XOR for byte in raw if byte != NULL)
    if fmt != b"DXT1":
        raise ValueError("кусок не DXT1: " + fmt.decode("ascii", "replace"))
    offset += 1
    uncompressed = struct.unpack_from(">" + "I" * mips, data, offset)
    offset += 4 * mips
    compressed = struct.unpack_from(">" + "I" * mips, data, offset)
    offset += 4 * mips
    length = struct.unpack_from(">H", data, offset)[0]
    offset += 2 + length
    chosen = min(mip_index, mips - 1)
    for index in range(mips):
        block = data[offset:offset + compressed[index]]
        offset += compressed[index]
        if index == chosen:
            plain = lz4.block.decompress(block, uncompressed_size=uncompressed[index])
            return _dxt1(plain, width >> index, height >> index)
    raise ValueError("нет картинки в куске")


def _dxt1(buf, width, height):
    pix = bytearray(width * height * 3)
    offset = 0
    for by in range(height // 4):
        for bx in range(width // 4):
            color0, color1, bits = struct.unpack_from("<HHI", buf, offset)
            offset += 8
            colors = [_rgb565(color0), _rgb565(color1)]
            if color0 > color1:
                colors.append(tuple((2 * a + b) // 3 for a, b in zip(colors[0], colors[1])))
                colors.append(tuple((a + 2 * b) // 3 for a, b in zip(colors[0], colors[1])))
            else:
                colors.append(tuple((a + b) // 2 for a, b in zip(colors[0], colors[1])))
                colors.append((0, 0, 0))
            for index in range(16):
                color = colors[(bits >> (2 * index)) & 3]
                x = bx * 4 + index % 4
                y = by * 4 + index // 4
                at = (y * width + x) * 3
                pix[at:at + 3] = bytes(color)
    return pix, width, height


def _rgb565(color):
    return (
        ((color >> 11) & 31) * 255 // 31,
        ((color >> 5) & 63) * 255 // 63,
        (color & 31) * 255 // 31,
    )


def _save_png(image, path):
    import zlib
    pix, width, height = image
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(pix[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 1)) + chunk(b"IEND", b"")
    path.write_bytes(png)


_port = None
_lock = threading.Lock()


def _serve(cache_root):
    global _port
    with _lock:
        if _port:
            return f"http://127.0.0.1:{_port}/"
        root = Path(cache_root).resolve()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                rel = unquote(self.path.split("?", 1)[0]).lstrip("/")
                target = (root / rel).resolve()
                if root not in target.parents or target.suffix != ".png" or not target.is_file():
                    self.send_error(404)
                    return
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        _port = server.server_address[1]
        threading.Thread(target=server.serve_forever, name="STALZONE-PDA", daemon=True).start()
        return f"http://127.0.0.1:{_port}/"
