"""
Flightdeck - tablet control panel server for Star Citizen (or any game).

Run on the gaming PC:   python server.py
Then open the printed URL on your tablet (same Wi-Fi).

Only buttons defined in config.json can be triggered - the tablet can't send
arbitrary keys. Keypresses use hardware scan codes via SendInput, which is what
games reading DirectInput/raw input expect.

No third-party packages needed. Python 3.9+.
"""
import base64
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import market
import mirror
import userdata

HERE = os.environ.get("FLIGHTDECK_HOME") or os.path.dirname(os.path.abspath(__file__))  # the exe sets FLIGHTDECK_HOME
CONFIG_PATH = os.path.join(HERE, "config.json")
userdata.migrate()   # your own files live in mydata/ (see userdata.py)
STATIC_DIR = os.path.join(HERE, "static")
MAX_HOLD_SECONDS = 10  # safety: auto-release a mirrored hold if the tablet goes quiet

# --------------------------------------------------------------------------
# Scan codes (set 1). (code, extended)
# --------------------------------------------------------------------------
SC = {
    "esc": (0x01, False), "1": (0x02, False), "2": (0x03, False), "3": (0x04, False),
    "4": (0x05, False), "5": (0x06, False), "6": (0x07, False), "7": (0x08, False),
    "8": (0x09, False), "9": (0x0A, False), "0": (0x0B, False), "minus": (0x0C, False),
    "equals": (0x0D, False), "backspace": (0x0E, False), "tab": (0x0F, False),
    "q": (0x10, False), "w": (0x11, False), "e": (0x12, False), "r": (0x13, False),
    "t": (0x14, False), "y": (0x15, False), "u": (0x16, False), "i": (0x17, False),
    "o": (0x18, False), "p": (0x19, False), "lbracket": (0x1A, False), "rbracket": (0x1B, False),
    "enter": (0x1C, False), "lctrl": (0x1D, False), "a": (0x1E, False), "s": (0x1F, False),
    "d": (0x20, False), "f": (0x21, False), "g": (0x22, False), "h": (0x23, False),
    "j": (0x24, False), "k": (0x25, False), "l": (0x26, False), "semicolon": (0x27, False),
    "apostrophe": (0x28, False), "grave": (0x29, False), "lshift": (0x2A, False),
    "backslash": (0x2B, False), "z": (0x2C, False), "x": (0x2D, False), "c": (0x2E, False),
    "v": (0x2F, False), "b": (0x30, False), "n": (0x31, False), "m": (0x32, False),
    "comma": (0x33, False), "period": (0x34, False), "slash": (0x35, False),
    "rshift": (0x36, False), "np_multiply": (0x37, False), "lalt": (0x38, False),
    "space": (0x39, False), "capslock": (0x3A, False),
    "f1": (0x3B, False), "f2": (0x3C, False), "f3": (0x3D, False), "f4": (0x3E, False),
    "f5": (0x3F, False), "f6": (0x40, False), "f7": (0x41, False), "f8": (0x42, False),
    "f9": (0x43, False), "f10": (0x44, False), "f11": (0x57, False), "f12": (0x58, False),
    "np7": (0x47, False), "np8": (0x48, False), "np9": (0x49, False), "np_minus": (0x4A, False),
    "np4": (0x4B, False), "np5": (0x4C, False), "np6": (0x4D, False), "np_plus": (0x4E, False),
    "np1": (0x4F, False), "np2": (0x50, False), "np3": (0x51, False), "np0": (0x52, False),
    "np_period": (0x53, False),
    # extended keys
    "rctrl": (0x1D, True), "ralt": (0x38, True), "np_enter": (0x1C, True), "np_divide": (0x35, True),
    "insert": (0x52, True), "delete": (0x53, True), "home": (0x47, True), "end": (0x4F, True),
    "pgup": (0x49, True), "pgdn": (0x51, True), "up": (0x48, True), "down": (0x50, True),
    "left": (0x4B, True), "right": (0x4D, True),
}
MOUSE = {"mouse_left", "mouse_right", "mouse_middle", "mouse_x1", "mouse_x2", "wheel_up", "wheel_down"}
VALID_KEYS = set(SC) | MOUSE


def parse_combo(combo):
    """'lalt+n' -> ['lalt', 'n'] with validation."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    for p in parts:
        if p not in SC and p not in MOUSE:
            raise ValueError(f"Unknown key '{p}' in '{combo}'")
    return parts


# --------------------------------------------------------------------------
# Input backend: real SendInput on Windows, logging dry-run elsewhere
# --------------------------------------------------------------------------
class DryRunInput:
    name = "dry-run (no keys sent - not on Windows)"

    def down(self, key): print(f"    down {key}")
    def up(self, key): print(f"    up   {key}")


class WindowsInput:
    name = "Windows SendInput (scan codes)"

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                        ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.INPUT, self.KEYBDINPUT, self.MOUSEINPUT = INPUT, KEYBDINPUT, MOUSEINPUT
        self.SendInput = ctypes.windll.user32.SendInput
        self.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

    def _send(self, inp):
        n = self.SendInput(1, self.ctypes.byref(inp), self.ctypes.sizeof(inp))
        if n != 1:
            print("    ! SendInput was blocked (is the game running as admin? run this as admin too)")

    def _key(self, key, release):
        code, ext = SC[key]
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if ext:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        if release:
            flags |= 0x0002  # KEYEVENTF_KEYUP
        inp = self.INPUT(type=1)
        inp.ki = self.KEYBDINPUT(0, code, flags, 0, 0)
        self._send(inp)

    def _mouse(self, key, release):
        flags, data = {
            "mouse_left": ((0x0004 if release else 0x0002), 0),
            "mouse_right": ((0x0010 if release else 0x0008), 0),
            "mouse_middle": ((0x0040 if release else 0x0020), 0),
            "mouse_x1": ((0x0100 if release else 0x0080), 1),
            "mouse_x2": ((0x0100 if release else 0x0080), 2),
            "wheel_up": (0x0800, 120),
            "wheel_down": (0x0800, (-120) & 0xFFFFFFFF),
        }[key]
        if key.startswith("wheel") and release:
            return  # wheel is a single event
        inp = self.INPUT(type=0)
        inp.mi = self.MOUSEINPUT(0, 0, data, flags, 0, 0)
        self._send(inp)

    def down(self, key):
        (self._mouse if key in MOUSE else self._key)(key, False)

    def up(self, key):
        (self._mouse if key in MOUSE else self._key)(key, True)


backend = WindowsInput() if sys.platform == "win32" else DryRunInput()
send_lock = threading.Lock()


def press(keys, hold_ms=60, taps=1):
    """Press a combo: modifiers down in order, hold, release in reverse."""
    with send_lock:
        for t in range(taps):
            if t:
                time.sleep(0.08)
            for k in keys:
                backend.down(k)
                time.sleep(0.015)
            time.sleep(max(hold_ms, 30) / 1000)
            for k in reversed(keys):
                backend.up(k)
                time.sleep(0.015)


# Chat macros (emotes): open chat, type the command, send
CHAR_KEYS = {c: (c, False) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
CHAR_KEYS.update({" ": ("space", False), "/": ("slash", False), "-": ("minus", False),
                  "_": ("minus", True), ".": ("period", False), ",": ("comma", False)})


def type_chat(text, chat_key):
    with send_lock:
        for k in parse_combo(chat_key):
            backend.down(k); time.sleep(0.02); backend.up(k)
        time.sleep(0.25)  # let the chat box open
        for ch in text:
            key, shift = CHAR_KEYS.get(ch.lower(), (None, False))
            if key is None:
                continue
            shift = shift or ch.isupper()
            if shift:
                backend.down("lshift")
            backend.down(key); time.sleep(0.012); backend.up(key)
            if shift:
                backend.up("lshift")
            time.sleep(0.012)
        time.sleep(0.05)
        backend.down("enter"); time.sleep(0.03); backend.up("enter")


# Mirrored holds (tablet finger down -> key down, finger up -> key up)
held = {}  # button id -> (keys, deadline)
held_lock = threading.Lock()


def hold_start(bid, keys):
    with held_lock:
        if bid in held:
            held[bid] = (keys, time.time() + MAX_HOLD_SECONDS)
            return
        held[bid] = (keys, time.time() + MAX_HOLD_SECONDS)
    with send_lock:
        for k in keys:
            backend.down(k)
            time.sleep(0.015)


def hold_end(bid):
    with held_lock:
        entry = held.pop(bid, None)
    if entry:
        with send_lock:
            for k in reversed(entry[0]):
                backend.up(k)
                time.sleep(0.015)


def release_all():
    for bid in list(held.keys()):
        hold_end(bid)


def watchdog():
    while True:
        time.sleep(0.5)
        now = time.time()
        for bid, (_, deadline) in list(held.items()):
            if now > deadline:
                print(f"  watchdog released '{bid}' (no release from tablet)")
                hold_end(bid)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Your own buttons, icons and panels (my_buttons.json), made on the tablet
# --------------------------------------------------------------------------
MY_LIB_PATH = userdata.path("my_buttons.json")
LOOKS = {"tile", "toggle", "wide", "hero", "mode", "chan", "round", "cover", "lever", "rocker", "bar"}
TWO_ACTIONS = {"rocker", "bar"}             # a + and a - action
COLOURS = {"blue", "amber", "red", "green", "white"}
LIB_ID = re.compile(r"u_[a-z0-9]{4,16}")
PANEL_ID = re.compile(r"up_[a-z0-9]{4,16}")
ICON_ID = re.compile(r"ic_[a-z0-9]{4,24}")
SC_ACTION = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
MAX_ICON_BYTES = 200_000


def my_library():
    try:
        with open(MY_LIB_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        d = {}
    except Exception as e:
        print(f"  ! my_buttons.json couldn't be read ({e}) - your own buttons are missing until it's fixed")
        d = {}
    return {"buttons": d.get("buttons") or [], "panels": d.get("panels") or [], "icons": d.get("icons") or {},
            "edits": d.get("edits") or {}, "panelEdits": d.get("panelEdits") or {}}


def save_library(lib):
    tmp = MY_LIB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=1)
    os.replace(tmp, MY_LIB_PATH)


def clean_action(a):
    """{'sc': action} follows your Star Citizen keybind; {'keys': 'ralt+l'} is a fixed key combo."""
    if not isinstance(a, dict):
        return None
    if isinstance(a.get("sc"), str) and SC_ACTION.fullmatch(a["sc"]):
        return {"sc": a["sc"]}
    if isinstance(a.get("keys"), str) and a["keys"].strip():
        parse_combo(a["keys"])   # raises ValueError for unknown keys
        return {"keys": "+".join(parse_combo(a["keys"]))}
    return None


def clean_button(b, icons):
    if not isinstance(b, dict):
        raise ValueError("bad button")
    bid = b.get("id") if isinstance(b.get("id"), str) and LIB_ID.fullmatch(b["id"]) else "u_" + os.urandom(4).hex()
    look = b.get("look") if b.get("look") in LOOKS else "tile"
    out = {"id": bid, "label": str(b.get("label") or "").strip()[:40] or "Button", "look": look,
           "color": b.get("color") if b.get("color") in COLOURS else "blue"}
    if isinstance(b.get("sub"), str) and b["sub"].strip():
        out["sub"] = b["sub"].strip()[:60]
    icon = b.get("icon")
    if isinstance(icon, str) and (re.fullmatch(r"[A-Za-z0-9]{1,24}", icon) or (icon.startswith("u:") and icon[2:] in icons)):
        out["icon"] = icon
    act = clean_action(b.get("act"))
    if not act:
        raise ValueError("pick a Star Citizen action or a key for the button")
    out["act"] = act
    if look in TWO_ACTIONS:
        act2 = clean_action(b.get("act2"))
        if not act2:
            raise ValueError("this style needs a second action (the - button)")
        out["act2"] = act2
    out["mode"] = b.get("mode") if b.get("mode") in ("tap", "hold", "repeat") else ("repeat" if look in TWO_ACTIONS else "tap")
    if b.get("toggle") or look in ("toggle", "lever"):
        out["toggle"] = True
    if isinstance(b.get("group"), str) and b["group"].strip():
        out["group"] = b["group"].strip()[:20]
    if isinstance(b.get("needs"), str) and re.fullmatch(r"[A-Za-z0-9_]{0,40}", b["needs"]):
        out["needs"] = b["needs"]   # only works when this button is on / selected ("" = always)
    if look == "bar":
        try:
            out["steps"] = max(2, min(100, int(b.get("steps", 20))))
        except (TypeError, ValueError):
            out["steps"] = 20
    return out


def library_buttons():
    """Your own buttons, in the same shape as config.json buttons."""
    out = []
    for c in my_library()["buttons"]:
        try:
            base = {"custom": True, "look": c["look"], "color": c.get("color", "blue"), "icon": c.get("icon", ""),
                    "sub": c.get("sub", ""), "lib": c["id"]}
            mode = "" if c.get("mode") in (None, "tap") else c["mode"]
            first = {**base, "id": c["id"], "label": c["label"], **c["act"]}
            if mode:
                first["mode"] = mode
            if c.get("toggle") and c["look"] not in TWO_ACTIONS:
                first["toggle"] = True
            if c["look"] == "cover":
                first["guard"] = True
            if c.get("group") and c["look"] not in TWO_ACTIONS:
                first["radio"] = "u:" + c["group"]
                first.pop("toggle", None)
            if "needs" in c:
                first["needs"] = c["needs"]
            if c["look"] in TWO_ACTIONS:   # first = the + action, second = the - action
                first["label"] = c["label"] + " +"
                second = {**base, "id": c["id"] + "_2", "label": c["label"] + " \u2212", **c["act2"], "part": 2}
                if "needs" in c:
                    second["needs"] = c["needs"]
                if mode:
                    second["mode"] = mode
                if c["look"] == "bar":
                    first.update(meter=c["id"], step=1, meterSteps=c.get("steps", 20), meterDefault=c.get("steps", 20) // 2)
                    second.update(meter=c["id"], step=-1)
                out += [first, second]
            else:
                out.append(first)
            for x in out[-2:]:
                if x.get("keys"):
                    parse_combo(x["keys"])
        except Exception as e:
            print(f"  ! skipped one of your buttons ({e})")
    return out


def apply_edit(b, e):
    """Your changes to one of the panel's own buttons (name, what it sends, look)."""
    b["label"] = e.get("label") or b["label"]
    act = e.get("act") or {}
    if act.get("sc"):
        if act["sc"] != b.get("sc"):
            b.pop("keys", None)   # the spare combo belonged to the old action
            b.pop("bind", None)
        b["sc"] = act["sc"]
        b.pop("text", None)
    elif act.get("keys"):
        b["keys"] = act["keys"]
        for k in ("sc", "text", "bind"):
            b.pop(k, None)
    if e.get("mode") in ("hold", "repeat"):
        b["mode"] = e["mode"]
    elif e.get("mode") == "tap":
        b.pop("mode", None)
    if e.get("look") in ("toggle", "lever"):
        b["toggle"] = True
    if e.get("look") == "cover":
        b["guard"] = True
    if "needs" in e:
        b["needs"] = e["needs"]
    b["ovr"] = {k: e[k] for k in ("look", "color", "icon", "sub", "label") if k in e}
    b["edited"] = True


def load_config():
    cfg = userdata.merged_config()   # config.json + mydata/config.local.json
    edits = my_library()["edits"]
    for page in cfg["pages"]:
        for group in page.get("groups", []):
            for b in group["buttons"]:
                if b["id"] in edits:
                    try:
                        apply_edit(b, edits[b["id"]])
                    except Exception as e:
                        print(f"  ! skipped your changes to '{b['id']}' ({e})")
    have = {p.get("type") or p.get("name") for p in cfg["pages"]}
    for kind, name in (("trade", "Trade"), ("hangar", "Hangar"), ("items", "Items")):   # the market tabs (market.py)
        if kind not in have:
            cfg["pages"].append({"name": name, "type": kind})
    mine = library_buttons()
    if mine:   # not a tab of its own: the tablet keeps it out of the tab bar
        cfg["pages"].append({"name": "My Buttons", "library": True, "groups": [{"name": "My buttons", "buttons": mine}]})
    buttons = {}
    for page in cfg["pages"]:
        for group in page.get("groups", []):
            for b in group["buttons"]:
                if b["id"] in buttons:
                    raise ValueError(f"Duplicate button id '{b['id']}'")
                if b.get("keys"):
                    parse_combo(b["keys"])  # validate the fallback combo
                elif "sc" not in b and "text" not in b and not b.get("virtual"):
                    raise ValueError(f"Button '{b['id']}' needs keys, sc or text")
                buttons[b["id"]] = b
    for b in buttons.values():   # "only works when ..." rules you set on the tablet
        n = b.get("needs")
        if n is None:
            continue
        t = buttons.get(n)
        if n == "" or not t:
            b.pop("onlyWhen", None)
        elif t.get("radio"):
            b["onlyWhen"] = {"radio": t["radio"], "is": t.get("state") or t["id"], "label": t["label"]}
        else:
            b["onlyWhen"] = {"toggle": t.get("state") or t["id"], "label": t["label"]}
    return cfg, buttons


def config_mtime():
    m = os.path.getmtime(CONFIG_PATH)
    for p in (MY_LIB_PATH, userdata.LOCAL_CONFIG):
        try:
            m = max(m, os.path.getmtime(p))
        except OSError:
            pass
    return m


CONFIG, BUTTONS = load_config()
CONFIG_MTIME = config_mtime()
REV = 1  # bumps whenever config.json or the game's binds change; the tablet re-renders

# --------------------------------------------------------------------------
# Star Citizen bindings (defaults from Data.p4k + your actionmaps.xml)
# --------------------------------------------------------------------------
SCB = None
if CONFIG.get("scPath"):
    from sc_bindings import SCBindings, HOLD_MODES
    SCB = SCBindings(CONFIG["scPath"], VALID_KEYS)
    SCB.load_defaults()
    SCB.check_actionmaps()
else:
    HOLD_MODES = set()

_eff_cache = {}


def effective(b):
    """Work out what a button actually sends right now."""
    key = (b["id"], REV)
    if key in _eff_cache:
        return _eff_cache[key]
    e = {"keys": b.get("keys"), "src": "manual", "mode": b.get("mode", ""),
         "holdMs": b.get("holdMs", 60), "taps": 1, "scLabel": ""}
    if b.get("virtual"):  # no key of its own, e.g. Stand (the tablet sends Crouch or Prone again)
        e.update({"src": "virtual", "_keys": []})
        _eff_cache[key] = e
        return e
    if b.get("sc") and SCB:
        r = SCB.resolve(b["sc"])
        e["scLabel"] = r["label"]
        if r["keys"]:
            e["keys"], e["src"] = r["keys"], r["source"]
            hold, e["taps"] = SCB.timing(r["mode"])
            e["holdMs"] = b.get("holdMs", hold)
            if not b.get("mode") and r["mode"] in HOLD_MODES:
                e["mode"] = "hold"
        elif b.get("text"):
            e["src"] = "chat"
        elif b.get("keys"):
            e["src"] = "spare"  # not bound in game: use the spare combo and bind it
        else:
            e["src"], e["keys"] = "none", None
    elif b.get("text"):
        e["src"] = "chat"
    if e["src"] == "chat":
        e["keys"], e["mode"] = None, ""
    e["_keys"] = parse_combo(e["keys"]) if e["keys"] else []
    _eff_cache.clear() if len(_eff_cache) > 2000 else None
    _eff_cache[key] = e
    return e


LAST_REFRESH = time.time()

# --------------------------------------------------------------------------
# Emote library (sc_data/emotes.json) and the ones you picked (my_emotes.json)
# --------------------------------------------------------------------------
EMOTES_PATH = os.path.join(HERE, "sc_data", "emotes.json")
MY_EMOTES_PATH = userdata.path("my_emotes.json")
DEFAULT_EMOTES_PATH = os.path.join(HERE, "sc_data", "default_emotes.json")


def emote_catalogue():
    try:
        with open(EMOTES_PATH, encoding="utf-8") as f:
            return json.load(f)["emotes"]
    except Exception as e:
        print(f"  ! couldn't read emotes.json: {e}")
        return []


def my_emotes():
    for path in (MY_EMOTES_PATH, DEFAULT_EMOTES_PATH):   # yours, else the starter set
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("selected", [])
        except Exception:
            pass
    return []


def save_my_emotes(sel):
    valid = {e["cmd"] for e in emote_catalogue()}
    sel = [c for c in dict.fromkeys(sel) if c in valid][:120]
    tmp = MY_EMOTES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"selected": sel}, f, indent=1)
    os.replace(tmp, MY_EMOTES_PATH)
    return sel


# --------------------------------------------------------------------------
# Favourites tab: your own layout of buttons and emotes (my_favourites.json)
# --------------------------------------------------------------------------
MY_FAV_PATH = userdata.path("my_favourites.json")
FAV_GRIDS = {(6, 4), (8, 5), (10, 6), (12, 8), (16, 10), (20, 12), (24, 16)}


def my_favourites():
    try:
        with open(MY_FAV_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    cols, rows = d.get("cols", 8), d.get("rows", 5)
    if (cols, rows) not in FAV_GRIDS:
        cols, rows = 8, 5
    return {"cols": cols, "rows": rows, "items": d.get("items", [])}


def save_my_favourites(d):
    out = clean_grid(d)
    tmp = MY_FAV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, MY_FAV_PATH)
    return out


def clean_grid(d, free=False):
    """Validate one grid layout (Favourites, your own tabs, rearranged built-in tabs).
    free=True: the inside of one of your panels (any size, no cards or panels inside)."""
    try:
        cols, rows = int(d.get("cols", 8)), int(d.get("rows", 5))
    except (TypeError, ValueError):
        cols, rows = 8, 5
    if (cols, rows) == (24, 15):
        rows = 16   # 24x15 became 24x16: everything stays where it is, with one more row
    if free:
        cols, rows = max(1, min(cols, 16)), max(1, min(rows, 10))
    elif (cols, rows) not in FAV_GRIDS:
        cols, rows = 8, 5
    emotes = {e["cmd"] for e in emote_catalogue()}
    items = []
    for it in (d.get("items") or [])[:120]:
        if not isinstance(it, dict):
            continue
        try:
            x, y, w, h = (int(it.get(k, v)) for k, v in (("x", 0), ("y", 0), ("w", 1), ("h", 1)))
        except (TypeError, ValueError):
            continue
        w, h = max(1, min(w, cols)), max(1, min(h, rows))
        x, y = max(0, min(x, cols - w)), max(0, min(y, rows - h))
        if it.get("id") in BUTTONS:
            items.append({"id": it["id"], "x": x, "y": y, "w": w, "h": h})
        elif it.get("emote") in emotes:
            items.append({"emote": it["emote"], "x": x, "y": y, "w": w, "h": h})
        elif isinstance(it.get("meter"), str) and re.fullmatch(r"[a-z0-9_]{1,30}", it["meter"]):
            items.append({"meter": it["meter"], "x": x, "y": y, "w": w, "h": h})   # a [-] bar [+] control
        elif free and isinstance(it.get("piece"), str) and 0 < len(it["piece"]) <= 120:
            items.append({"piece": it["piece"], "x": x, "y": y, "w": w, "h": h})   # a group of controls from a tab (e.g. a +/- rocker)
        elif free:
            continue
        elif isinstance(it.get("upanel"), str) and PANEL_ID.fullmatch(it["upanel"]):
            items.append({"upanel": it["upanel"], "x": x, "y": y, "w": w, "h": h})   # one of your own panels
        elif isinstance(it.get("card"), str):   # a named background card that groups buttons
            card = {"card": it["card"].strip()[:40] or "Card", "x": x, "y": y, "w": w, "h": h}
            if isinstance(it.get("num"), str) and it["num"].strip():
                card["num"] = it["num"].strip()[:3]
            if isinstance(it.get("lib"), str) and PANEL_ID.fullmatch(it["lib"]):
                card["lib"] = it["lib"]   # being edited: saves back to that library panel
            items.append(card)
        elif isinstance(it.get("panel"), str) and 0 < len(it["panel"]) <= 80 and "/" in it["panel"]:
            item = {"panel": it["panel"], "x": x, "y": y, "w": w, "h": h}   # a whole panel from a tab
            if isinstance(it.get("title"), str) and it["title"].strip():
                item["title"] = it["title"].strip()[:40]                     # your own name for it on this tab
            if isinstance(it.get("num"), str) and it["num"].strip():
                item["num"] = it["num"].strip()[:3]                          # your own number for it
            items.append(item)
    return {"cols": cols, "rows": rows, "items": items}


# --------------------------------------------------------------------------
# Tab layout (my_layout.json): your own tabs, rearranged built-in tabs,
# tab order and hidden tabs. Favourites is just one of your tabs ("fav").
# --------------------------------------------------------------------------
MY_LAYOUT_PATH = userdata.path("my_layout.json")


def my_layout():
    try:
        with open(MY_LAYOUT_PATH, encoding="utf-8") as f:
            return clean_layout(json.load(f))
    except FileNotFoundError:
        fav = my_favourites()   # first run: bring the old Favourites tab across
        return clean_layout({"tabs": {"fav": {"name": "Favourites", "icon": "star", **fav}}, "order": [], "hidden": []})
    except Exception as e:
        print(f"  ! my_layout.json couldn't be read ({e}) - using the default tabs")
        return {"v": 1, "tabs": {}, "order": [], "hidden": []}


def clean_layout(d):
    builtin = {p["name"] for p in CONFIG["pages"]}
    tabs = {}
    for k, t in (d.get("tabs") or {}).items():
        if not isinstance(k, str) or not isinstance(t, dict) or len(tabs) >= 40:
            continue
        own = k == "fav" or (k.startswith("c_") and len(k) <= 24)
        if not own and k not in builtin:
            continue
        g = clean_grid(t)
        if own:
            g["name"] = str(t.get("name") or "Tab").strip()[:24] or "Tab"
            g["icon"] = str(t.get("icon") or "star")[:20]
        tabs[k] = g
    keys = lambda v: [str(x)[:40] for x in (v if isinstance(v, list) else [])][:60]
    saved = {}   # "Save default": how you want each tab, for Reset tab to go back to
    for k, t in (d.get("saved") or {}).items() if isinstance(d.get("saved"), dict) else []:
        if isinstance(k, str) and isinstance(t, dict) and len(saved) < 40 and (k == "fav" or (k.startswith("c_") and len(k) <= 24) or k in builtin):
            saved[k] = clean_grid(t)
    return {"v": 1, "tabs": tabs, "order": keys(d.get("order")), "hidden": keys(d.get("hidden")), "saved": saved}


def save_my_layout(d):
    out = clean_layout(d)
    tmp = MY_LAYOUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, MY_LAYOUT_PATH)
    return out


def library_changed():
    """Your buttons changed: rebuild the button list now so they can be pressed straight away."""
    global CONFIG, BUTTONS, CONFIG_MTIME, REV
    CONFIG, BUTTONS = load_config()
    CONFIG_MTIME = config_mtime()
    REV += 1


def library_post(path, body):
    """-> (status, reply) for /api/lib/... requests."""
    lib = my_library()
    if path == "/api/lib/button":
        try:
            b = clean_button(body.get("button"), lib["icons"])
        except ValueError as e:
            return 400, {"error": str(e)}
        lib["buttons"] = [x for x in lib["buttons"] if x.get("id") != b["id"]]
        if len(lib["buttons"]) >= 300:
            return 400, {"error": "you have 300 buttons already - delete some first"}
        lib["buttons"].append(b)
        save_library(lib)
        library_changed()
        print(f"  Saved your button '{b['label']}'")
        return 200, {"button": b, "rev": REV}
    if path == "/api/lib/edit":   # change one of the panel's own buttons
        bid = body.get("id")
        if bid not in BUTTONS or BUTTONS[bid].get("custom"):
            return 404, {"error": "unknown button"}
        try:
            b = clean_button({**(body.get("button") or {}), "id": None}, lib["icons"])
        except ValueError as e:
            return 400, {"error": str(e)}
        if b["look"] in TWO_ACTIONS:
            return 400, {"error": "pick a one-button style"}
        btn = body.get("button") or {}
        e = {k: b[k] for k in ("label", "color", "act", "mode", "needs") if k in b}
        for k in ("icon", "sub"):
            if k in b:
                e[k] = b[k]
        if btn.get("look"):   # only when you changed the style
            e["look"] = b["look"]
        lib["edits"][bid] = e
        save_library(lib)
        library_changed()
        print(f"  Changed '{e['label']}'")
        return 200, {"ok": True, "rev": REV}
    if path == "/api/lib/edit-reset":
        lib["edits"].pop(str(body.get("id")), None)
        save_library(lib)
        library_changed()
        return 200, {"ok": True, "rev": REV}
    if path == "/api/lib/panel-edit":   # change one of the panel's own panels
        key, p = body.get("key"), body.get("panel")
        if not isinstance(key, str) or not (0 < len(key) <= 80 and "/" in key) or not isinstance(p, dict):
            return 400, {"error": "bad panel"}
        out = {"title": str(p.get("title") or "").strip()[:40] or key.split("/", 1)[1], **clean_grid(p, free=True)}
        if isinstance(p.get("num"), str) and p["num"].strip():
            out["num"] = p["num"].strip()[:3]
        if not out["items"]:
            return 400, {"error": "a panel needs at least one button"}
        lib["panelEdits"][key] = out
        save_library(lib)
        print(f"  Changed panel '{out['title']}'")
        return 200, {"panel": out}
    if path == "/api/lib/panel-edit-reset":
        lib["panelEdits"].pop(str(body.get("key")), None)
        save_library(lib)
        return 200, {"ok": True}
    if path == "/api/lib/button-delete":
        lib["buttons"] = [x for x in lib["buttons"] if x.get("id") != body.get("id")]
        save_library(lib)
        library_changed()
        return 200, {"ok": True, "rev": REV}
    if path == "/api/lib/icon":
        data = str(body.get("data", ""))
        m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", data)
        if not m:
            return 400, {"error": "icons must be PNG, JPEG or WebP pictures"}
        try:
            raw = base64.b64decode(m.group(2), validate=True)
        except Exception:
            return 400, {"error": "that picture couldn't be read"}
        if len(raw) > MAX_ICON_BYTES:
            return 400, {"error": "that picture is too big (200 KB max)"}
        sig = {"png": b"\x89PNG", "jpeg": b"\xff\xd8", "webp": b"RIFF"}[m.group(1)]
        if not raw.startswith(sig):
            return 400, {"error": "that isn't a real picture file"}
        if len(lib["icons"]) >= 200:
            return 400, {"error": "you have 200 icons already - delete some first"}
        iid = "ic_" + hashlib.sha1(raw).hexdigest()[:12]
        lib["icons"][iid] = {"data": data, "name": str(body.get("name") or "")[:40], "tint": bool(body.get("tint", True))}
        save_library(lib)
        return 200, {"id": iid, "icon": lib["icons"][iid]}
    if path == "/api/lib/icon-delete":
        lib["icons"].pop(str(body.get("id")), None)
        save_library(lib)
        return 200, {"ok": True}
    if path == "/api/lib/panel":
        p = body.get("panel")
        if not isinstance(p, dict):
            return 400, {"error": "bad panel"}
        pid = p.get("id") if isinstance(p.get("id"), str) and PANEL_ID.fullmatch(p["id"]) else "up_" + os.urandom(4).hex()
        out = {"id": pid, "title": str(p.get("title") or "").strip()[:40] or "My panel", **clean_grid(p, free=True)}
        if isinstance(p.get("num"), str) and p["num"].strip():
            out["num"] = p["num"].strip()[:3]
        if not out["items"]:
            return 400, {"error": "put some buttons in the card first"}
        lib["panels"] = [x for x in lib["panels"] if x.get("id") != pid]
        if len(lib["panels"]) >= 100:
            return 400, {"error": "you have 100 panels already - delete some first"}
        lib["panels"].append(out)
        save_library(lib)
        print(f"  Saved your panel '{out['title']}'")
        return 200, {"panel": out}
    if path == "/api/lib/panel-delete":
        lib["panels"] = [x for x in lib["panels"] if x.get("id") != body.get("id")]
        save_library(lib)
        return 200, {"ok": True}
    return 404, {"error": "not found"}


def sc_action_list():
    """Every Star Citizen action, for picking one when you make a button."""
    acts = []
    if SCB:
        for name, d in SCB.defaults.get("actions", {}).items():
            r = SCB.resolve(name)
            acts.append({"a": name, "l": d.get("label") or name, "m": d.get("map", ""), "k": r["keys"] or ""})
    acts.sort(key=lambda x: (x["m"], x["l"].lower()))
    return {"actions": acts, "keys": sorted(VALID_KEYS)}

# --------------------------------------------------------------------------
# Keyboard mirroring (PC keyboard -> tablet lights). See mirror.py
# --------------------------------------------------------------------------
EVENTS = mirror.EventBus()
_mirror_idx = [None, {}]


def mirror_index():
    """(main key, modifiers) -> toggle/radio buttons it flips. Rebuilt when binds change."""
    if _mirror_idx[0] == REV:
        return _mirror_idx[1]
    idx = {}
    for bid, b in BUTTONS.items():
        if not (b.get("toggle") or b.get("radio") or b.get("radioCycle")):
            continue
        # NAV and SCM share one key (hold B): the tablet treats a mirrored press as "switch mode"
        e = effective(b)
        if not e["_keys"] or any(k in MOUSE for k in e["_keys"]):
            continue
        sc_mode = SCB.resolve(b["sc"])["mode"] if (b.get("sc") and SCB) else "press"
        press_thr = (SCB.defaults.get("modes", {}).get(sc_mode, {}).get("press", -1) if SCB else -1)
        kind, thr = mirror.classify(sc_mode, press_thr)
        if not kind:
            continue
        group = ("radio:" + (b.get("radio") or b.get("radioCycle"))) if (b.get("radio") or b.get("radioCycle")) else (b.get("state") or bid)
        label = b["label"].replace("\u00ad", "").replace("\u00a0", " ")
        if b.get("toggleOff"):
            # two-way toggle (Doors, Locks): its own key sets it on, the partner's key sets it off
            idx.setdefault(mirror.split_combo(e["_keys"]), []).append(
                {"id": bid + ":on", "group": group, "kind": kind, "thr": thr, "label": label + " (on)"})
            off = BUTTONS.get(b["toggleOff"])
            oe = effective(off) if off else None
            if oe and oe["_keys"] and not any(k in MOUSE for k in oe["_keys"]):
                idx.setdefault(mirror.split_combo(oe["_keys"]), []).append(
                    {"id": bid + ":off", "group": group, "kind": "press", "thr": 0, "label": label + " (off)"})
            continue
        idx.setdefault(mirror.split_combo(e["_keys"]), []).append(
            {"id": bid, "group": group, "kind": kind, "thr": thr, "label": label})
    _mirror_idx[:] = [REV, idx]
    return idx


MIRROR = None


def refresh_binds():
    """Re-read Star Citizen's keybinds (Refresh button on the Keybinds tab)."""
    global REV, LAST_REFRESH
    if not SCB:
        return False
    SCB.load_defaults()          # cheap unless the game was patched
    SCB.am_mtime = None          # force a fresh read of actionmaps.xml
    SCB.check_actionmaps()
    REV += 1
    LAST_REFRESH = time.time()
    _eff_cache.clear()
    print(f"  keybinds refreshed: {len(SCB.overrides)} custom bind(s)")
    return True


def binds_status():
    """Summary for the Keybinds tab."""
    custom, need, cleared, seen = [], [], [], set()
    for page in CONFIG["pages"]:
        for group in page.get("groups", []):
            for b in group["buttons"]:
                sc = b.get("sc")
                if not sc or sc in seen:
                    continue
                e = effective(b)
                item = {"label": b["label"].replace("\u00ad", "").replace("\u00a0", " "),
                        "tab": page["name"], "scLabel": e["scLabel"], "keys": e["keys"]}
                if e["src"] in ("custom", "spare", "none"):
                    seen.add(sc)
                {"custom": custom, "spare": need, "none": cleared}.get(e["src"], []).append(item)
    return {"linked": bool(SCB and SCB.defaults.get("actions")),
            "scPath": CONFIG.get("scPath", ""),
            "actionmapsFound": bool(SCB and os.path.isfile(SCB.am_path)),
            "defaults": len(SCB.defaults.get("actions", {})) if SCB else 0,
            "lastRefresh": LAST_REFRESH, "rev": REV,
            "mirror": MIRROR.status if MIRROR else "off",
            "custom": custom, "needBind": need, "cleared": cleared}


def maybe_reload():
    """Pick up config.json edits without restarting."""
    global CONFIG, BUTTONS, CONFIG_MTIME, REV
    m = config_mtime()
    if m != CONFIG_MTIME:
        try:
            CONFIG, BUTTONS = load_config()
            CONFIG_MTIME = m
            REV += 1
            print("  config.json reloaded")
        except Exception as e:  # keep old config if the new one is broken
            print(f"  ! config.json has an error, keeping previous version: {e}")
            CONFIG_MTIME = m


def public_config():
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    c = strip(CONFIG)
    c.pop("pin", None)
    c.pop("scPath", None)
    c["pinRequired"] = bool(CONFIG.get("pin"))
    c["rev"] = REV
    c["scLinked"] = bool(SCB and SCB.defaults.get("actions"))
    for page in c["pages"]:
        for group in page.get("groups", []):
            for b in group["buttons"]:
                e = effective(BUTTONS[b["id"]])
                b.update({k: v for k, v in e.items() if not k.startswith("_")})
    return c


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
                 ".css": "text/css", ".json": "application/json", ".png": "image/png",
                 ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json"}


class QuietServer(ThreadingHTTPServer):
    """The tablet drops connections whenever the page reloads, the app is
    backgrounded or the screen sleeps - that's normal, so don't print a traceback."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "Flightdeck/1.0"

    def log_message(self, fmt, *args):
        pass  # quiet; we print our own lines

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            maybe_reload()
            return self._json(200, public_config())
        if path == "/api/emotes":
            return self._json(200, {"catalogue": emote_catalogue(), "selected": my_emotes()})
        if path == "/api/favourites":
            return self._json(200, my_favourites())
        if path == "/api/layout":
            return self._json(200, my_layout())
        if path == "/api/lib":
            return self._json(200, my_library())
        if path == "/api/sc-actions":
            return self._json(200, sc_action_list())
        if path == "/api/binds":
            return self._json(200, binds_status())
        if path == "/api/events":
            if not hasattr(MIRROR, "tracker"):
                return self._json(200, {"seq": 0, "events": [], "disabled": True})
            try:
                since = int(self.path.split("since=")[1].split("&")[0]) if "since=" in self.path else -1
            except ValueError:
                since = -1
            seq, events = EVENTS.wait(since)
            return self._json(200, {"seq": seq, "events": events})
        if path.startswith("/api/market/"):
            return self._market_get(path)
        if path == "/api/ping":
            try:  # changes to the panel's own files make the tablet reload itself
                ui = int(max(os.path.getmtime(os.path.join(STATIC_DIR, f)) for f in os.listdir(STATIC_DIR)))
            except Exception:
                ui = 0
            return self._json(200, {"ok": True, "backend": backend.name, "rev": REV, "ui": ui, "ledger": MARKET.ledger_rev()})
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _market_get(self, path):
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        arg = lambda k, d="": (q.get(k) or [d])[0]
        try:
            if path == "/api/market/trade":
                return self._json(200, MARKET.trade_data())
            if path == "/api/market/items":
                return self._json(200, market_index())
            if path == "/api/market/item":
                return self._json(200, MARKET.item(int(arg("id", "0"))))
            if path == "/api/market/shopping":
                ids = [int(x) for x in arg("ids").split(",") if x.strip().isdigit()][:300]
                return self._json(200, MARKET.shopping(ids))
            if path == "/api/market/ledger":
                return self._json(200, MARKET.ledger())
            if path == "/api/market/ledger.csv":
                body = MARKET.ledger_csv().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="flightdeck-trades.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/market/uex":
                return self._json(200, MARKET.uex_public())
            if path == "/api/market/gamelog":
                imp = MARKET.ledger().get("settings", {}).get("imported", [])
                return self._json(200, MARKET.game_log(CONFIG.get("scPath", ""), imp))
            if path == "/api/market/whereami":
                return self._json(200, MARKET.where_am_i(CONFIG.get("scPath", "")))
            if path == "/api/market/gamelog-lines":
                return self._json(200, MARKET.log_lines(CONFIG.get("scPath", ""), arg("q", "."), min(500, int(arg("n", "150")))))
            if path == "/api/market/ship":
                return self._json(200, MARKET.ship_grids(int(arg("id", "0"))))
            if path == "/api/market/shipinfo":
                return self._json(200, MARKET.ship_info(int(arg("id", "0"))))
            if path == "/api/market/status":
                return self._json(200, MARKET.status())
        except Exception as ex:
            print(f"  ! market: {path}: {ex}")
            return self._json(502, {"error": f"Couldn't get market data: {ex}"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > (16_000_000 if path == "/api/market/uex/report" else 2_000_000):
                return self._json(413, {"error": "too big"})
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})

        pin = CONFIG.get("pin")
        if pin and str(body.get("pin", "")) != str(pin):
            return self._json(403, {"error": "wrong pin"})

        if path == "/api/refresh-binds":
            try:
                ok = refresh_binds()
            except Exception as ex:
                return self._json(500, {"error": f"couldn't read keybinds: {ex}"})
            if not ok:
                return self._json(409, {"error": "scPath isn't set (mydata\\config.local.json)"})
            return self._json(200, binds_status())
        if path == "/api/emotes":
            sel = body.get("selected")
            if not isinstance(sel, list):
                return self._json(400, {"error": "selected must be a list"})
            return self._json(200, {"selected": save_my_emotes([str(x) for x in sel])})
        if path.startswith("/api/lib/"):
            return self._json(*library_post(path, body))
        if path == "/api/layout":
            if not isinstance(body.get("tabs"), dict):
                return self._json(400, {"error": "tabs must be an object"})
            return self._json(200, save_my_layout(body))
        if path == "/api/favourites":
            if not isinstance(body.get("items"), list):
                return self._json(400, {"error": "items must be a list"})
            return self._json(200, save_my_favourites(body))
        if path == "/api/emote":
            cmd = str(body.get("cmd", ""))
            if cmd not in {e["cmd"] for e in emote_catalogue()}:  # only emotes from the library can be typed
                return self._json(404, {"error": "unknown emote"})
            print(f"  {'Emote':<22} chat {cmd}")
            threading.Thread(target=type_chat, args=(cmd, CONFIG.get("chatKey", "enter")), daemon=True).start()
            return self._json(200, {"ok": True})
        if path == "/api/market/ledger":
            try:
                return self._json(200, MARKET.save_ledger(body.get("ledger")))
            except market.LedgerConflict:
                return self._json(409, {"error": "changed on another device", "ledger": MARKET.ledger()})
            except Exception as ex:
                return self._json(400, {"error": str(ex)})
        if path.startswith("/api/market/uex"):
            try:
                if path == "/api/market/uex":
                    return self._json(200, MARKET.uex_save(body))
                if path == "/api/market/uex/send":
                    t = body.get("trade") or {}
                    uid = MARKET.uex_send(t)
                    print(f"  UEX trade sent: {t.get('kind')} {t.get('scu')} SCU {t.get('name', '')} (#{uid})")
                    return self._json(200, {"id": uid})
                if path == "/api/market/uex/edit":
                    t = body.get("trade") or {}
                    MARKET.uex_edit(body.get("id"), t)
                    print(f"  UEX trade updated: #{body.get('id')} {t.get('kind')} {t.get('scu')} SCU {t.get('name', '')}")
                    return self._json(200, {"ok": True})
                if path == "/api/market/uex/report":
                    r = MARKET.uex_report(body)
                    print(f"  UEX price report sent for terminal #{body.get('tid')} ({len(body.get('prices') or [])} commodit{'y' if len(body.get('prices') or []) == 1 else 'ies'})")
                    return self._json(200, r)
                if path == "/api/market/uex/remove":
                    return self._json(200, {"ok": MARKET.uex_remove(body.get("id"))})
            except Exception as ex:
                return self._json(502, {"error": str(ex)})
        if path == "/api/release-all":
            release_all()
            return self._json(200, {"ok": True})

        b = BUTTONS.get(body.get("id"))
        if not b:
            return self._json(404, {"error": "unknown button"})

        e = effective(b)
        label = b["label"].replace("\u00ad", "").replace("\u00a0", " ")
        if path in ("/api/press", "/api/down") and e["src"] == "chat":
            print(f"  {label:<22} chat {b['text']}")
            threading.Thread(target=type_chat, args=(b["text"], CONFIG.get("chatKey", "enter")), daemon=True).start()
            return self._json(200, {"ok": True})
        if path in ("/api/press", "/api/down") and not e["_keys"]:
            return self._json(409, {"error": f"'{label}' has no key - bind it in game"})
        if path == "/api/press":
            extra = f"  ({e['holdMs']}ms)" if e["holdMs"] > 60 else ""
            print(f"  {label:<22} {e['keys']}{extra}")
            threading.Thread(target=press, args=(e["_keys"], e["holdMs"], e["taps"]), daemon=True).start()
            return self._json(200, {"ok": True})
        if path == "/api/down":
            print(f"  {label:<22} {e['keys']}  (hold)")
            hold_start(b["id"], e["_keys"])
            return self._json(200, {"ok": True})
        if path == "/api/up":
            hold_end(b["id"])
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


# --------------------------------------------------------------------------
# Market tabs (Trade, Items) - see market.py
# --------------------------------------------------------------------------
MARKET = market.Market(userdata.USER)
_INDEX = {"data": None, "t": 0, "thread": None, "error": None}


def market_index():
    """The item list takes ~40 downloads the first time, so it's built in the background."""
    fresh = _INDEX["data"] and time.time() - _INDEX["t"] < 3 * 3600
    if not fresh and not (_INDEX["thread"] and _INDEX["thread"].is_alive()):
        def build():
            try:
                _INDEX["data"], _INDEX["t"], _INDEX["error"] = MARKET.items_index(), time.time(), None
            except Exception as ex:
                _INDEX["error"] = str(ex)
                print(f"  ! item list: {ex}")
        _INDEX["thread"] = threading.Thread(target=build, daemon=True)
        _INDEX["thread"].start()
    if _INDEX["data"]:
        return {**_INDEX["data"], "ready": True}
    st = MARKET.index_state
    return {"ready": False, "done": st["done"], "total": st["total"], "error": _INDEX["error"]}


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    global MIRROR
    MIRROR = mirror.create(SC, mirror_index, EVENTS, CONFIG)
    time.sleep(0.3)  # let the keyboard hook report whether it started
    port = int(os.environ.get("SHIPDECK_PORT", CONFIG.get("port", 8765)))
    threading.Thread(target=watchdog, daemon=True).start()
    srv = QuietServer(("0.0.0.0", port), Handler)
    print("=" * 56)
    print("  FLIGHTDECK running")
    print(f"  Input   : {backend.name}")
    print(f"  Buttons : {len(BUTTONS)}")
    if SCB:
        n = sum(1 for b in BUTTONS.values() if b.get("sc"))
        un = [b["label"] for b in BUTTONS.values() if effective(b)["src"] == "spare"]
        print(f"  Keybinds: read from Star Citizen ({n} buttons linked, {len(SCB.overrides)} custom binds)")
        if un:
            print(f"  Not bound in game yet ({len(un)}): tap them while binding - see README")
    print(f"  Keyboard: mirroring {MIRROR.status}")
    print(f"  Open on your tablet:  http://{lan_ip()}:{port}")
    print("  Keep the game window focused on the PC. Ctrl+C to stop.")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        release_all()


if __name__ == "__main__":
    main()
