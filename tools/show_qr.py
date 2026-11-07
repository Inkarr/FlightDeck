"""Print the address the iPad should open, plus a QR code for the iPad camera."""
import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    port = 8765
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            port = int(json.load(f).get("port", port))
    except Exception:
        pass
    url = f"http://{lan_ip()}:{port}"
    print()
    print(f"  iPad address:  {url}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        print("  Or point the iPad camera at this code:\n")
        qr.print_ascii(invert=True)
    except ImportError:
        pass
    except Exception:
        pass  # console can't show the block characters; the address above is enough
    print()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
