"""
Flightdeck.exe entry point (also works as:  python flightdeck.py).

On start it:
  1. picks a writable home folder - next to Flightdeck.exe, or %LOCALAPPDATA%\\Flightdeck
     if that folder is read-only (e.g. Program Files)
  2. unpacks the web panel and game data there, and your starting config.json
     the first time only (your own copies are never overwritten)
  3. finds Star Citizen if config.json doesn't point at it yet
  4. offers once to open the Windows Firewall for the iPad (one admin prompt)
  5. shows the iPad address + QR code, then runs the normal Flightdeck server
"""
import json
import os
import re
import shutil
import string
import subprocess
import sys
import traceback

FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
EXE_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
FIREWALL_RULE = "Flightdeck"


def say(msg=""):
    print("  " + msg if msg else "")


def writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".flightdeck-write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def home_folder():
    if not FROZEN:
        return EXE_DIR  # running from source: use the source folder as before
    if writable(EXE_DIR):
        return EXE_DIR
    alt = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Flightdeck")
    os.makedirs(alt, exist_ok=True)
    return alt


def unpack(home):
    """Copy bundled files out of the exe. Web panel + game data are refreshed every
    start (so they match this exe); settings files are only created if missing."""
    if not FROZEN:
        return
    always = ["static", os.path.join("sc_data", "emotes.json"), os.path.join("sc_data", "activation_modes.json"),
              os.path.join("sc_data", "default_emotes.json")]
    once = ["config.json"]
    for rel in always + once:
        src, dst = os.path.join(BUNDLE, rel), os.path.join(home, rel)
        if not os.path.exists(src) or (rel in once and os.path.exists(dst)):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


# ----------------------------------------------------------------- Star Citizen
def fixed_drives():
    if sys.platform != "win32":
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED - skips empty card readers
                out.append(root)
    return out


def find_star_citizen():
    roots = []
    launcher = os.path.join(os.environ.get("APPDATA", ""), "rsilauncher")
    if os.path.isdir(launcher):  # the RSI launcher remembers the library folder
        for name in os.listdir(launcher):
            if name.lower().endswith(".json"):
                try:
                    with open(os.path.join(launcher, name), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                for m in re.finditer(r'[A-Za-z]:(?:\\\\|\\|/)[^"]*?Roberts Space Industries', text):
                    roots.append(m.group(0).replace("\\\\", "\\").replace("/", "\\"))
    for d in fixed_drives():
        for sub in ("", "Program Files\\", "Program Files (x86)\\", "Games\\", "Program Files\\Games\\"):
            roots.append(d + sub + "Roberts Space Industries")
    found = []
    for r in dict.fromkeys(roots):
        for ch in ("LIVE", "PTU", "EPTU", "TECH-PREVIEW"):
            p = os.path.join(r, "StarCitizen", ch)
            if os.path.isfile(os.path.join(p, "Data.p4k")) and p not in found:
                found.append(p)
    found.sort(key=lambda p: not p.upper().endswith("\\LIVE"))
    return found


def check_star_citizen(home):
    import userdata
    try:
        cfg = userdata.merged_config()
    except (OSError, ValueError) as e:
        say(f"! couldn't read config.json ({e})")
        return
    current = cfg.get("scPath", "")
    if current and os.path.isfile(os.path.join(current, "Data.p4k")):
        return
    found = find_star_citizen()
    path = found[0] if found else None
    if path:
        say(f"Found Star Citizen: {path}")
    else:
        say("Couldn't find Star Citizen automatically.")
        while not path:
            try:
                a = input("  Paste your StarCitizen\\LIVE folder (or press Enter to skip): ").strip().strip('"')
            except EOFError:
                a = ""
            if not a:
                say("Skipped - keybinds won't be read until scPath is set in mydata\\config.local.json.")
                return
            for cand in (a, os.path.join(a, "LIVE"), os.path.join(a, "StarCitizen", "LIVE")):
                if os.path.isfile(os.path.join(cand, "Data.p4k")):
                    path = cand
                    break
            else:
                say("No Data.p4k there - try again.")
    userdata.save_local({"scPath": path})
    say("Saved to mydata\\config.local.json")


# ----------------------------------------------------------------- firewall
def firewall_rule_exists():
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}"],
                           capture_output=True, text=True, creationflags=0x08000000)
        return r.returncode == 0 and FIREWALL_RULE in r.stdout
    except OSError:
        return True  # can't check - don't nag


def check_firewall(home, port):
    if sys.platform != "win32" or firewall_rule_exists():
        return
    marker = os.path.join(home, "mydata", ".firewall-asked")
    if os.path.exists(marker):
        return
    say("The iPad needs Windows Firewall to let it in (one-time, needs admin).")
    try:
        a = input("  Open the firewall for Flightdeck on your home network now? [Y/n] ").strip().lower()
    except EOFError:
        a = "n"
    open(marker, "w").close()
    if a not in ("", "y", "yes"):
        say("Skipped. If the iPad can't connect, delete mydata\\.firewall-asked and restart Flightdeck.")
        return
    import ctypes
    args = (f'advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow protocol=TCP '
            f'localport={port} profile=private,domain')
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0)
    say("Firewall opened." if rc > 32 else "Firewall wasn't changed (the admin prompt was declined).")


# ----------------------------------------------------------------- QR
def show_address(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    url = f"http://{ip}:{port}"
    say()
    say(f"iPad address:  {url}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        say("Or point the iPad camera at this code:")
        print()
        qr.print_ascii(invert=True)
    except Exception:
        pass
    say()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    if sys.platform == "win32":
        os.system("title Flightdeck")
    home = home_folder()
    os.environ["FLIGHTDECK_HOME"] = home
    os.chdir(home)
    unpack(home)
    if BUNDLE not in sys.path:
        sys.path.insert(0, BUNDLE)
    import userdata   # reads FLIGHTDECK_HOME, so only after it's set
    userdata.migrate()
    say(f"Your settings are kept in {userdata.USER}")
    check_star_citizen(home)
    port = 8765
    try:
        port = int(userdata.merged_config().get("port", 8765))
    except Exception:
        pass
    check_firewall(home, port)
    show_address(port)

    if BUNDLE not in sys.path:
        sys.path.insert(0, BUNDLE)
    import server  # reads config.json etc. from FLIGHTDECK_HOME
    try:
        server.main()
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or e.errno in (98, 10048):
            say(f"Port {port} is already in use - is Flightdeck already running in another window?")
        else:
            raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        print()
        traceback.print_exc()
        print()
        say("Flightdeck stopped because of the error above.")
    if FROZEN:
        try:
            input("\n  Press Enter to close...")
        except EOFError:
            pass
