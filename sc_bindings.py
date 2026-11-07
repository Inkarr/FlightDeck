"""
Star Citizen keybinding reader for Flightdeck.

* Default binds come from Data\\Libs\\Config\\defaultProfile.xml inside Data.p4k.
  They are extracted once into mydata/sc_defaults.json and re-extracted
  automatically when Data.p4k changes (i.e. after a patch).
* Your own changes come from user\\client\\0\\Profiles\\default\\actionmaps.xml,
  which Star Citizen rewrites when you change a bind (or exit the game).

Nothing in the game folder is ever written to.
"""
import json
import os
import struct
import xml.etree.ElementTree as ET

HERE = os.environ.get("FLIGHTDECK_HOME") or os.path.dirname(os.path.abspath(__file__))  # the exe sets FLIGHTDECK_HOME
DATA_DIR = os.path.join(HERE, "sc_data")
DEFAULTS_PATH = os.path.join(HERE, "mydata", "sc_defaults.json")   # your cache, kept out of git

DEFAULT_PROFILE = "Data\\Libs\\Config\\defaultProfile.xml"
LOCALISATION = "Data\\Localization\\english\\global.ini"


# --------------------------------------------------------------------------
# Data.p4k (zip64 + zstd) reader - just enough to pull single files out
# --------------------------------------------------------------------------
def p4k_extract(p4k_path, wanted):
    """Return {name: bytes} for the given archive paths (case-insensitive)."""
    import zstandard  # pip install zstandard
    wanted_l = {w.lower(): w for w in wanted}
    found = {}
    size = os.path.getsize(p4k_path)
    with open(p4k_path, "rb") as f:
        f.seek(max(0, size - 65536 - 22))
        tail = f.read()
        i = tail.rfind(b"PK\x06\x07")
        if i < 0:
            raise ValueError("Data.p4k: zip64 locator not found")
        z64off = struct.unpack_from("<Q", tail, i + 8)[0]
        f.seek(z64off)
        z = f.read(56)
        if z[:4] != b"PK\x06\x06":
            raise ValueError("Data.p4k: bad zip64 directory record")
        _n, cdsize, cdoff = struct.unpack_from("<QQQ", z, 32)

        entries = {}
        f.seek(cdoff)
        buf, read = b"", 0
        while read < cdsize and len(entries) < len(wanted_l):
            chunk = f.read(min(64 << 20, cdsize - read))
            read += len(chunk)
            buf += chunk
            p = 0
            while len(buf) - p >= 46:
                if buf[p:p + 4] != b"PK\x01\x02":
                    raise ValueError("Data.p4k: corrupt central directory")
                csize, usize = struct.unpack_from("<II", buf, p + 20)
                nlen, xlen, clen = struct.unpack_from("<HHH", buf, p + 28)
                lho, = struct.unpack_from("<I", buf, p + 42)
                tot = 46 + nlen + xlen + clen
                if len(buf) - p < tot:
                    break
                name = buf[p + 46:p + 46 + nlen].decode("utf-8", "replace")
                if name.lower() in wanted_l:
                    extra = buf[p + 46 + nlen:p + 46 + nlen + xlen]
                    method, = struct.unpack_from("<H", buf, p + 10)
                    # zip64 extra field holds the real sizes / offset
                    q = 0
                    while q + 4 <= len(extra):
                        hid, hsz = struct.unpack_from("<HH", extra, q)
                        if hid == 1:
                            vals = list(struct.unpack_from("<%dQ" % (hsz // 8), extra, q + 4))
                            if usize == 0xFFFFFFFF: usize = vals.pop(0)
                            if csize == 0xFFFFFFFF: csize = vals.pop(0)
                            if lho == 0xFFFFFFFF: lho = vals.pop(0)
                        q += 4 + hsz
                    entries[name] = (method, csize, usize, lho)
                p += tot
            buf = buf[p:]

        for name, (method, csize, usize, lho) in entries.items():
            f.seek(lho)
            h = f.read(30)
            nlen, xlen = struct.unpack_from("<HH", h, 26)
            f.seek(lho + 30 + nlen + xlen)
            data = f.read(csize)
            if method == 100:
                data = zstandard.ZstdDecompressor().decompress(data, max_output_size=usize)
            elif method == 8:
                import zlib
                data = zlib.decompress(data, -15)
            found[wanted_l[name.lower()]] = data
    return found


def cryxml_to_tree(data):
    """CryEngine binary XML ('CryXmlB') -> ElementTree root. Plain XML passes through."""
    if not data.startswith(b"CryXmlB\0"):
        return ET.fromstring(data)
    (_len, nOff, nCnt, aOff, aCnt, cOff, cCnt, sOff, _sSize) = struct.unpack_from("<9I", data, 8)

    def s(o):
        return data[sOff + o:data.index(b"\0", sOff + o)].decode("utf-8", "replace")

    nodes = [struct.unpack_from("<IIHHiiii", data, nOff + 28 * i) for i in range(nCnt)]
    attrs = [struct.unpack_from("<II", data, aOff + 8 * i) for i in range(aCnt)]
    kids = [struct.unpack_from("<I", data, cOff + 4 * i)[0] for i in range(cCnt)]
    els = []
    for (nm, content, ac, _cc, _parent, fa, _fc, _r) in nodes:
        e = ET.Element(s(nm))
        for k, v in attrs[fa:fa + ac]:
            e.set(s(k), s(v))
        t = s(content)
        if t.strip():
            e.text = t
        els.append(e)
    for i, (_nm, _c, _ac, cc, _p, _fa, fc, _r) in enumerate(nodes):
        for c in kids[fc:fc + cc]:
            els[i].append(els[c])
    return els[0]


def build_defaults(sc_path):
    """Extract default binds from Data.p4k and save sc_defaults.json."""
    p4k = os.path.join(sc_path, "Data.p4k")
    files = p4k_extract(p4k, [DEFAULT_PROFILE, LOCALISATION])
    root = cryxml_to_tree(files[DEFAULT_PROFILE])

    loc = {}
    for line in files.get(LOCALISATION, b"").decode("utf-8-sig", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            loc[k.split(",")[0].lower()] = v

    def label(s):
        return loc.get((s or "").lstrip("@").lower(), "").replace("\\n", " ")

    modes = {}
    am_el = root.find("ActivationModes")
    for m in (am_el if am_el is not None else []):
        modes[m.get("name")] = {
            "press": float(m.get("pressTriggerThreshold", "-1")),
            "multiTap": int(m.get("multiTap", "1")),
        }

    actions = {}
    for am in root.iter("actionmap"):
        for a in am.findall("action"):
            def binds(dev):
                out = []
                v = a.get(dev)
                if v and v.strip():
                    out.append(v.strip())
                sub = a.find(dev)
                if sub is not None:
                    for i in sub.iter("inputdata"):
                        if i.get("input", "").strip():
                            out.append(i.get("input").strip())
                return out
            name = a.get("name")
            mode = a.get("activationMode") or ""
            if not mode and a.get("onHold") == "1":
                mode = "hold"
            entry = actions.setdefault(name, {"map": am.get("name"), "kb": [], "mouse": [],
                                              "mode": mode, "label": label(a.get("UILabel"))})
            entry["kb"] += [b for b in binds("keyboard") if b not in entry["kb"]]
            entry["mouse"] += [b for b in binds("mouse") if b not in entry["mouse"]]

    st = os.stat(p4k)
    out = {"p4k": {"mtime": int(st.st_mtime), "size": st.st_size},
           "modes": modes, "actions": actions}
    os.makedirs(os.path.dirname(DEFAULTS_PATH), exist_ok=True)
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=0, ensure_ascii=False)
    return out


# --------------------------------------------------------------------------
# Key-name conversion: Star Citizen -> Flightdeck
# --------------------------------------------------------------------------
_TOKEN = {
    "escape": "esc", "]": "rbracket", "[": "lbracket", "lbracket": "lbracket", "rbracket": "rbracket",
    "np_add": "np_plus", "np_subtract": "np_minus", "np_multiply": "np_multiply",
    "np_divide": "np_divide", "np_period": "np_period", "np_enter": "np_enter",
    "mwheel_up": "wheel_up", "mwheel_down": "wheel_down",
    "mouse1": "mouse_left", "mouse2": "mouse_right", "mouse3": "mouse_middle",
    "mouse4": "mouse_x1", "mouse5": "mouse_x2",
    "'": "apostrophe", ";": "semicolon", ",": "comma", ".": "period", "/": "slash",
    "\\": "backslash", "-": "minus", "=": "equals", "`": "grave",
}
_MODS = ["lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt"]


def sc_to_keys(sc, valid):
    """'f6+lalt' -> 'lalt+f6'. Returns None if any part can't be sent (axes, HMD...)."""
    if not sc or not sc.strip():
        return None
    parts = []
    for t in sc.strip().lower().split("+"):
        if t.startswith("np_") and t[3:].isdigit():
            t = "np" + t[3:]
        t = _TOKEN.get(t, t)
        if t not in valid:
            return None
        parts.append(t)
    parts.sort(key=lambda p: _MODS.index(p) if p in _MODS else 99)
    return "+".join(parts)


# --------------------------------------------------------------------------
# Live state
# --------------------------------------------------------------------------
class SCBindings:
    def __init__(self, sc_path, valid_keys, log=print):
        self.sc_path = sc_path
        self.valid = valid_keys
        self.log = log
        self.defaults = {"actions": {}, "modes": {}}
        self.overrides = {}
        self.am_path = os.path.join(sc_path, "user", "client", "0", "Profiles", "default", "actionmaps.xml")
        self.am_mtime = None
        self.status = "not loaded"

    # ---- defaults -------------------------------------------------------
    def load_defaults(self):
        p4k = os.path.join(self.sc_path, "Data.p4k")
        cached = None
        if os.path.isfile(DEFAULTS_PATH):
            with open(DEFAULTS_PATH, encoding="utf-8") as fh:
                cached = json.load(fh)
        stale = False
        if os.path.isfile(p4k):
            st = os.stat(p4k)
            stale = (cached is None or cached["p4k"]["mtime"] != int(st.st_mtime)
                     or cached["p4k"]["size"] != st.st_size)
        if stale:
            try:
                self.log("  Star Citizen has been updated - reading new default keybinds from Data.p4k...")
                cached = build_defaults(self.sc_path)
                self.log(f"  done: {len(cached['actions'])} actions")
            except ImportError:
                self.log("  ! can't read Data.p4k: run  pip install zstandard  (using saved defaults)")
            except Exception as e:  # never stop the panel over this
                self.log(f"  ! couldn't read Data.p4k ({e}); using saved defaults")
        if cached:
            self.defaults = cached
        elif not os.path.isfile(p4k):
            self.log(f"  ! Data.p4k not found in {self.sc_path} - check scPath in config.json")

    # ---- user rebinds ---------------------------------------------------
    def check_actionmaps(self):
        """Re-read actionmaps.xml if it changed. Returns True when something changed."""
        try:
            m = os.path.getmtime(self.am_path)
        except OSError:
            if self.am_mtime is not None:
                self.overrides, self.am_mtime = {}, None
                return True
            return False
        if m == self.am_mtime:
            return False
        try:
            root = ET.parse(self.am_path).getroot()
        except ET.ParseError:
            return False  # half-written; try again next time
        ov = {}
        profiles = root.findall("ActionProfiles") or [root]
        prof = next((p for p in profiles if p.get("profileName") == "default"), profiles[0])
        for am in prof.iter("actionmap"):
            for a in am.findall("action"):
                entry = {}
                for rb in a.findall("rebind"):
                    inp = rb.get("input", "")
                    dev, _, key = inp.partition("_")
                    if dev.startswith("kb"):
                        entry.setdefault("kb", key.strip())
                    elif dev.startswith("mo"):
                        entry.setdefault("mouse", key.strip())
                    if rb.get("activationMode"):
                        entry["mode"] = rb.get("activationMode")
                if entry:
                    ov[a.get("name")] = entry
        changed = ov != self.overrides
        self.overrides, self.am_mtime = ov, m
        if changed:
            self.log(f"  actionmaps.xml: {len(ov)} custom bind(s) picked up")
        return changed

    # ---- resolution -----------------------------------------------------
    def resolve(self, action):
        """-> dict(keys, source, mode, label) for a Star Citizen action name."""
        d = self.defaults["actions"].get(action)
        o = self.overrides.get(action, {})
        if d is None and not o:
            return {"keys": None, "source": "missing", "mode": "", "label": ""}
        d = d or {"kb": [], "mouse": [], "mode": "", "label": ""}
        mode = o.get("mode") or d.get("mode", "")
        for dev in ("kb", "mouse"):
            if dev in o:
                k = sc_to_keys(o[dev], self.valid)
                if k:
                    return {"keys": k, "source": "custom", "mode": mode, "label": d["label"]}
        for dev in ("kb", "mouse"):
            if dev in o:  # explicitly cleared in-game -> skip the default for that device
                continue
            for b in d.get(dev, []):
                k = sc_to_keys(b, self.valid)
                if k:
                    return {"keys": k, "source": "default", "mode": mode, "label": d["label"]}
        return {"keys": None, "source": "unbound", "mode": mode, "label": d["label"]}

    def timing(self, mode):
        """How a tap should be sent for an activation mode: (hold_ms, taps)."""
        m = self.defaults.get("modes", {}).get(mode, {})
        thr = m.get("press", -1)
        taps = m.get("multiTap", 1)
        if thr and thr > 0:
            return int(thr * 1000) + 200, taps
        return 60, taps


HOLD_MODES = {"hold", "hold_no_retrigger", "all", "delayed_hold", "delayed_hold_long",
              "delayed_hold_no_retrigger"}


if __name__ == "__main__":
    # Manual refresh:  python sc_bindings.py "C:\Program Files\Roberts Space Industries\StarCitizen\LIVE"
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    res = build_defaults(path)
    print(len(res["actions"]), "actions written to", DEFAULTS_PATH)
