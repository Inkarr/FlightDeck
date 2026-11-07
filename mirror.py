"""
Keyboard mirroring for Flightdeck.

Watches the PC's physical keyboard (Windows low-level keyboard hook, no extra
packages) and, when you press a key that is bound to one of the panel's
toggle/radio buttons, tells the tablet to flip that button's light, as if
you had tapped it on the tablet.

- Keys Flightdeck itself sends (from the tablet) are ignored, so nothing
  double-flips.
- By default only keys pressed while Star Citizen is the focused window count.
- Pressing the chat key (Enter) pauses mirroring until Enter or Esc again,
  so typing in chat doesn't flip lights.
- Tap / long-press timing follows Star Citizen's activation modes, so a quick
  N toggles the gear while holding N (Auto Land) doesn't.
- The game's real state can't be read, so lights can still drift (for example
  if the game ignores a key). Use "Reset lights" on the tablet if they do.
"""
import json
import os
import queue
import sys
import threading
import time

MODS = ("lctrl", "rctrl", "lalt", "ralt", "lshift", "rshift")
HERE = os.environ.get("FLIGHTDECK_HOME") or os.path.dirname(os.path.abspath(__file__))  # the exe sets FLIGHTDECK_HOME
TAP_MODES = {"tap": 0.25, "tap_quicker": 0.15, "smart_toggle": 0.25, "hold_toggle": 0.25}
SKIP_MODES = {"double_tap", "double_tap_nonblocking"}


def _release_thresholds():
    """Tap release windows from the game's activation modes (falls back to defaults)."""
    out = dict(TAP_MODES)
    try:
        with open(os.path.join(HERE, "sc_data", "activation_modes.json"), encoding="utf-8") as f:
            for name, m in json.load(f).items():
                thr = float(m.get("releaseTriggerThreshold") or -1)
                if thr > 0 and m.get("onRelease") == "1" and m.get("onPress") == "0":
                    out[name] = thr
    except Exception:
        pass
    return out


RELEASE_THR = _release_thresholds()


def classify(mode, press_thr):
    """-> (kind, threshold). kind: 'press' (fires on key down), 'tap' (released
    within threshold), 'long' (held at least threshold) or None (not mirrored)."""
    if mode in SKIP_MODES:
        return None, 0
    if press_thr and press_thr > 0:
        return "long", press_thr
    if mode in RELEASE_THR:
        return "tap", RELEASE_THR[mode]
    return "press", 0


def split_combo(parts):
    """['lalt', 'n'] -> ('n', frozenset({'lalt'})). A lone modifier is its own main key."""
    non_mods = [p for p in parts if p not in MODS]
    main = non_mods[-1] if non_mods else parts[-1]
    return main, frozenset(p for p in parts if p != main)


# --------------------------------------------------------------------------
# Events for the tablet (long-polled)
# --------------------------------------------------------------------------
class EventBus:
    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.events = []  # (seq, [button ids])

    def publish(self, ids):
        with self.cond:
            self.seq += 1
            self.events.append((self.seq, ids))
            del self.events[:-200]
            self.cond.notify_all()

    def wait(self, since, timeout=25.0):
        with self.cond:
            if 0 <= since == self.seq:
                self.cond.wait(timeout)
            if since < 0 or since > self.seq:  # first call, or the server restarted
                return self.seq, []
            return self.seq, [{"seq": s, "ids": ids} for s, ids in self.events if s > since]


# --------------------------------------------------------------------------
# Key tracking (platform independent, so it can be tested anywhere)
# --------------------------------------------------------------------------
class KeyTracker:
    """Turns raw key down/up events into button ids to flip.

    get_index() -> {(main, frozenset(mods)): [{"id", "group", "kind", "thr", "label"}]}
    """

    def __init__(self, get_index, publish, log=print):
        self.get_index = get_index
        self.publish = publish
        self.log = log
        self.down = {}  # key -> [t_down, mods held at the time, another key pressed meanwhile]

    def key_down(self, key, t):
        if key in self.down:
            return  # auto-repeat
        for rec in self.down.values():
            rec[2] = True
        mods = frozenset(k for k in self.down if k in MODS)
        self.down[key] = [t, mods, False]
        if key not in MODS:
            self._fire(key, mods, "down", 0.0)

    def key_up(self, key, t):
        rec = self.down.pop(key, None)
        if not rec:
            return
        if key in MODS and rec[2]:
            return  # it was used as a modifier for another key
        self._fire(key, rec[1], "up", t - rec[0], lone_mod=key in MODS)

    def reset(self):
        self.down.clear()

    def _fire(self, main, mods, phase, dur, lone_mod=False):
        cands = self.get_index().get((main, mods), [])
        hits, groups = [], set()
        for c in cands:
            k = c["kind"]
            ok = ((phase == "down" and k == "press") or
                  (phase == "up" and lone_mod and k == "press") or
                  (phase == "up" and k == "tap" and dur <= c["thr"] + 0.05) or
                  (phase == "up" and k == "long" and dur >= c["thr"]))
            if ok and c["group"] not in groups:
                groups.add(c["group"])
                hits.append(c)
        if hits:
            combo = "+".join(sorted(mods) + [main])
            self.log(f"  [keyboard] {combo:<14} -> " + ", ".join(h["label"] for h in hits))
            self.publish([h["id"] for h in hits])


# --------------------------------------------------------------------------
# Windows keyboard hook
# --------------------------------------------------------------------------
class WindowsKeyboardMirror:
    def __init__(self, scancodes, tracker, chat_key="enter", game_exe="StarCitizen.exe",
                 only_in_game=True, log=print):
        self.names = {v: k for k, v in scancodes.items()}  # (code, ext) -> name
        self.tracker = tracker
        self.chat_key = chat_key
        self.game_exe = game_exe.lower()
        self.only_in_game = only_in_game
        self.log = log
        self.q = queue.Queue()
        self.typing_until = 0.0
        self._pid_cache = {}
        self.status = "starting"

    def start(self):
        threading.Thread(target=self._hook_thread, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()

    # -- hook (keep this fast: Windows drops slow hooks) --
    def _hook_thread(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = LRESULT
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)

        q = self.q

        def proc(n_code, w_param, l_param):
            if n_code == 0:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not kb.flags & 0x10:  # LLKHF_INJECTED: keys Flightdeck sent itself
                    q.put((kb.scanCode, bool(kb.flags & 0x01), w_param in (0x0101, 0x0105), time.monotonic()))
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(proc)  # keep a reference or Python frees it
        hook = user32.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)  # WH_KEYBOARD_LL
        if not hook:
            self.status = f"off (keyboard hook failed, error {ctypes.get_last_error()})"
            self.log(f"  ! Keyboard mirroring: {self.status}")
            return
        self.status = "on" + (f" (only while {self.game_exe} is focused)" if self.only_in_game else "")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # -- processing --
    def _game_focused(self):
        if not self.only_in_game:
            return True
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        pid = pid.value
        if pid not in self._pid_cache:
            name = ""
            h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value).lower()
                kernel32.CloseHandle(h)
            if len(self._pid_cache) > 64:
                self._pid_cache.clear()
            self._pid_cache[pid] = name
        return self._pid_cache[pid] == self.game_exe

    def _worker(self):
        was_focused = True
        while True:
            code, ext, up, t = self.q.get()
            name = self.names.get((code, ext))
            if not name:
                continue
            try:
                focused = self._game_focused()
            except Exception:
                focused = True
            if not focused:
                if was_focused:
                    self.tracker.reset()
                was_focused = False
                continue
            was_focused = True
            # Chat: Enter opens it, Enter/Esc closes it. Don't mirror what you type.
            if not up and name in (self.chat_key, "esc"):
                if self.typing_until and (name == "esc" or name == self.chat_key):
                    self.typing_until = 0.0
                elif name == self.chat_key:
                    self.typing_until = time.monotonic() + 60
                self.tracker.reset()
                continue
            if self.typing_until:
                if time.monotonic() < self.typing_until:
                    continue
                self.typing_until = 0.0
            (self.tracker.key_up if up else self.tracker.key_down)(name, t)


def create(scancodes, get_index, bus, cfg, log=print):
    """Start mirroring if enabled and possible. Returns an object with .status."""
    class Off:
        def __init__(self, status): self.status = status
    if not cfg.get("mirrorKeyboard", True):
        return Off("off (mirrorKeyboard is false in config.json)")
    if sys.platform != "win32":
        return Off("off (only works on Windows)")
    tracker = KeyTracker(get_index, bus.publish, log)
    m = WindowsKeyboardMirror(scancodes, tracker, chat_key=cfg.get("chatKey", "enter"),
                              game_exe=cfg.get("gameExe", "StarCitizen.exe"),
                              only_in_game=cfg.get("mirrorOnlyInGame", True), log=log)
    m.start()
    return m
