# Architecture

## System topology

```
Windows host
├── ESP overlay process (Python/tkinter)      ← draws; v1 reads via Frida RPC
│     esp_overlay.py / esp_auto.py            ← v2: will read dnplayer.exe directly
├── dnplayer.exe  (LDPlayer 14, x86_64 QEMU-based)
│     guest RAM lives inside this process's address space   ← v2 read target ❓
│
│   Android guest (x86_64 system image)
│   ├── frida-server-x64  (/data/local/tmp)   ← v1 only
│   └── com.ledi.csno  (the game)
│         x86_64 process; arm64 game libs run via libhoudini
│         └── libkm_client_panorama_client.so  ← entities, local player, RecvTables
│             libkm_engine_client.so           ← CRender, view matrix
```

Key environment facts (all ✅ verified, details in
[phase2-dynamic.md](phase2-dynamic.md)):

- The **game process is x86_64**; `libkm_*.so` are arm64 binaries loaded through
  libhoudini. Under Houdini the original arm64 `.text` is mapped `r--p` (the
  translated code lives in separate JIT caches).
- Frida's `Module` API cannot see Houdini-loaded modules (it only covers the
  native linker namespace) — `resolveModule()` in `config.js` rebuilds module
  info from `/proc`-derived `Process.enumerateRanges` by matching file paths.
- On a native arm64 device none of these quirks apply, but the data model
  (formulas, netvars) is identical — see [migration-guide.md](migration-guide.md).

## The four logical layers

Every read path (v1 today, v2 planned) is split so that only layer 2 changes:

```
┌────────────────────────────────────────────────────────┐
│ 1  CONFIG           offsets.json / config.js           │  pure data:
│    (single source of truth — both files must stay in   │  netvars, formulas,
│     sync; config.js mirrors offsets.json for the agent)│  RVA seeds, sigs
├────────────────────────────────────────────────────────┤
│ 2  READ BACKEND     v1: esp_loop.js (frida RPC getFrame)│  the ONLY layer
│                     v2: host reader (pymem/ctypes)  ❓  │  that differs
├────────────────────────────────────────────────────────┤
│ 3  FRAME MODEL      JSON: { ok, players:[{hp,team,x,y, │  stable contract
│                     z,sx,sy,local,...}], localTeam,    │  across backends
│                     error? }                           │
├────────────────────────────────────────────────────────┤
│ 4  RENDER           esp_overlay.py: transparent,       │  backend-agnostic
│                     click-through, top-asserted window │  (reused as-is in v2)
└────────────────────────────────────────────────────────┘
```

The v2 contract is deliberately the same `getFrame()` JSON shape so the
renderer and supervisor need zero changes when the backend is swapped.

## Per-frame data flow (v1, shipped)

```
supervisor tick (30 Hz poll)
  → RPC getFrame() into agent
      local   = *(client + 0x1617F40)
      list    = client + 0x16432A0
      for i in 0..127:
          ent = *(list + 0x28 + 0x20*i)          # DIRECT C_BaseEntity*
          hp  = i32[ent+0x138]; team = i32[ent+0x12C]
          keep if hp>0 && team!=0                 # player filter
          origin = f32x3[ent+0x170] (+ eye 0x140 for head)
      M = 16×f32 at *(engine + 0xBA2220) + 0xA4   # view-proj VMatrix
      worldToScreen(origin, M, guestW, guestH) → sx,sy
  ← JSON frame
  → canvas redraw, mapped onto the emulator client rect
```

Read budget: ~130 pointer reads per frame, sub-millisecond. **Never** do
GB-scale `Memory.scan` passes in the loop — under Houdini a 3.1 GB scan froze
the game for 48 s (✅ measured; see phase2 doc, "hard perf constraint").

## Component map (repo files → responsibility)

| File | Layer | Responsibility |
|------|-------|----------------|
| `offsets.json` | 1 | Authoritative static config (documented in [offsets-reference.md](offsets-reference.md)) |
| `config.js` | 1+2-helpers | Agent-side mirror of offsets.json + `resolveModule` / `scanSig` / `adrpAddTarget` |
| `esp_loop.js` | 2+3 | v1 read backend: validates bases, serves `getFrame()` RPC |
| `frida_run.py` | 2-driver | Non-interactive one-shot script runner (verification harness) |
| `esp_overlay.py` | 4 | Overlay window: geometry tracking, W2S canvas mapping, colors, status line |
| `esp_auto.py` | supervisor | Lifecycle: emulator online → frida-server up → game attach/detach/re-attach, ✕ ESP stop pill |
| `start_esp.bat` | launcher | One-click cold start (emulator launch → boot wait → game start → supervisor) |

## Design rules (learned the hard way)

1. **No hardcoded runtime addresses** — every consumer resolves module bases at
   runtime and validates against RVA seeds or signatures first.
2. **Field offsets vs RVAs never mix** — netvars cross architectures; RVAs do
   not leave their build (see portability table in offsets-reference).
3. **The frame JSON is the seam.** Backends must not leak concepts (frida
   handles, process handles) above layer 3.
4. **Read-only everywhere.** The project never writes guest memory; the ESP is
   strictly an observer.
5. **UI robustness beats features**: overlay re-asserts topmost every 2 s,
   keeps last-good geometry when the window matcher fails, and never blanks the
   canvas (always a status line) — see phase3 doc for the failure stories.
