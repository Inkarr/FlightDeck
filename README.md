# Flightdeck — tablet control panel for Star Citizen

*(Formerly ShipDeck.)*

## Quick start (from source)

1. Install **Python 3.9+** from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**, or `git clone`) into a folder such as `C:\Flightdeck`.
3. Double-click **start.bat**. The first time it installs two small packages, finds Star Citizen for you (or asks where it is), offers to open Windows Firewall for the tablet, and prints the iPad address and a QR code.
4. Open that address in Safari on the iPad and **Add to Home Screen**.

## Your files: `mydata\`

Everything personal lives in the **`mydata`** folder next to the code, which is in `.gitignore`. Updating the code (`git pull`, a new zip, the installer) never touches it, and it never ends up on GitHub.

| File in `mydata\` | What it holds |
|---|---|
| `config.local.json` | This PC's settings: `scPath`, `pin`, `port` and any other top-level `config.json` field. These override `config.json`. |
| `my_buttons.json`, `my_layout.json`, `my_favourites.json`, `my_emotes.json` | Your own buttons, tabs, Favourites and emotes |
| `my_market.json` (+ `.bak`) | Trade runs, hangar, starred items |
| `my_uex.json` | Your UEX app token and secret key. Keep it private. |
| `market_cache\`, `sc_defaults.json` | Downloaded prices and items, and the game's default keybinds (both rebuilt automatically) |

To back up or move to a new PC, copy `mydata`. Older copies of Flightdeck kept these files next to `server.py`; they're moved into `mydata` automatically on the next start.


A GameGlass-style touch panel. Your iPad or tablet shows the buttons, and a small server on your gaming PC turns each tap into a real keypress for the game.

```
iPad (Safari)  ──Wi-Fi──▶  server.py on PC  ──SendInput──▶  Star Citizen
                                  ▲
                    reads your keybinds from the game
```

## Flightdeck.exe (no Python needed)

Double-click **Build Exe.bat** on this PC. It takes about a minute the first time, and makes `dist\Flightdeck.exe`: one file with everything inside. Copy that file to any Windows PC, put it in its own folder (for example `C:\Flightdeck`) and double-click it.

On first run the exe:
- unpacks its files next to itself (`static`, `sc_data`, `config.json`). If that folder is read-only, it uses `%LOCALAPPDATA%\Flightdeck` instead.
- finds Star Citizen, or asks you where it is.
- offers once to open Windows Firewall for the iPad (one admin prompt).
- shows the iPad address and QR code, then runs as normal.

Your `mydata` folder is never touched. To update, rebuild and replace `Flightdeck.exe`; the web panel and game data inside it refresh automatically.

**First launch on a new PC:** Windows SmartScreen may say *"Windows protected your PC"*, because the exe isn't code-signed. Click **More info → Run anyway**.

## Installing on a new PC

1. On this PC, double-click **Build Setup.bat**. It makes `dist\Flightdeck-Setup.zip` from the current Flightdeck.
2. Copy the zip to the new PC, unzip it anywhere, and double-click **Install Flightdeck.bat**. Windows asks for administrator rights.

The installer:
- finds Python 3.9+, or installs Python 3.13. It uses winget, or falls back to python.org, and checks the download's signature.
- installs the two packages Flightdeck uses (`zstandard`, `qrcode`).
- copies Flightdeck to `C:\Flightdeck`, or a folder you choose.
- finds Star Citizen on any drive and saves it as `scPath` in `mydata\config.local.json`.
- opens the firewall for your home network. It offers to switch the network to *Private* if Windows has it as Public, and to remove any old "block Python" firewall rules.
- creates Desktop and Start menu shortcuts. It can also start Flightdeck with Windows if you want.
- adds Flightdeck to Windows **Installed apps**, so it can be uninstalled normally.
- reads the default keybinds.
- shows the iPad address with a **QR code**: point the iPad camera at it to open Flightdeck.

**Upgrading:** run a newer setup the same way. Your `mydata` folder is kept.

Every time Flightdeck starts, the window shows the address and QR code again.

## Make the tabs your own

**Edit (top bar)** rearranges whichever tab you're on:
- **Built-in tabs** (Flight, Landing, Combat, Mining, Salvage, On Foot): the first Edit turns the tab's panels into movable pieces, placed where they already are. Move them, resize them, remove them, and **Add** anything from the library: whole panels from any tab, single buttons, or emotes. **Reset tab** puts the original layout back.
- **Card** adds a named background card, like a panel, to group buttons. Its toolbar (top right, in Edit) has four buttons:
  - ✎ renames the card.
  - **Tidy** lays the buttons inside out evenly so they fill the card, like a built-in panel.
  - **+** adds buttons straight into the card, then tidies it.
  - × removes the card but leaves its buttons.

  Moving a card moves the buttons inside it. To change the order inside a card, drag the buttons, then tap Tidy.
- **Grid** sets how fine the layout is: 6×4 up to 16×10. Changing it scales your layout to fit, and cards re-tidy themselves.
- Social and Keybinds can't be rearranged, because their lists update themselves.

**Tabs (top bar)** manages the tab row:
- **+ New tab** adds your own named tab. It works like Favourites.
- ▲▼ reorder the tabs.
- **Hide** removes a tab you don't use. Its buttons still work on other tabs, and you can show it again any time. Keybinds always stays.
- On your own tabs you can also **Rename** them, tap the icon to **pick an icon**, and **Delete** them.

Everything is saved on the PC in `mydata\my_layout.json`, so it's the same on any tablet. The first time it runs, your old Favourites are brought across automatically.

## Make your own buttons and panels

Tap **Library** at the top (the books icon) - or **Add → New button** while editing - to see every button and panel, change them, or make something new. To design a button:

- **Style** - Button, On / off (shows ON/OFF like Night Vision), Wide, Big round icon (like Power), Mode (big text like SCM), Tall (like Shields), Round (like Closest Hostile), Safety cover (lift then press), Lever (like the landing gear), + / − pair (like Weapons) and Bar with + / − (like Speed limit).
- **Colour** - blue, amber, red, green or white.
- **Icon** - pick from the built-in icons or tap **Upload** to use your own picture (PNG, JPG...). Leave *Colour uploads like the other icons* ticked for one-colour pictures; untick it to keep the picture's own colours.
- **What it sends** - a **Star Citizen action** (search e.g. *night vision*, *gear*; the key follows your in-game binds) or a fixed **Key** combo. The + / − and bar styles need one for each button.
- **When pressed** - Tap, Hold (held while you hold it) or Repeat. A **Light group** makes buttons light one at a time, like SCM / NAV.

The preview on the right shows exactly how it will look. Saved buttons appear under **My buttons & panels** in **Add** and can go on any tab.

**Your own panels:** in **Library** tap **New panel**, name and number it, set its size with the arrows, **Add** buttons and arrange them, then **Save**. Or build one on a tab: add a **Card**, put buttons in it and tap the disk on the card (**Save to library**). Put a panel on any tab from **Add**. To change one, tap its pencil on a tab or **Edit** in the Library - saving updates it on every tab it's on.

**Changing any button or panel:** tap **Library**, find it (search, or open a tab's list) and tap **Edit**. Change its name, style, icon, colour, what it sends or its rule, and it changes everywhere it's used - including its own tab. Panels open in the panel editor: move, resize, add or remove buttons, then **Save**. **Reset** (or *Reset to original* in the editor) undoes your changes. Style changes show wherever the button stands on its own; inside a fixed group (e.g. the shield faces) it keeps its shape.

**Rules - "Only works when":** in the button designer pick another button, e.g. *Power is on* or *NAV is selected*. Until then the button is greyed out and won't send anything (Shields, Engines and Weapons work this way with Power).

Everything you make is kept on the PC in `mydata\my_buttons.json` (the installer keeps it when updating).

**Save default:** when a tab looks how you want, tap **Edit → Save default** (the disk). **Reset tab** then puts it back to that. On a built-in tab, tapping **Reset tab** when it already matches your default takes it back to the original layout (your default is kept).

## Favourites tab (★)

The star tab, first in the row, is your own panel.

1. Tap **Edit**, then **Add**. Pick a whole **PANEL** (amber), which comes exactly as it is on its tab: the gear lever, quantum dial, shield faces, power bars and so on. Or pick a single button, or any emote on your Social tab. Tap a chosen one again to take it off. Panels scale themselves to whatever size you give them.
2. **Drag** a button to move it, and drag its **bottom-right corner** to resize it. Buttons snap to the grid and can't overlap; a red outline means that space is taken.
3. Tap **×** to remove a button. **Grid** switches between 6×4 (big buttons), 8×5 and 10×6 (more buttons).
4. Tap **Done**.

Favourite buttons are the real thing: same keys, same hold/repeat timing, safety covers, and lights in sync with the other tabs. The layout is saved on the PC in `mydata\my_favourites.json`, so it works from any tablet and survives updates.

## Keybinds come from the game

Flightdeck reads your keybinds straight from Star Citizen. You never need to edit keys in Flightdeck.

- **Defaults** come from `Data.p4k`, the game's own data. When a patch changes the defaults, Flightdeck notices on its next start and re-reads them (it takes a few seconds).
- **Your own changes** come from `user\client\0\Profiles\default\actionmaps.xml`. They're read when Flightdeck starts, and again whenever you tap **Refresh keybinds** on the **Keybinds** tab. After a change in-game, leave the keybinding screen (that's when Star Citizen saves the file), then tap Refresh. Every button updates straight away.
- **Timing** is handled for you. Some actions only fire on a long press, such as Auto Land (hold N), Auto Target (hold T), Holster (hold R) and Self Destruct. Flightdeck holds those keys for exactly as long as the game needs.

The game folder is `scPath` in `mydata\config.local.json`. If it's missing, Flightdeck finds it on first start (usually something like `C:\Program Files\Roberts Space Industries\StarCitizen\LIVE`). Flightdeck only ever reads from that folder and never writes to it.

## Keyboard mirroring

Lights on the tablet also follow the keys you press on the PC. Press N on your keyboard and the tablet's Landing Gear light flips, just as if you'd tapped it. Buttons briefly flash green when this happens.

- Only toggle and radio buttons (the ones with a light) are mirrored, and only keyboard keys, not mouse or HOTAS buttons.
- It only counts keys while Star Citizen is the focused window.
- Timing follows the game: a quick tap of N flips the gear, but holding N (Auto Land) doesn't.
- Pressing Enter (chat) pauses mirroring until you press Enter or Esc again, so typing doesn't flip lights.
- Some keys mean different things in a seat and on foot (C is Decoupled or Crouch). The tablet uses whichever tab you last had open: On Foot or Social means on foot, anything else means in a seat.
- Flightdeck can't read the game's real state, so lights can still drift, for example if the game ignores a key. Tap **Fix** to correct a single light, or **Reset** to reset them all.
- Turn it off with `"mirrorKeyboard": false` in `mydata\config.local.json`. `"mirrorOnlyInGame": false` mirrors keys in any window; `"gameExe"` changes the game's program name (default `StarCitizen.exe`).

No extra packages are needed. If the game runs as administrator, run start.bat as administrator too, or Windows won't let Flightdeck see the keys.

## Emotes

The Social tab shows only the emotes you pick. Tap **Choose** on the tab to open the full list (from the [Star Citizen Wiki](https://starcitizen.tools/Emotes)), search it, and tap emotes on or off. Your choice is saved on the PC in `mydata\my_emotes.json`, so it survives reloads and works from any tablet.

Emotes are sent by opening chat and typing the command, e.g. `/wave1`. The full list lives in `sc_data/emotes.json` if you want to add new ones.

## Trade tab

Find the best cargo run and keep a record of what you make. Prices come from [UEX Corp](https://uexcorp.space), the community trade site. The PC downloads them, so it needs an internet connection; no account or API key is needed.

- **Routes:** pick a star system, your ship (or type your SCU) and a budget. Optionally set **Starting from**, **Finishing at** and **Avoid**: each opens a searchable list of places grouped by system and planet. Avoid takes as many places as you like, and with **All** systems you can avoid a whole system. Flightdeck lists the most profitable buy → sell pairs, with price per SCU, stock on sale, demand where it's known, and how old each price is. Prices go amber after a week and red after a month. Routes never cross a jump point. Tap **Buy this** to log the buy; the sell terminal is then picked for you when you sell.
- **Round trips:** tap **Round trip** under **Trip** to plan a cargo out and a different cargo back to where you started. **Starting from** is your home base and **Turn around at** (optional) is where you sell the first cargo and buy the second. Each round trip shows both legs and the total profit; the return leg's budget includes what the first leg made. **Buy this** logs the outbound buy, and **Current run** then shows the way back with a **Buy the return cargo** button (at UEX's latest price).
- **Current run:** one trip, from your first buy to cashing out. Log each **Buy**, **Sell** and **Cost** (fuel, repairs...). Prices fill in from UEX; change them to what you actually paid. It shows cargo aboard, profit so far and aUEC per hour. Tap **End run** (twice) when you're done.
- **Cargo grid & boxes:** pick a ship on Routes and tap **Cargo grid & boxes** (or **GRID** on the Hangar tab, or **Boxes** on a route). It shows the grids in **3D** (drag to turn, pinch or scroll to zoom, double-tap to reset) or as **Layers** seen from above, and works out the fewest boxes for the load: e.g. *9 × 32, 1 × 8, 1 × 4*. Tap a box size to see what happens if a terminal only hands out smaller boxes; **Boxes** on a route starts at the biggest box that terminal gives out. Filled boxes are the load, dashed ones are spare room. Grid sizes come from the Star Citizen Wiki; the packing is Flightdeck's own estimate.
- **Loading more than one cargo:** with a run going, the Routes list allows for what's already aboard (tick **Allow for cargo aboard** off to plan as if empty), and the cargo grid shows your cargo aboard in its own colour, then the boxes to buy for the next load, dashed, fitted round it. Change a commodity's SCU there if you didn't load it all, or untick it if it isn't in the ship. Box sizes come from the game log when Flightdeck has them; otherwise it works them out.
- **From your game log:** Star Citizen writes every commodity buy and sell to its `Game.log`, with the exact price and SCU. Flightdeck reads it (from the game folder in `scPath`, plus the last week of `logbackups`) and lists new ones on **Current run**: **Add** puts it straight into your run, **Edit** opens it first, × skips it, **Add all** takes the lot. Things you bought in shops (and ship services such as refuelling or repairs, once the game logs them) show as **COST**: add the ones that belong to the run. **Add all trades** only takes the buys and sells. It works out the commodity from the game's ID (via the Star Citizen Wiki) and the terminal from where you were and the price; "(best guess)" means check it. The Current run button shows how many are waiting.
- **Searching:** in the Log a trade dialog, tap the commodity or the terminal to search them; terminals that trade it come first with their prices, then everywhere else by system and planet.
- **Ledger:** every finished run with total profit, the last 7 days, aUEC per hour and your best cargo. Tap a run to see its trades, delete one, or carry the run on. **Export CSV** downloads the lot.

**Sending trades to UEX (optional):** tap **UEX** at the top of the Trade tab and paste two things from uexcorp.space: your **app token** (create an app under **My Apps**) and your **secret key** (in your UEX profile). Tap **Test & save**. Then either tick **Send every buy and sell automatically**, or tap **→ UEX** on a trade (or **Send to UEX** on a run) to send it yourself. Sent trades show **UEX ✓**, and deleting one here deletes it on UEX too. Costs aren't sent, because UEX only logs commodity trades. UEX only accepts trades from accounts verified with RSI. Both keys stay on the PC in `mydata\my_uex.json`; the tablet never sees them.

**Reporting prices to UEX:** if a terminal in game doesn't match the route (e.g. Tin is on low inventory), tap **REPORT TO UEX** on that side of the route. It starts with what UEX has; change the price (the game often shows it per box, so pick **Price is for** "a 32 SCU box" and Flightdeck divides it), the shop quantity, the inventory level and the cargo sizes on offer, then **Send to UEX**. It needs your UEX secret key. UEX asks new datarunners for a screenshot, which you can attach. Your routes use the new figures straight away.

UEX prices are reported by players, so they can be out of date or miss demand limits. Check the terminal before you buy a full load.

## Hangar tab

The ships you have, each with its picture (from UEX). **+ Add ship** opens the panel for adding ships and **HIDE** tucks it away again; once you have ships it starts hidden. Add each one as **Bought**, **Loaner** or **Rented** (1, 3, 7 or 30 days). The Routes ship list then shows only your ships that carry cargo; tick **Show ships you don't have** to see the rest. Rentals show the time left, **+7D** (or however long you rented it) rents it again, and expired ones drop off the Routes list. Add a pledged ship that isn't in the game yet and Flightdeck offers to add its loaners. Ships not in the game yet are marked in amber; tick **Hide ships not in the game yet** to leave them out of the search, your hangar list and the Routes list. Tap a ship's type to change it. Tap **›** next to a ship to open or close the list of its cargo: its own cargo grids (from the game data), cargo you've added and its modules. A ship's own SCU is the bigger of UEX's figure and the Star Citizen Wiki's cargo grids, because UEX lists some ships (like the Aurora Mk II) with no cargo. **+ CARGO** adds either cargo that's **part of the ship** but missing from the game data (it always counts), or a **swappable module** that belongs to that ship but can be swapped out, such as the Aurora Mk II cargo module: give its grid size (width × length × height in SCU) and how many grids. Tap **✓ Fitted / Not fitted** when you swap it in or out; only fitted modules count. Fitted modules count towards the ship's SCU on Routes and show in its cargo grid.

**Loadout:** each ship shows its stock **GUNS**, **TURRETS**, **MISSILES** and **SHIELDS** (for example *GUNS 3×S3*). Tap one, or **INFO**, to open the ship's page: maker, role and description, specs (crew, cargo, size, mass, speeds, pitch/yaw/roll, hull and shield HP, pilot DPS, quantum speed and range, fuel, insurance claim and expedite times, pledge price), then every weapon, turret, missile, shield, power plant, cooler, quantum drive and utility item with its size, grade and maker, and where to buy or rent it in game (aUEC). This is the stock loadout from the [Star Citizen Wiki](https://star-citizen.wiki); ships you've changed in game will differ. On the same page, **Yours** keeps what you paid ($), the insurance (LTI, 120 months...) and a note for each ship; the hangar header adds up what you've paid.

## Items tab

Where to buy armour, weapons, attachments, gadgets, medpens, clothing and ship parts.

- Search by name, maker or type, or tap a category. Each result shows how many shops sell it and the cheapest price.
- Tap an item for its stats, picture and description (from the [Star Citizen Wiki](https://starcitizen.tools)) and every shop that sells it, cheapest first, with how old each price is. Items no shop sells are marked as loot or mission only.
- Tap ☆ to star items. **★ Starred** is your shopping list: it works out the fewest stops to buy everything, and lists anything you can't buy in a shop.

The first time you open Items, the PC downloads the item list (about 40 requests to UEX, under a minute). After that it's cached in `mydata\market_cache`.

Your runs, starred items and Trade settings are saved on the PC in `mydata\my_market.json` (the installer keeps it when updating; a backup of the previous save is kept as `my_market.json.bak`). Trade and Items can be hidden or moved with **Tabs** like any other tab.

## What the tags mean

| Tag | Meaning |
|---|---|
| *(none)* | Uses Star Citizen's default key. |
| **BIND** (cyan) | Star Citizen has no default key for this action. Flightdeck shows a spare Right-Ctrl combo; bind it once (see below). |
| **NOT BOUND** (dimmed) | You've cleared this bind in-game, so there's nothing to press. Bind it again in-game and the button comes back by itself. |
| **CHAT** | An emote with no keybind. It opens chat and types the command, e.g. `/wave`. If you give the emote a key in-game, Flightdeck switches to the key. |
| **HOLD** | The key stays down while your finger is on the button. |
| **REPEAT** | Hold to keep stepping (power, speed limit, scan angle and so on). |

## One-time binding (BIND buttons)

These actions have no default key in Star Citizen 4.10:

1. Start Flightdeck and open Star Citizen → **Options → Keybindings**.
2. Search for the action and click its keyboard slot.
3. **Tap the matching button on the tablet.** The game records the combo.

You can also bind any key you like in-game. Tap **Refresh keybinds** and the BIND tag disappears.

The **Keybinds** tab always shows the current list of actions still needing a bind, plus all your custom binds.

| Tab | Button | Star Citizen action | Spare combo |
|---|---|---|---|
| Flight | G-Safe | G-Force Safety On/Off (Toggle / Hold) | Left Ctrl + G |
| Flight | ESP | E.S.P. - Toggle On / Off (Press) | Left Ctrl + E |
| Landing | Doors | Open/Close Doors (Toggle) | Right Ctrl + F8 |
| Landing | Door Locks | Lock/Unlock Doors (Toggle) | Right Ctrl + F7 |
| Combat | Prev | Cycle Lock - All - Back | Right Ctrl + F11 |
| Combat | Missile Mode | Toggle Missile Operator Mode | Right Ctrl + F12 |
| Combat | Arm −1 | Decrease Number of Armed Missiles | Right Ctrl + NUM 0 |
| Combat | Lead / Lag PIP | Toggle Lead / Lag PIPs | Right Ctrl + NUM 3 |
| Combat | Panic | Decoy - Panic Launch (tap) | Right Ctrl + NUM 9 |
| Combat | Top | Shield raise level top | Right Ctrl + NUM 7 |
| Combat | Front | Shield raise level front | Right Ctrl + NUM 8 |
| Combat | Left | Shield raise level left | Right Ctrl + NUM 4 |
| Combat | Reset | Shield reset levels | Right Ctrl + NUM 5 |
| Combat | Right | Shield raise level right | Right Ctrl + NUM 6 |
| Combat | Bottom | Shield raise level bottom | Right Ctrl + NUM 1 |
| Combat | Back | Shield raise level back | Right Ctrl + NUM 2 |
| On Foot | Inspect | Inspect Item | Right Ctrl + Insert |
| On Foot | Drop | Drop Item | Right Ctrl + Home |

Every spare combo was checked against every Star Citizen default bind, so none of them clash.

## Setup (one time)

1. Install **Python 3.9+** from python.org on the gaming PC. Tick **"Add python.exe to PATH"** during install.
2. Optional: start.bat offers to open the firewall for you. To do it by hand, right-click **allow-firewall.bat** in the Flightdeck folder and choose **Run as administrator**. Your Wi-Fi must be set as a *Private* network in Windows.

## Each session

1. Double-click **start.bat**. The first time, it also installs `zstandard` (needed to read Data.p4k) and `qrcode`. The window then prints a URL such as `http://192.168.1.20:8765`.
2. On the iPad, open that address in **Safari**. The first time, tap Share → **Add to Home Screen**. It installs as **Flightdeck** with its own icon and opens full screen.
3. Keep the Star Citizen window focused. Keys go to whatever window is in front.

## Tabs

| Tab | What's on it |
|---|---|
| **Flight** | Decoupled, G-Safe, ESP, cruise throttle, speed limit + / −, speed brake, power (shields + weapons), NAV/SCM, quantum, starmap, mobiGlas, camera, eject, self destruct |
| **Landing** | Request landing, gear, VTOL, auto land, docking, cargo loading, doors, lights, night vision, port lock |
| **Combat** | Targeting, pins, missiles, gimbal, aim mode, countermeasures, power management, shield faces |
| **Mining** | Mining mode, fire laser, fracture/extract, laser power, modules, beam high/low, scanning, power, shields |
| **Salvage** | Salvage mode, fire heads, focus, modifiers, beam axis and spacing, gimbal, scanning, doors |
| **Social** | The emotes you have chosen (tap **Choose** to pick from all 106), plus the weapon-drawn hand signals (numpad by default) |
| **On Foot** | Inventory, medpen, weapons, holster, fire mode, zeroing, Zero-G, tractor, stand/crouch/prone, flashlight, helmet, visor |
| **Keybinds** | The Refresh keybinds button, status, your custom binds, and actions still needing a bind |
| **Trade** | Best trade routes for your ship and budget, your current run, and a ledger of profit per run |
| **Items** | Find where to buy any item, its stats, and a shopping list for the items you star |

## Customising `config.json`

Each button links to a Star Citizen action:

```json
{ "id": "lights", "label": "Lights", "sc": "v_lights", "toggle": true }
```

**Button fields**

| Field | Meaning |
|---|---|
| `sc` | The Star Citizen action name. Its key is read from the game. `sc_data/defaultProfile.plain.xml` lists every action. |
| `keys` | A fixed key or combo. Used when there's no `sc`, or as the spare when the action isn't bound. |
| `text` | A chat command, used when the action has no key. |
| `mode` | `"hold"` (key down while touched) or `"repeat"`. Hold mode is chosen automatically when the game expects a held key. |
| `holdMs` | Overrides the automatic press length. |
| `toggle` | Shows an amber state light. |
| `state` | Shares the light with buttons on other tabs. |
| `radio` | Only one button in the group is lit at a time. `radioClear` clears the group. |
| `guard` | Adds a safety cover. |
| `style` | `primary`, `warn` or `danger`. |
| `radioDefault` | This button's light is on when nothing else in its `radio` group is (SCM starts lit, as when you power up a ship). |
| `radioCycle` | Pressing it moves the light to the next button in that `radio` group. |
| `noRepress` | Does nothing if its light is already on. NAV and SCM both hold B, so tapping the lit one would switch away from it. |
| `onlyWhen` | Greys the button out unless a `radio` group is on a given button, e.g. Engage Quantum only in NAV: `{"radio": "mm", "is": "mm_nav", "label": "NAV"}`. |
| `toggleOff` | Makes one toggle out of a pair of actions. Doors sends Open All when off and Close All (`toggleOff`) when lit; Locks does the same with Lock / Unlock. |
| `toggleDefault` | The light starts on, and Reset puts it back on (Helmet). |
| `alsoOn`, `alsoOff` | Other lights this one switches with it. Power: on lights Shields + Weapons (`alsoOn`), off turns Shields, Engines and Weapons off (`alsoOff`). |
| `meter`, `step` | Moves a bar each time it's pressed (speed limit). `meterSteps` is how many presses from min to max (20) and `meterDefault` where it starts (20 = 100%). |

**Layout fields**
- Panel: `cols`, and `layout: "shields"` for the cross pad.
- Tab: `compact`, `rowMax`.

**Top-level fields:** `scPath`, `chatKey`, `pin`, `port`, `mirrorKeyboard`, `mirrorOnlyInGame`, `gameExe`. Put your own values for these in `mydata\config.local.json` rather than `config.json`, so they survive updates.

Edits to `config.json` are picked up the next time the tablet reloads the page. The lights on the panel can't read the game's state. If one drifts, tap **Fix**, tap that light (or mode, or the speed bar) to correct it, then **Done**. Nothing is sent to the game while fixing. **Reset** puts everything back to the start.

## Troubleshooting

| Problem | Fix |
|---|---|
| Tablet says "PC not found" | Check both devices are on the same Wi-Fi, that you ran allow-firewall.bat, and that you're using the IP start.bat printed. |
| Server logs the press but the game ignores it | If the game runs as administrator, run start.bat as administrator too. Also check the game window is focused. |
| "Data.p4k not found" | Fix `scPath` in `mydata\config.local.json` so it points at your LIVE (or PTU) folder. |
| A rebind isn't showing | Leave Star Citizen's keybinding screen first (that's when it saves), then tap **Refresh keybinds** on the Keybinds tab. |
| A key seems stuck | Tap **Release**, or close start.bat (it releases everything on exit). |
| Trade or Items says it couldn't get data | The PC needs internet access. Flightdeck keeps the last download in `mydata\market_cache`, so it carries on with older prices if UEX is down. |
| Want to refresh the defaults manually | Run `python sc_bindings.py "<your StarCitizen\\LIVE folder>"`. |

Files in `sc_data`:
- `default_emotes.json` is the starter set of emotes shown until you pick your own.
