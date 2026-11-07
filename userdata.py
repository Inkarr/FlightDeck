"""
Where your own Flightdeck files live.

Everything personal is kept in the  mydata  folder next to the code:
  config.local.json   this PC's settings (scPath, pin, port...) - overrides config.json
  my_buttons.json     your own buttons and panels
  my_layout.json      your tab layout
  my_favourites.json  Favourites tab
  my_emotes.json      the emotes you picked
  my_market.json      trade ledger, hangar, starred items
  my_uex.json         your UEX keys (secret - never shared)
  market_cache/       downloaded prices and item data
  sc_defaults.json    default keybinds read from Data.p4k

mydata/ is in .gitignore, so updating the code (git pull, a new zip, the installer)
never touches it. Older copies kept these files next to server.py; they're moved
into mydata/ automatically on the first start.

Command line (used by the installer):
  python userdata.py get scPath
  python userdata.py set scPath "D:\\...\\StarCitizen\\LIVE"
"""
import json
import os
import shutil
import sys

HOME = os.environ.get("FLIGHTDECK_HOME") or os.path.dirname(os.path.abspath(__file__))  # the exe sets FLIGHTDECK_HOME
USER = os.path.join(HOME, "mydata")
LOCAL_CONFIG = os.path.join(USER, "config.local.json")

# old location (next to the code) -> name inside mydata/
_OLD = [
    ("my_buttons.json", None), ("my_layout.json", None), ("my_favourites.json", None),
    ("my_emotes.json", None), ("my_market.json", None), ("my_market.json.bak", None),
    ("my_uex.json", None), ("market_cache", None), (".firewall-asked", None),
    (os.path.join("sc_data", "sc_defaults.json"), "sc_defaults.json"),
]
_PERSONAL_KEYS = ("scPath", "pin")   # moved out of an old config.json into config.local.json


def path(*parts):
    """Path of a file inside mydata/."""
    return os.path.join(USER, *parts)


def migrate():
    os.makedirs(USER, exist_ok=True)
    moved = []
    for old, new in _OLD:
        src, dst = os.path.join(HOME, old), path(new or os.path.basename(old))
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                moved.append(os.path.basename(dst))
            except OSError as e:
                print(f"  ! couldn't move {old} into mydata ({e})")
    # personal values that used to live in config.json
    cfg_path = os.path.join(HOME, "config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        local = load_local()
        take = {k: cfg[k] for k in _PERSONAL_KEYS if cfg.get(k) and k not in local}
        if take:
            save_local(take)
            for k in take:
                cfg[k] = ""
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            moved.append("config.local.json (" + ", ".join(take) + ")")
    except (OSError, ValueError):
        pass
    if moved:
        print("  Moved your settings into mydata\\: " + ", ".join(moved))


def load_local():
    try:
        with open(LOCAL_CONFIG, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"  ! mydata\\config.local.json couldn't be read ({e})")
        return {}


def save_local(updates):
    os.makedirs(USER, exist_ok=True)
    d = load_local()
    d.update(updates)
    tmp = LOCAL_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LOCAL_CONFIG)
    return d


def merged_config():
    """config.json with this PC's overrides from mydata/config.local.json on top."""
    with open(os.path.join(HOME, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in load_local().items():
        if k != "pages":
            cfg[k] = v
    return cfg


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "get":
        try:
            print(merged_config().get(a[1], ""))
        except (OSError, ValueError):
            print("")
    elif len(a) == 3 and a[0] == "set":
        val = int(a[2]) if a[1] == "port" else a[2]
        save_local({a[1]: val})
    elif a == ["migrate"]:
        migrate()
    else:
        print(__doc__)
