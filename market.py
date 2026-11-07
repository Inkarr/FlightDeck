"""
Flightdeck market data: trade routes, your trade ledger and the item finder.

The tablet never talks to the internet itself - it asks this PC, which fetches from
  * UEX Corp API 2.0  (https://uexcorp.space/api)  - commodity and item prices, shops, terminals
  * Star Citizen Wiki API (https://api.star-citizen.wiki) - item pictures, descriptions, rarity
and keeps a copy in mydata/market_cache/ so it's quick, and still works for a while if a site is down.

Reading prices needs no API key. Sending your trades to UEX (optional) needs your UEX app token
and your UEX secret key, which are kept on this PC only, in mydata/my_uex.json - never sent to the tablet.
Your trade ledger and starred items live in mydata/my_market.json.
No third-party packages needed.
"""
import calendar
import csv
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UEX = "https://api.uexcorp.uk/2.0/"
WIKI = "https://api.star-citizen.wiki/api/"
UA = "Flightdeck/1.0 (Star Citizen tablet panel; personal use)"

HOUR = 3600
DAY = 24 * HOUR

# UEX item categories worth searching (armour, clothing, weapons, gadgets, ship parts...)
ITEM_CATEGORIES = [1, 2, 3, 4, 5, 7, 24,                     # armour + undersuits
                   8, 9, 10, 11, 12, 13, 14, 15, 68, 72,     # clothing
                   17, 18,                                   # personal weapons + attachments
                   16, 69, 61, 62, 63,                       # consumables, food, drink, misc
                   28, 67, 29, 30, 31, 110, 64,              # gadgets, tractor, mining, salvage, containers
                   19, 21, 22, 23, 81,                       # ship systems
                   32, 33, 34, 35, 70, 79, 80, 90]           # vehicle weapons


# ship services that charge you (wording guessed - the log hasn't shown one yet)
SERVICE = re.compile(r"\b(refuel|repair|rearm|restock)\w*\b.*\b(?:price|cost|amount|total|fee)\[[\d.]+\]", re.I)

UEX_ERRORS = {
    "missing_secret_key": "Add your UEX secret key (from your UEX profile)",
    "invalid_secret_key": "UEX didn't accept the secret key - copy it again from your UEX profile",
    "user_not_found": "UEX doesn't know that secret key - copy it again from your UEX profile",
    "user_not_allowed": "UEX has a restriction on this account for now",
    "user_disabled": "UEX has blocked this account",
    "user_not_verified": "UEX only takes trades from accounts verified with RSI - verify yours on uexcorp.space",
    "terminal_not_found": "UEX doesn't know that terminal",
    "commodity_not_found": "UEX doesn't know that commodity",
    "trade_not_found": "That trade isn't on UEX any more",
    "requests_limit_reached": "Too many requests to UEX - try again in a minute",
    "duplicated_report": "UEX already has this report from the last few minutes",
    "too_many_reports": "Too many reports to UEX lately - try again in half an hour",
    "missing_screenshot": "UEX wants a screenshot with reports from new datarunners - add one and send again",
    "invalid_screenshot": "UEX couldn't read the screenshot - try a PNG or JPG under 10 MB",
    "invalid_token": "UEX didn't accept the app token - copy it again from My Apps on uexcorp.space",
    "missing_token": "Add your UEX app token (from My Apps on uexcorp.space)",
}


class Market:
    def __init__(self, home):   # home = the mydata folder
        self.home = home
        self.cache_dir = os.path.join(home, "market_cache")
        self.ledger_path = os.path.join(home, "my_market.json")
        self.uex_path = os.path.join(home, "my_uex.json")
        self.mem = {}                  # url -> (time, data)
        self.lock = threading.Lock()
        self.ledger_lock = threading.Lock()
        self.errors = {}               # what last failed, for the tablet's status line
        self.index_state = {"building": False, "done": 0, "total": 0}
        os.makedirs(self.cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ fetching
    def _cache_file(self, url):
        name = re.sub(r"[^a-zA-Z0-9]+", "_", url.split("://", 1)[1])[:150]
        return os.path.join(self.cache_dir, name + ".json")

    def get(self, url, ttl, disk=True):
        """JSON from url, cached for ttl seconds. Falls back to an older copy if the site fails."""
        now = time.time()
        hit = self.mem.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
        path = self._cache_file(url)
        if disk and not hit and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
                hit = (saved["t"], saved["data"])
                self.mem[url] = hit
                if now - hit[0] < ttl:
                    return hit[1]
            except Exception:
                hit = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode("utf-8"))
            self.errors.pop(url.split("?")[0], None)
        except Exception as ex:
            self.errors[url.split("?")[0]] = f"{type(ex).__name__}: {ex}"
            if hit:
                return hit[1]      # stale is better than nothing
            raise
        self.mem[url] = (now, data)
        if disk:
            try:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"t": now, "data": data}, f)
                os.replace(tmp, path)
            except Exception:
                pass
        return data

    def age(self, url):
        hit = self.mem.get(url)
        return int(time.time() - hit[0]) if hit else None

    def uex(self, resource, ttl, **params):
        url = UEX + resource + "/"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        d = self.get(url, ttl)
        if isinstance(d, dict):
            if d.get("status") not in (None, "ok"):
                raise RuntimeError(f"UEX {resource}: {d.get('status')}")
            return d.get("data") or []
        return d

    # ------------------------------------------------------------------ places
    def terminals(self):
        return self.uex("terminals", 12 * HOUR)

    @staticmethod
    def place(t):
        """Where a terminal is, e.g. ('Stanton', 'ArcCorp', 'Area 18')."""
        sysname = t.get("star_system_name") or ""
        body = t.get("moon_name") or t.get("planet_name") or t.get("orbit_name") or ""
        spot = t.get("city_name") or t.get("space_station_name") or t.get("outpost_name") or ""
        if not spot:
            spot = body or t.get("displayname") or t.get("name") or ""
        return sysname, body, spot

    def term_map(self):
        out = {}
        for t in self.terminals():
            s, b, p = self.place(t)
            out[t["id"]] = {"id": t["id"], "name": t.get("name") or t.get("displayname") or "", "sys": s, "body": b, "place": p,
                            "type": t.get("type"), "maxBox": t.get("max_container_size") or 0,
                            "station": 1 if t.get("id_space_station") else 0, "live": t.get("is_available_live", 1)}
        return out

    # ------------------------------------------------------------------ trading
    def trade_data(self):
        """Everything the Trade tab needs, compact: prices, terminals, commodities, ships."""
        prices = self.uex("commodities_prices_all", 15 * 60)
        comms = self.uex("commodities", 12 * HOUR)
        tm = self.term_map()
        used = set()
        rows = []
        for p in prices:
            if not (p.get("price_buy") or p.get("price_sell")):
                continue
            used.add(p["id_terminal"])
            # [commodity, terminal, buy price, sell price, scu you can buy, scu they want (0 = not known),
            #  their stock when selling, buy status, sell status, last update]
            rows.append([p["id_commodity"], p["id_terminal"], p.get("price_buy") or 0, p.get("price_sell") or 0,
                         p.get("scu_buy") or 0, p.get("scu_sell") or 0, p.get("scu_sell_stock") or 0,
                         p.get("status_buy") or 0, p.get("status_sell") or 0, p.get("date_modified") or 0])
        terms = [tm[i] for i in used if i in tm]
        com = [{"id": c["id"], "name": c["name"], "code": c.get("code"), "kind": c.get("kind"),
                "illegal": c.get("is_illegal", 0), "volatile": 1 if (c.get("is_volatile_qt") or c.get("is_volatile_time")) else 0}
               for c in comms if c.get("is_buyable") or c.get("is_sellable")]
        try:
            ships = []   # every ship and vehicle, for your hangar; the route finder only offers ones with cargo
            for v in self.uex("vehicles", DAY):
                loan = v.get("ids_vehicles_loaners") or ""
                loan = [int(x) for x in (loan.split(",") if isinstance(loan, str) else loan) if str(x).strip().isdigit()]
                ships.append({"id": v["id"], "name": v.get("name_full") or v["name"], "scu": v.get("scu") or 0,
                              "concept": 1 if v.get("is_concept") else 0, "ground": 1 if v.get("is_ground_vehicle") else 0,
                              "loaners": loan, "photo": v.get("url_photo") or ""})
            ships.sort(key=lambda s: s["name"].lower())
        except Exception:
            ships = []
        return {"rows": rows, "terminals": terms, "commodities": com, "ships": ships,
                "age": self.age(UEX + "commodities_prices_all/"), "now": int(time.time())}

    # ------------------------------------------------------------------ items
    def items_index(self):
        """Every searchable item with how many shops sell it and the cheapest price."""
        st = self.index_state
        items = {}
        st["total"], st["done"], st["building"] = len(ITEM_CATEGORIES), 0, True
        try:
            for cat in ITEM_CATEGORIES:
                try:
                    for it in self.uex("items", DAY, id_category=cat):
                        items[it["id"]] = it
                except Exception:
                    pass
                st["done"] += 1
        finally:
            st["building"] = False
        if not items:
            raise RuntimeError("couldn't download the item list from UEX")
        shops = {}
        for p in self.uex("items_prices_all", 3 * HOUR):
            if (p.get("price_buy") or 0) <= 0:
                continue
            s = shops.setdefault(p["id_item"], [0, 0])
            s[0] += 1
            s[1] = p["price_buy"] if not s[1] else min(s[1], p["price_buy"])
        out = []
        for it in items.values():
            n, low = shops.get(it["id"], (0, 0))
            out.append([it["id"], it["name"], it.get("section") or "", it.get("category") or "",
                        it.get("company_name") or "", it.get("size") or "", n, low])
        out.sort(key=lambda r: r[1].lower())
        return {"items": out, "age": self.age(UEX + "items_prices_all/")}

    def item(self, item_id):
        """One item: stats, picture, and every shop selling it."""
        item_id = int(item_id)
        tm = self.term_map()
        shops = []
        meta = None
        for p in self.uex("items_prices_all", 3 * HOUR):
            if p["id_item"] != item_id:
                continue
            meta = meta or p
            if (p.get("price_buy") or 0) <= 0 and (p.get("price_sell") or 0) <= 0:
                continue
            t = tm.get(p["id_terminal"], {})
            shops.append({"terminal": p.get("terminal_name") or t.get("name", ""), "tid": p["id_terminal"],
                          "sys": t.get("sys", ""), "body": t.get("body", ""), "place": t.get("place", ""),
                          "buy": p.get("price_buy") or 0, "sell": p.get("price_sell") or 0,
                          "updated": p.get("date_modified") or 0})
        shops.sort(key=lambda s: (s["buy"] <= 0, s["buy"] or 1e12))
        out = {"id": item_id, "shops": shops, "stats": [], "name": meta.get("item_name") if meta else None}
        uuid = (meta or {}).get("item_uuid") or ""
        cat = (meta or {}).get("id_category")
        try:
            attrs = self.uex("items_attributes", DAY, id_item=item_id)
            for a in attrs:
                v = a.get("value")
                if v in (None, "", "0") and a.get("attribute_name") not in ("Damage Reduction",):
                    continue
                out["stats"].append([a.get("attribute_name") or "", f"{v}{(' ' + a['unit']) if a.get('unit') else ''}"])
                out["name"] = out["name"] or a.get("item_name")
                uuid = uuid or a.get("item_uuid") or ""
        except Exception:
            pass
        if not out["name"] or not cat:
            # not sold anywhere - find its name in the category lists
            for c in ITEM_CATEGORIES:
                try:
                    hit = next((i for i in self.uex("items", DAY, id_category=c) if i["id"] == item_id), None)
                except Exception:
                    hit = None
                if hit:
                    out["name"] = out["name"] or hit["name"]
                    uuid = uuid or hit.get("uuid") or ""
                    out["company"] = hit.get("company_name")
                    out["category"] = hit.get("category")
                    out["section"] = hit.get("section")
                    break
        out["wiki"] = self.wiki_item(uuid, out["name"] or "")
        return out

    def wiki_item(self, uuid, name):
        """Picture, description, rarity and stats from the Star Citizen Wiki (None if not found)."""
        d = None
        try:
            if uuid:
                d = self.get(WIKI + "items/" + urllib.parse.quote(uuid), 7 * DAY)
                d = d.get("data", d) if isinstance(d, dict) else None
            if not d and name:
                q = WIKI + "items?" + urllib.parse.urlencode({"filter[name]": name, "page[size]": 5})
                lst = self.get(q, 7 * DAY)
                lst = lst.get("data", []) if isinstance(lst, dict) else []
                d = next((x for x in lst if (x.get("name") or "").lower() == name.lower()), None)   # only a sure match
        except Exception:
            return None
        if not isinstance(d, dict):
            return None
        desc = d.get("description")
        if isinstance(desc, dict):
            desc = desc.get("en_EN") or next(iter(desc.values()), "")
        img = None
        for im in d.get("images") or []:
            img = im.get("thumbnail_url") or im.get("original_url")
            if img:
                break
        stats = [[x.get("name"), x.get("value")] for x in (d.get("description_data") or []) if isinstance(x, dict) and x.get("name")]
        pw = d.get("personal_weapon") or {}
        dmg = pw.get("damage") if isinstance(pw, dict) else None
        if isinstance(dmg, dict) and dmg.get("dps_total"):
            stats.append(["Damage per second", round(dmg["dps_total"])])
        if isinstance(dmg, dict) and dmg.get("alpha_total"):
            stats.append(["Damage per shot", round(dmg["alpha_total"], 1)])
        return {"name": d.get("name"), "rarity": d.get("rarity"), "type": d.get("type_label") or d.get("classification_label"),
                "lootable": d.get("is_lootable"), "description": (desc or "").strip()[:1200], "image": img,
                "stats": stats, "url": d.get("web_url"), "version": d.get("version")}

    def ship_grids(self, vehicle_id):
        """A ship's cargo grids from the Star Citizen Wiki, in SCU units (1 SCU = a 1.25 m cube)."""
        vehicle_id = int(vehicle_id)
        v = next((x for x in self.uex("vehicles", DAY) if x["id"] == vehicle_id), None)
        if not v:
            raise RuntimeError("UEX doesn't know that ship")
        name = v.get("name_full") or v.get("name") or ""
        d = None
        if v.get("uuid"):
            try:
                d = self.get(WIKI + "vehicles/" + urllib.parse.quote(v["uuid"]), 7 * DAY)
                d = d.get("data", d) if isinstance(d, dict) else None
            except Exception:
                d = None
        if not d or not d.get("cargo_grids"):
            for q in (v.get("name") or "", name):
                if not q:
                    continue
                try:
                    lst = self.get(WIKI + "vehicles?" + urllib.parse.urlencode({"filter[name]": q, "page[size]": 10}), 7 * DAY)
                except Exception:
                    continue
                lst = lst.get("data", []) if isinstance(lst, dict) else []
                hit = next((x for x in lst if (x.get("name") or "").lower() in (q.lower(), name.lower())), None)
                if hit and hit.get("uuid"):
                    try:
                        full = self.get(WIKI + "vehicles/" + hit["uuid"], 7 * DAY)
                        d = full.get("data", full)
                        break
                    except Exception:
                        pass
        u = lambda m: max(0, int(round((m or 0) / 1.25)))
        grids = []
        for g in (d or {}).get("cargo_grids") or []:
            mx = g.get("max_size") or {}
            grids.append({"w": u(g.get("width")), "h": u(g.get("height")), "l": u(g.get("length")), "scu": g.get("scu") or 0,
                          "maxBox": g.get("max_scu_box") or 0, "max": [u(mx.get("x")), u(mx.get("y")), u(mx.get("z"))],
                          "external": bool(g.get("external"))})
        grids.sort(key=lambda g: -g["scu"])
        return {"id": vehicle_id, "name": name, "scu": v.get("scu") or 0, "found": bool(d),
                "capacity": (d or {}).get("cargo_capacity"), "grids": grids, "uexBoxes": v.get("container_sizes") or ""}

    def shopping(self, ids):
        """Shops for each starred item, grouped by place, best stops first."""
        tm = self.term_map()
        want = set(int(i) for i in ids)
        names = {}
        places = {}
        sold = set()
        for p in self.uex("items_prices_all", 3 * HOUR):
            if p["id_item"] not in want:
                continue
            names[p["id_item"]] = p.get("item_name")
            if (p.get("price_buy") or 0) <= 0:
                continue
            t = tm.get(p["id_terminal"], {})
            key = (t.get("sys", ""), t.get("place", ""))
            g = places.setdefault(key, {"sys": key[0], "place": key[1], "body": t.get("body", ""), "items": {}})
            cur = g["items"].get(p["id_item"])
            if not cur or p["price_buy"] < cur["price"]:
                g["items"][p["id_item"]] = {"id": p["id_item"], "name": p.get("item_name"), "price": p["price_buy"],
                                            "terminal": p.get("terminal_name") or t.get("name", ""), "updated": p.get("date_modified") or 0}
            sold.add(p["id_item"])
        out = []
        for g in places.values():
            g["items"] = sorted(g["items"].values(), key=lambda i: i["name"] or "")
            out.append(g)
        out.sort(key=lambda g: (-len(g["items"]), sum(i["price"] for i in g["items"])))
        return {"places": out, "notSold": [i for i in want if i not in sold], "names": names}

    # ------------------------------------------------------------------ the game's log: your buys and sells
    def commodity_by_guid(self, guid):
        """The game's commodity ID -> its name, via the Star Citizen Wiki (cached for a month)."""
        try:
            d = self.get(WIKI + "commodities/" + urllib.parse.quote(guid), 30 * DAY)
            d = d.get("data", d) if isinstance(d, dict) else {}
            return d.get("name") or d.get("display_name") or ""
        except Exception:
            return ""

    def game_log(self, sc_path, imported=()):
        """Commodity buys and sells the game wrote to Game.log (this session) and recent logbackups."""
        if not sc_path or not os.path.isdir(sc_path):
            return {"found": False, "reason": "scPath isn't set in config.json, so Flightdeck can't find the game's log", "trades": []}
        files = []
        main = os.path.join(sc_path, "Game.log")
        if os.path.exists(main):
            files.append(main)
        bk = os.path.join(sc_path, "logbackups")
        if os.path.isdir(bk):   # earlier sessions, last 7 days
            for f in sorted(os.listdir(bk)):
                full = os.path.join(bk, f)
                if f.lower().endswith(".log") and time.time() - os.path.getmtime(full) < 7 * DAY:
                    files.append(full)
        if not files:
            return {"found": False, "reason": f"No Game.log in {sc_path} yet - it appears once you start the game", "trades": []}
        raw = []
        for f in files:
            raw.extend(self._parse_log(f))
        raw.sort(key=lambda t: t["ts"])
        seen, trades = set(), []
        for t in raw:   # the same session can be in Game.log and a backup
            if t["key"] in seen:
                continue
            seen.add(t["key"])
            trades.append(t)
        try:
            data = self.trade_data()
        except Exception:
            data = None
        names = {}
        for t in trades:
            if t["kind"] == "cost":
                t["name"], t["commodity"], t["terminals"] = t["note"], None, []
                continue
            if t["guid"] not in names:
                names[t["guid"]] = self.commodity_by_guid(t["guid"])
            self._match(t, names[t["guid"]], data)
        imported = set(imported or ())
        for t in trades:
            t["imported"] = t["key"] in imported
        return {"found": True, "files": len(files), "trades": trades[-200:]}

    def log_lines(self, sc_path, pattern, limit=150):
        """The latest Game.log lines matching a search - for working out how the game writes new things."""
        path = os.path.join(sc_path or "", "Game.log")
        if not os.path.exists(path):
            return {"found": False, "lines": []}
        try:
            rx = re.compile(pattern or ".", re.I)
        except re.error as ex:
            raise RuntimeError(f"bad search: {ex}")
        with open(path, encoding="utf-8", errors="replace") as f:
            hits = [ln.rstrip()[:1200] for ln in f if rx.search(ln)]
        return {"found": True, "count": len(hits), "lines": hits[-limit:]}

    _ts = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z>")
    _kv = re.compile(r"(\w+)\[([^\]]*)\]")

    def _parse_log(self, path):
        cache = getattr(self, "_logcache", {})
        self._logcache = cache
        try:
            st = os.stat(path)
        except OSError:
            return []
        hit = cache.get(path)
        if hit and hit[0] == (st.st_mtime, st.st_size):
            return [dict(t) for t in hit[1]]
        out, loc = [], ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return []
        for line in lines:
            if "Location[" in line and "RequestLocationInventory" in line:
                m = re.search(r"Location\[([^\]]+)\]", line)
                if m:
                    loc = m.group(1)
                    for t in out:          # a trade made just before you checked the freight elevator
                        if not t["location"] and 0 <= self._secs(line) - t["_s"] < 1800:
                            t["location"] = loc
                continue
            if "SendShopBuyRequest" in line or SERVICE.search(line):
                c = self._cost_line(line, loc)
                if c:
                    out.append(c)
                continue
            if "SendCommodityBuyRequest" not in line and "SendCommoditySellRequest" not in line:
                continue
            m = self._ts.match(line)
            if not m:
                continue
            kv = dict(self._kv.findall(line))
            # buys:  price[total] shopPricePerCentiSCU[..] quantity[22400.000000 cSCU]
            # sells: amount[total] quantity[224]   (SCU, no unit)
            try:
                q = kv.get("quantity", "0")
                qty = float(q.split()[0])
                total = float(kv.get("price") or kv.get("amount") or "0")
            except ValueError:
                continue
            per = kv.get("shopPricePerCentiSCU")
            scu = qty / 100.0 if "cSCU" in q else qty
            if scu <= 0:
                continue
            ts = calendar.timegm(time.strptime(m.group(1)[:19], "%Y-%m-%dT%H:%M:%S"))   # the log is in UTC
            kind = "buy" if "BuyRequest" in line else "sell"
            boxes = re.findall(r"boxSize\[([\d.]+)\]\s*\|\s*unitAmount\[(\d+)\]", line)
            out.append({"key": f"{m.group(1)}|{kind}|{qty:.0f}|{total:.0f}", "ts": int(ts * 1000), "_s": ts, "kind": kind,
                        "guid": kv.get("resourceGUID", ""), "scu": round(scu, 2), "total": round(total),
                        "price": round(total / scu, 6) if total else round(float(per or 0) * 100, 6),   # exact, so SCU x price = what you paid
                        "shop": kv.get("shopName", ""), "location": loc,
                        "boxes": [[float(a), int(b)] for a, b in boxes]})
        for t in out:
            t.pop("_s", None)
        cache[path] = ((st.st_mtime, st.st_size), out)
        return [dict(t) for t in out]

    def _cost_line(self, line, loc):
        """Things you paid for at a shop or ship service (refuel, repair...) -> a possible run cost."""
        m = self._ts.match(line)
        if not m:
            return None
        kv = dict(self._kv.findall(line))
        amt = None
        for k in ("client_price", "price", "cost", "amount", "total", "fee"):
            try:
                v = float(kv.get(k, ""))
            except ValueError:
                continue
            if v > 0:
                amt = v
                break
        if not amt:
            return None
        ts = calendar.timegm(time.strptime(m.group(1)[:19], "%Y-%m-%dT%H:%M:%S"))
        item = kv.get("itemName", "")
        if item:
            what = re.sub(r"_+", " ", item).strip().title()
            try:
                n = int(float(kv.get("quantity", "1")))
            except ValueError:
                n = 1
            what += f" × {n}" if n > 1 else ""
        else:
            sv = SERVICE.search(line)
            what = sv.group(1).title() if sv else "Ship service"
        return {"key": f"{m.group(1)}|cost|{amt:.0f}", "ts": int(ts * 1000), "kind": "cost", "note": what, "total": round(amt),
                "shop": kv.get("shopName", ""), "location": loc, "guid": "", "scu": 0, "price": 0, "boxes": []}

    def _secs(self, line):
        m = self._ts.match(line)
        if not m:
            return 0
        return calendar.timegm(time.strptime(m.group(1)[:19], "%Y-%m-%dT%H:%M:%S"))

    @staticmethod
    def _tokens(s):
        s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "")
        t = set(x for x in re.split(r"[^a-z0-9]+", s.lower()) if x and not re.fullmatch(r"stanton\d*|pyro\d*|nyx\d*|scshop|store|shop|m|ht|int|ext|rr|g|lt|base", x))
        if "jp" in t:   # jump-point stations, e.g. RR_JP_StantonMagnus -> the gateway station
            t.discard("jp")
            t.add("gateway")
        return t

    def _match(self, t, name, data):
        """Which UEX commodity and terminal a logged trade was."""
        t["commodity"] = None
        t["terminals"] = []
        if not data:
            t["name"] = name
            return
        com = None
        if name:
            low = name.lower()
            com = next((c for c in data["commodities"] if c["name"].lower() == low), None) or \
                next((c for c in data["commodities"] if c["name"].lower().startswith(low)), None)
        t["name"] = com["name"] if com else (name or "Unknown cargo")
        if com:
            t["commodity"] = com["id"]
        tm = {x["id"]: x for x in data["terminals"]}
        loc_t, shop_t = self._tokens(t["location"]), self._tokens(t["shop"])
        col = 2 if t["kind"] == "buy" else 3
        cands = []
        for r in data["rows"]:
            if com and r[0] != com["id"]:
                continue
            term = tm.get(r[1])
            if not term:
                continue
            tt = self._tokens(term["name"] + " " + term.get("place", ""))
            score = 0.0
            if loc_t and loc_t <= tt:
                score += 100
            elif loc_t:
                score += 30 * len(loc_t & tt) / len(loc_t)
            if shop_t:
                score += 15 * len(shop_t & tt) / len(shop_t)
            if r[col] > 0 and t["price"] > 0:
                score += max(0.0, 40 - 400 * abs(r[col] - t["price"]) / t["price"])
            elif com:
                continue          # this terminal doesn't trade it that way
            cands.append((score, term["id"], term["name"], term.get("place", ""), r[col]))
        cands.sort(key=lambda c: -c[0])
        best, seen = [], set()
        for c in cands:
            if c[1] not in seen:
                seen.add(c[1])
                best.append({"id": c[1], "name": c[2], "place": c[3], "uex": c[4], "score": round(c[0])})
        t["terminals"] = best[:6]

    # ------------------------------------------------------------------ status
    def status(self):
        return {"errors": self.errors, "index": self.index_state,
                "prices": self.age(UEX + "commodities_prices_all/"), "items": self.age(UEX + "items_prices_all/")}

    # ------------------------------------------------------------------ your ledger
    def ledger(self):
        try:
            with open(self.ledger_path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        return {"v": 1, "runs": d.get("runs", []), "starred": d.get("starred", []), "settings": d.get("settings", {}),
                "hangar": d.get("hangar", [])}

    def save_ledger(self, d):
        if not isinstance(d, dict) or not isinstance(d.get("runs", []), list) or not isinstance(d.get("starred", []), list):
            raise ValueError("ledger must have runs and starred lists")
        out = {"v": 1, "runs": d.get("runs", [])[-2000:], "starred": [int(x) for x in d.get("starred", [])][:300],
               "settings": d.get("settings", {}) if isinstance(d.get("settings"), dict) else {},
               "hangar": [h for h in d.get("hangar", []) if isinstance(h, dict)][:500] if isinstance(d.get("hangar"), list) else []}
        with self.ledger_lock:
            if os.path.exists(self.ledger_path):
                try:
                    os.replace(self.ledger_path, self.ledger_path + ".bak")
                except OSError:
                    pass
            tmp = self.ledger_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1)
            os.replace(tmp, self.ledger_path)
        return out

    # ------------------------------------------------------------------ sending trades to UEX
    def uex_keys(self):
        try:
            with open(self.uex_path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        return {"appToken": d.get("appToken", ""), "secretKey": d.get("secretKey", ""),
                "autoSend": bool(d.get("autoSend", False)), "user": d.get("user", "")}

    def uex_public(self):
        k = self.uex_keys()
        return {"appTokenSet": bool(k["appToken"]), "secretKeySet": bool(k["secretKey"]),
                "ready": bool(k["appToken"] and k["secretKey"]), "autoSend": k["autoSend"], "user": k["user"]}

    def _uex_call(self, method, resource, query=None, body=None, keys=None, auth=True, errors=None):
        k = keys or self.uex_keys()
        url = UEX + resource + "/"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"User-Agent": UA, "Accept": "application/json", "secret-key": k["secretKey"]}
        if auth:
            headers["Authorization"] = "Bearer " + k["appToken"]

        def send(data, ctype):
            h = dict(headers)
            if data is not None:
                h["Content-Type"] = ctype
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as ex:
                raw = ex.read().decode("utf-8", "replace")
                if not raw.strip():
                    raise RuntimeError(f"UEX said HTTP {ex.code}")
            try:
                return json.loads(raw)
            except ValueError:
                raise RuntimeError("UEX sent back something unexpected: " + raw[:120])

        if body is None:
            d = send(None, None)
        else:
            d = send(json.dumps(body).encode(), "application/json")
            if str(d.get("status", "")).startswith("missing_") and "secret" not in str(d.get("status")):
                d = send(urllib.parse.urlencode(body).encode(), "application/x-www-form-urlencoded")   # in case it wants a form
        st = d.get("status")
        if st != "ok":
            raise RuntimeError((errors or {}).get(st) or UEX_ERRORS.get(st, f"UEX said: {st or d.get('message') or 'error'}"))
        return d.get("data")

    def uex_save(self, d):
        k = self.uex_keys()
        for f in ("appToken", "secretKey"):
            v = d.get(f)
            if isinstance(v, str) and v.strip():
                k[f] = v.strip()
            if d.get("clear"):
                k[f] = ""
        if "autoSend" in d:
            k["autoSend"] = bool(d["autoSend"])
        if d.get("clear"):
            k["autoSend"], k["user"] = False, ""
        msg = None
        if k["secretKey"] and (d.get("test") or d.get("secretKey")):
            if len(k["secretKey"]) != 40:
                raise RuntimeError("The secret key should be 40 characters - copy it again from your UEX profile")
            u = self._uex_call("GET", "user", keys=k, auth=False)
            u = u[0] if isinstance(u, list) and u else u
            k["user"] = (u or {}).get("username") or (u or {}).get("name") or ""
            msg = f"Linked to UEX as {k['user']}" if k["user"] else "Secret key works"
        tmp = self.uex_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(k, f, indent=1)
        os.replace(tmp, self.uex_path)
        return {**self.uex_public(), "message": msg}

    def uex_send(self, t):
        """One buy or sell -> UEX. Returns UEX's id for it."""
        k = self.uex_keys()
        if not (k["appToken"] and k["secretKey"]):
            raise RuntimeError("Add your UEX app token and secret key first (UEX button on the Trade tab)")
        if t.get("kind") not in ("buy", "sell"):
            raise RuntimeError("Only buys and sells can go to UEX")
        body = {"id_terminal": int(t["tid"]), "id_commodity": int(t["cid"]), "operation": t["kind"],
                "scu": int(round(float(t["scu"]))), "price": float(t["price"]), "is_production": 1}
        d = self._uex_call("POST", "user_trades_add", body=body, keys=k)
        uid = d.get("id_user_trade") if isinstance(d, dict) else d
        if not uid:
            raise RuntimeError("UEX didn't return an id for the trade")
        return int(uid)

    def uex_edit(self, uex_id, t):
        """Change a trade that's already on UEX (e.g. you picked the wrong terminal)."""
        if t.get("kind") not in ("buy", "sell"):
            raise RuntimeError("Only buys and sells are on UEX")
        body = {"id": int(uex_id), "id_terminal": int(t["tid"]), "id_commodity": int(t["cid"]), "operation": t["kind"],
                "scu": int(round(float(t["scu"]))), "price": float(t["price"]), "is_production": 1}
        self._uex_call("POST", "user_trades_edit", body=body)
        return True

    def uex_report(self, d):
        """Send what a terminal shows in game (price, stock, inventory level, box sizes) to UEX as a data report."""
        k = self.uex_keys()
        if not k["secretKey"]:
            raise RuntimeError("Add your UEX secret key first (UEX button on the Trade tab)")
        prices = []
        for p in d.get("prices") or []:
            e = {"id_commodity": int(p["cid"])}
            side = "buy" if p.get("side") == "buy" else "sell"
            if p.get("missing"):
                e["is_missing"] = 1
            else:
                e["price_" + side] = float(p["price"])
                if p.get("scu") not in (None, ""):
                    e["scu_" + side] = int(float(p["scu"]))
                if p.get("status"):
                    e["status_" + side] = max(1, min(7, int(p["status"])))
                if p.get("boxes"):
                    e["container_sizes"] = ",".join(str(int(b)) for b in p["boxes"] if int(b) in (1, 2, 4, 8, 16, 24, 32))
            prices.append(e)
        if not prices:
            raise RuntimeError("Nothing to report")
        body = {"id_terminal": int(d["tid"]), "type": "commodity", "is_production": 1, "prices": prices}
        if d.get("details"):
            body["details"] = str(d["details"])[:300]
        if d.get("screenshot"):
            body["screenshot"] = str(d["screenshot"]).split(",", 1)[-1]   # base64, without the data: prefix
        r = self._uex_call("POST", "data_submit", body=body, keys=k, errors={
            "user_not_allowed": "UEX only takes price reports from its datarunners, and your account isn't one (or has a temporary restriction). "
                                "Your trades still go to your UEX Trade Log as normal. Ask UEX about becoming a datarunner, then try again.",
            "screenshot_required": "UEX wants a screenshot with this report - add one and send again"})
        return {"ids": (r or {}).get("ids_reports") if isinstance(r, dict) else r, "user": (r or {}).get("username") if isinstance(r, dict) else None}

    def uex_remove(self, uex_id):
        self._uex_call("DELETE", "user_trades_remove", query={"id": int(uex_id), "is_production": 1})
        return True

    def ledger_csv(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Run", "Run started", "Ship", "Time", "Type", "Commodity", "Where", "SCU", "Price per SCU", "Total aUEC"])
        for n, r in enumerate(self.ledger()["runs"], 1):
            start = time.strftime("%Y-%m-%d %H:%M", time.localtime((r.get("started") or 0) / 1000))
            for t in r.get("trades", []):
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime((t.get("ts") or 0) / 1000))
                total = t.get("amount") if t.get("kind") == "cost" else (t.get("scu") or 0) * (t.get("price") or 0)
                sign = 1 if t.get("kind") == "sell" else -1
                w.writerow([n, start, r.get("ship", ""), when, t.get("kind"), t.get("name", t.get("note", "")),
                            t.get("terminalName", ""), t.get("scu", ""), t.get("price", ""), round(sign * (total or 0))])
        return buf.getvalue()
