# Phase 2 — Dynamic Verification with Frida (✅ complete)

Goal: prove every Phase-1 claim against the **live process** before building
anything on top of it. Unknowns were tracked as K1–K5; all resolved.

## Environment facts (read this before debugging anything on-device)

| Fact | Consequence |
|------|-------------|
| LDPlayer 14 guest is **x86_64**; game libs are arm64 running under **libhoudini** | The game *process* is x86_64 → **use the x86_64 frida-server**. The arm64 server enumerates the process but **crashes on attach** (K5 ✅). |
| frida-server start (needs root) | `adb shell "su -c 'setsid /data/local/tmp/frida-server-x64 >/data/local/tmp/fs.log 2>&1 &'"` — `setsid` keeps it alive past the adb session |
| adb device ambiguity | LDPlayer may appear both as `emulator-5554` and `127.0.0.1:5555`; if commands get "more than one device", `adb disconnect` the stale one or use `adb -s <serial>`. Port for instance *n* is typically `5555 + 2n` |
| su quoting | Wrap the whole remote command in `su -c '…'` with outer double quotes — nested single quotes eat arguments silently |
| Install dir hash changes per reinstall | Never hardcode `/data/app/~~<hash>==/…`; resolve with `adb shell pm path com.ledi.csno` |

## Agent-side consequences of the x86_64-process / arm64-code mix ✅

1. **`libkm_*` modules are invisible to Frida's Module API** (it only covers
   the native x86_64 linker namespace) → `resolveModule()` in `config.js`
   reconstructs `{base, size, ranges}` from `Process.enumerateRanges('r--')` by
   matching `r.file.path`. On a native arm64 device the normal API path is
   taken automatically.
2. **arm64 `.text` is mapped `r--p`** (translation happens in separate JIT
   caches) → signature scans must cover `r--` ranges; the raw arm64 bytes are
   intact there and scan fine.
3. **Frida 17 removed the `Memory.readX` statics** → all reads use the
   `NativePointer` instance API (`p.add(off).readPointer()`).
4. **`NativeFunction` into arm64 code is impossible** from the x86_64 agent →
   the Phase-1 `GetClientEntity` wrapper+vcall hypothesis could not be tested by
   *calling* it; it was tested by *reading* instead — which is what exposed the
   static misreading (K1 below). Native-function validation is deferred to a
   real arm64 device (Phase 4 hardware pass, ❓).

## Verification scripts & results

Driver: `python frida_run.py <script.js> [pid]` (attaches, loads script +
`config.js`, prints agent log, detaches).

| Script | Proves | Result |
|--------|--------|--------|
| `verify_bases.js` | module resolution, RVA seeds, 3 wildcarded sigs decode to the seed addresses | ✅ MATCH (menu state) |
| `verify_recvtable.js` | live RecvTable walk from `DT_CSPlayer_RecvTable` vs static dump | ✅ **18/18 ESP netvars match, 0 mismatch**; runtime dump archived (now `reference/runtime_netvars_all_tables.txt`) |
| `verify_esp_core.js` | entity enumeration + matrix projection sanity in a live bot match | ✅ steps 3+4 PASS |

## Resolved unknowns

| ID | Question | Resolution ✅ |
|----|----------|---------------|
| **K1** | wrapper → entity raw offset? | **There is no wrapper/vcall.** Empirically: `entity(i) = *(client + 0x16432A0 + 0x28 + 0x20*i)` is a **DIRECT `C_BaseEntity*`**. The Phase-1 disasm reading was off by 0x20. Entry layout: `+0x00` entity\*, `+0x08` serial, `+0x10/+0x18` intrusive links. |
| **K2** | player index range? | Entry **0 = local player**; players occupy `1..N` (bot match: indices 0–9 = 10 players); unused slots null; **indices 64+ are world entities** (weapons/props, `team==0`). Filter: `hp > 0 && team != 0`. |
| **K3** | remote dormancy signal? | `m_bDormant` is **not networked** in this build; `m_nTickBase` (0x3C50) is `DT_LocalPlayerExclusive` — verified in-match: local ticks ~65/s, bots static by design. Use `m_bSpotted` (0xECD, networked) or origin-staleness tracking instead. |
| **K4** | does `CRender+0xA4` hold a usable view-proj matrix? | Yes — 16 row-major floats; standard Source W2S projected enemies **on-screen** (w ≈ 2000). |
| **K5** | frida-server arch under Houdini? | x86_64 binary required (see environment table above). |

## Hard performance constraint ✅

`Memory.scanSync` over GB-scale regions **freezes the game under Houdini**
— measured: a 3.1 GB pass took 48 s with the game unresponsive. Production
code must read **only the known entity array** (~130 pointers, milliseconds).
One-shot verification scans at menu time are acceptable; anything on a timer is not.

## Status

Phase 2 complete (2026-09-30). Nothing here is speculative; the table above is
the record. Re-run `verify_bases.js` after any game update before trusting
`offsets.json` again (RVA seeds are 🔧 build-specific).
