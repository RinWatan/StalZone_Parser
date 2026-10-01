# -*- coding: utf-8 -*-
"""Один предмет в поиск аукциона. Координаты из screen_slots.json."""
import ctypes
import json
import sys
import time

_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def _send(inputs):
    arr = (_INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))


def _click(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.03)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)


def _tap(vk):
    down = _INPUT()
    down.type = 1
    down.u.ki.wVk = vk
    up = _INPUT()
    up.type = 1
    up.u.ki.wVk = vk
    up.u.ki.dwFlags = 0x0002
    _send([down, up])


def _tap_ctrl(vk):
    ctrl = _INPUT()
    ctrl.type = 1
    ctrl.u.ki.wVk = 0x11
    key = _INPUT()
    key.type = 1
    key.u.ki.wVk = vk
    key_up = _INPUT()
    key_up.type = 1
    key_up.u.ki.wVk = vk
    key_up.u.ki.dwFlags = 0x0002
    ctrl_up = _INPUT()
    ctrl_up.type = 1
    ctrl_up.u.ki.wVk = 0x11
    ctrl_up.u.ki.dwFlags = 0x0002
    _send([ctrl, key, key_up, ctrl_up])


def _type_text(text):
    batch = []
    for ch in text:
        down = _INPUT()
        down.type = 1
        down.u.ki.wScan = ord(ch)
        down.u.ki.dwFlags = 0x0004
        up = _INPUT()
        up.type = 1
        up.u.ki.wScan = ord(ch)
        up.u.ki.dwFlags = 0x0004 | 0x0002
        batch.extend([down, up])
    if batch:
        _send(batch)


def _clear_and_type(text):
    _tap_ctrl(0x41)
    time.sleep(0.05)
    for _ in range(48):
        _tap(0x08)
    time.sleep(0.05)
    _type_text(text)


def load_points(path):
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    field = cfg.get("search_field")
    button = cfg.get("search_button")
    if not field or not button:
        return None
    return tuple(field), tuple(button)


def search_item(path, name):
    """Вбивает название и жмёт «Поиск». Пустая строка — успех."""
    if sys.platform != "win32":
        return "Поиск в игре только на Windows"
    points = load_points(path)
    if not points:
        return "Нет координат: рядом с программой положи screen_slots.json с полем поиска и кнопкой"
    field, button = points
    _click(*field)
    time.sleep(0.12)
    _click(*field)
    time.sleep(0.08)
    _clear_and_type(name)
    time.sleep(0.2)
    _click(*button)
    return ""
