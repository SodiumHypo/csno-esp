# Phase 3 — Frida ESP: the reference implementation (✅ frozen @ `v1.0-frida`)

The shipped v1 approach: a Frida agent inside the game process answers one RPC
(`getEspFrame`) per frame; a Windows overlay renders it. **This code is frozen
as tested — it is the behavioral specification the v2 host-reader must
reproduce, not a base for further feature work.**

## Startup chain

```
start_esp.bat          one-click: ldconsole launch → adb boot-wait → am start game
  └─ esp_auto.py       supervisor (tkinter mainloop + daemon RPC worker)
       ├─ ensures frida-server-x64 running (adb, root, setsid)
       ├─ attaches to com.ledi.csno pid (re-attach on crash/restart)
       ├─ loads esp_loop.js  → rpc.getEspFrame(guestW, guestH) @ 30 Hz
       └─ esp_overlay.py draws on a transparent click-through topmost window
quit: red "✕ ESP" pill (top-right) — the only control in background launches
```

## Frame contract (the seam for v2)

`getEspFrame(w, h)` → JSON:

| Field | Type | Meaning |
|-------|------|---------|
| `ok` | bool | frame usable (false ⇒ show `error`) |
| `error` | str | human-readable stage failure: `modules loading`, `no local player (in match?)`, `renderer null`, `matrix not ready` |
| `localTeam` | int | local player's `m_iTeamNum` (−1 unknown) |
| `players[]` | array | one entry per filtered player |
| `players[].i` | int | entity-list index |
| `players[].local` | 0/1 | is the local player (never drawn — user decision) |
| `players[].team` `hp` `spotted` | int | `m_iTeamNum`, `m_iHealth`, `m_bSpotted` |
| `players[].fx,fy,hx,hy` | int px | feet/head **already projected** into guest resolution `w×h` |

Projection lives **in the agent** (`esp_loop.js project()`) so the render layer
stays dumb; v2 must keep this split to reuse the overlay unchanged.

Read budget per frame: 1 ptr (local) + 1 ptr + 16 f32 (matrix) + 128 entry ptrs
+ ~8 reads/player — no scans, no native calls (Houdini-safe by construction).

## Rendering & geometry (esp_overlay.py)

- Window: `overrideredirect` + `-transparentcolor` (black) +
  `WS_EX_LAYERED | WS_EX_TRANSPARENT` → invisible except the drawing, and
  click-through. `SetProcessDPIAware()` before any coordinate math.
- Frame-to-screen: guest `w×h` projection space is linearly mapped onto the
  emulator's **client rect** (`find_emulator_client_rect()`); the emulator's
  internal resolution is passed to the agent as `w,h` so scale is exact.
- Style: lime = teammate, red = enemy; vertical HP bar at box left; gray status
  line top-left (`esp: N tracked` / error / "no players projected (menu?)").

## Robustness patterns — each one exists because of a real failure ✅

| # | Symptom | Fix (where) |
|---|---------|-------------|
| 1 | "nothing displays at all" — LDPlayer fullscreen re-raises its window and permanently buries a one-shot `-topmost` overlay | `keep_on_top()`: `SetWindowPos(HWND_TOPMOST, SWP_NOSIZE|NOMOVE|NOACTIVATE)` every 2 s on both overlay and pill (`esp_auto.supervise`) |
| 2 | overlay glued to a 229×35 rect at (−31996,−32000), or to Explorer's window titled "LDPlayer14 - …" | `find_emulator_client_rect()`: visible ∧ ¬iconic ∧ class/title match ∧ size floor 320×240 ∧ class-exclusion list ∧ **largest client area wins**; `None` → keep last-good geometry (never blank on a transient miss) |
| 3 | tkinter mainloop froze when an RPC hung on a dying agent | RPC polling moved to a **daemon worker thread**; mainloop only consumes queued frames |
| 4 | attach during game cold-start spammed re-attach cycles | agent `init()` failure returns `{ok:false, error:"modules loading"}` instead of throwing — supervisor polls again (Houdini maps appear late) |
| 5 | hung RPC wedged forever after game crash | 30 consecutive failures (`RPC_FAIL_LIMIT`, ~1 s) → forced detach/re-attach |
| 6 | 0-player frames looked like a broken tool | canvas is **never** blank — a status line always renders |
| 7 | no console in one-click mode → couldn't stop the service | separate clickable `Toplevel` pill "✕ ESP" (main overlay is click-through, so controls must be their own window) |
| 8 | `timeout.exe` in the bat tight-looped when stdin was redirected | all bat delays use `ping -n 4 127.0.0.1 >nul`; every wait loop capped (~3 min) with labeled errors. Bat files must be saved **CRLF** |

## Deployment modes

| Mode | Command | Use |
|------|---------|-----|
| One-click | `start_esp.bat` | cold boot everything |
| Supervised | `python esp_auto.py` | emulator already up |
| Manual one-shot | `python esp_overlay.py [pid]` | debugging; single attach, no recovery |

Paths policy (user directive): **never hardcode local paths in shipped files.**
`start_esp.bat` reads `python` / `adb` / `ldconsole` from `config.json` next to
it (parsed with PowerShell `ConvertFrom-Json` — no python bootstrap
dependency), falling back to PATH tools. `config.json` is gitignored; the repo
ships `config.example.json`. Python scripts take the adb path from `%ADB%`.

## Detectability profile & positioning (why this is lab-only)

v1 leaves substantial guest-visible traces: the frida-server daemon process,
the injected agent (anonymous executable regions in `/proc/<pid>/maps`,
`TracerPid != 0` during attach, open port 27042). It is fit for an authorized
R&D environment precisely **because none of that is checked here** — it is not
a covert design, and Phase 4 exists to replace it.

## Status

Complete and user-verified end-to-end (including cold emulator boot via the
bat). Frozen per maintainer decision — change nothing except porting it
([migration-guide.md](migration-guide.md)).
