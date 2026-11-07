"""
Build Flightdeck-Setup.zip - everything a new PC needs.

Run "Build Setup.bat" (or: python tools\\build_setup.py). The zip lands in the dist
folder. On the new PC: unzip anywhere, double-click "Install Flightdeck.bat".
"""
import datetime
import fnmatch
import os
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", ".github", "mydata", "dist", ".git", ".buildenv", "build", "market_cache"}
SKIP_FILES = ["*.pyc", "index.backup-*.html", "*.before-upgrade", "Flightdeck-Setup*.zip", "my_*.json*",
              "Flightdeck.cmd"]  # the installer writes its own launcher


def main():
    dist = os.path.join(HERE, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "Flightdeck-Setup.zip")
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("backup-")]
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in SKIP_FILES):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, HERE)
                z.write(full, os.path.join("Flightdeck", rel))
                n += 1
    size = os.path.getsize(out) / 1024 / 1024
    print(f"  {out}")
    print(f"  {n} files, {size:.1f} MB - built {datetime.datetime.now():%d %b %Y %H:%M}")
    print("  On the new PC: unzip it, then double-click 'Install Flightdeck.bat'.")


if __name__ == "__main__":
    main()
